"""Opt-in descriptor admission and persistent synthetic HTTP runtime recovery."""
from dataclasses import replace
from datetime import datetime, timezone
import json
import sqlite3
import hashlib

import httpx
import pytest

from radhouse.application.work_service import WorkService
from radhouse.domain.tasks import RuntimeResult, RuntimeFailure
from radhouse.integrations.hermes import HermesAgentWorkAdapter, HermesRunsClient
from tests.test_work_lifecycle import work_service, result


def descriptor(now, **changes):
    return dict(contract='radhouse-runtime-v1', bot_id='bot-alpha', profile='researcher',
        runtime_revision='fixture-v1', provider_binding='fake-local', result_protocol='work-result-v1',
        observations='durable-sequence-v1', durable_runs=True, durable_workspace=True,
        admission='ready', hold_reason=None, max_parallel_runs=1, observed_at=int(now.timestamp()),
        guidance_receipts=False, **changes)


def adapter(handler, clock):
    client = HermesRunsClient('http://127.0.0.1:8642', 'synthetic-token', transport=httpx.MockTransport(handler))
    return HermesAgentWorkAdapter(client, runtime_revision='fixture-v1', clock=clock,
        expected_bot_id='bot-alpha', expected_profile='researcher', expected_provider_binding='fake-local',
        descriptor_required=True)


@pytest.mark.parametrize('change,code', [
    ({'bot_id':'another-bot'},'runtime_identity_mismatch'),
    ({'profile':'deployer'},'runtime_identity_mismatch'),
    ({'runtime_revision':'old'},'runtime_version_mismatch'),
    ({'provider_binding':'other-model'},'runtime_provider_mismatch'),
    ({'contract':'v99'},'runtime_contract_unavailable'),
    ({'observations':'transient'},'runtime_contract_unavailable'),
    ({'observed_at':1},'runtime_descriptor_stale'),
    ({'admission':'held','hold_reason':'manual_stop'},'runtime_admission_held'),
    ({'durable_workspace':False},'runtime_contract_unavailable'),
    ({'durable_runs':1},'runtime_contract_unavailable'),
    ({'max_parallel_runs':True},'runtime_contract_unavailable'),
    ({'unknown_field':'private'},'runtime_contract_unavailable'),
])
def test_descriptor_refuses_identity_version_staleness_and_unsupported_contract(clock, change, code):
    value = {**descriptor(clock()), **change}
    calls=[]
    def handler(request):
        calls.append(request.method)
        return httpx.Response(200,json=value)
    runtime=adapter(handler,clock)
    try:
        with pytest.raises(RuntimeFailure, match=code): runtime.describe('bot-alpha', require_ready=True)
        assert calls==['GET']
    finally: runtime.client.close()


def test_held_descriptor_remains_observable_without_reopening_admission(clock):
    value={**descriptor(clock()), 'admission':'held', 'hold_reason':'maintenance'}
    runtime=adapter(lambda _:httpx.Response(200,json=value),clock)
    try:
        assert runtime.describe('bot-alpha').admission=='held'
        with pytest.raises(RuntimeFailure,match='runtime_admission_held'):
            runtime.describe('bot-alpha',require_ready=True)
    finally: runtime.client.close()


def test_duplicate_runtime_identity_field_is_refused(clock):
    payload=json.dumps(descriptor(clock())).replace('"bot_id": "bot-alpha"',
        '"bot_id": "another-bot", "bot_id": "bot-alpha"')
    runtime=adapter(lambda _:httpx.Response(200,content=payload),clock)
    try:
        with pytest.raises(RuntimeFailure,match='runtime_malformed_response'):runtime.describe('bot-alpha')
    finally:runtime.client.close()


@pytest.mark.postgres
@pytest.mark.parametrize('stop', [False, True])
def test_persistent_http_runtime_lost_start_reply_restart_and_missing_progress(work_service, service, service_factory,
        store, alice, envelope, start, clock, tmp_path, stop):
    path=tmp_path/'runtime.sqlite3'
    workspace=tmp_path/'runtime-workspace';workspace.mkdir()
    retained=workspace/'note.txt'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE runs (key TEXT PRIMARY KEY, run TEXT, session TEXT, sequence INTEGER, status TEXT, output TEXT, digest TEXT)')
    work=work_service.submit(alice,envelope(),start)
    output=result(work)
    lost=[True]
    held=[False]
    def handler(request):
        assert request.headers['Authorization']=='Bearer synthetic-token'
        if request.url.path=='/v1/radhouse/descriptor':
            value=descriptor(clock())
            if held[0]: value.update(admission='held',hold_reason='maintenance')
            return httpx.Response(200,json=value)
        if request.url.path=='/v1/capabilities':
            return httpx.Response(200,json={'features':{'runs_idempotency':{'supported':True,'durable':True,'retention_seconds':3600}}})
        with sqlite3.connect(path) as db:
            if request.method=='POST' and request.url.path=='/v1/runs':
                data=json.loads(request.content)
                key=request.headers['Idempotency-Key']
                existing=db.execute('SELECT * FROM runs WHERE key=?',(key,)).fetchone()
                digest=hashlib.sha256(request.content).hexdigest()
                if existing is not None and existing[6]!=digest:return httpx.Response(409,json={'error':'conflict'})
                if existing is None:
                    db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?)',(key,'run-1',data['session_id'],1,'running',None,digest))
                    db.commit()
                    retained.write_text('Retained workspace data')
                if lost and lost.pop(): raise httpx.ReadError('lost after durable start')
                return httpx.Response(202,json={'run_id':'run-1','session_id':data['session_id'],
                    'status':'running','replayed':existing is not None},
                    headers={'Idempotency-Replayed':'true' if existing else 'false'})
            row=db.execute('SELECT * FROM runs WHERE run=?',('run-1',)).fetchone()
            if request.method=='POST' and request.url.path=='/v1/runs/run-1/stop':
                if row[4] not in {'completed','cancelled','failed'}:
                    db.execute('UPDATE runs SET sequence=sequence+1,status=?',('cancelled',))
                    row=db.execute('SELECT * FROM runs WHERE run=?',('run-1',)).fetchone()
            return httpx.Response(200,json={'run_id':row[1],'status':row[4],'output':row[5],'observation_sequence':row[3]})
    runtime=adapter(handler,clock)
    service.work=runtime
    service.run(work.task_id)
    with store.transaction() as tx: assert tx.task(work.task_id).phase=='recovering'
    runtime.client.close()
    # Fresh adapter/controller attaches the original SQLite-backed identity.
    runtime=adapter(handler,clock)
    fresh=service_factory(work=runtime); fresh.durable_work_enabled=True
    try:
        fresh.recover(work.task_id)
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT count(*) FROM runs').fetchone()[0]==1
            if not stop: db.execute('UPDATE runs SET sequence=2,status=?,output=?',('completed',output))
        if stop:
            from radhouse.domain.work import WorkCommand
            held[0]=True
            current=WorkService(fresh).get(alice,work.work_id,envelope=envelope())
            WorkService(fresh).apply_command(alice,work.work_id,
                WorkCommand('cancel',current.state_revision,current.scope_revision),envelope=envelope())
        fresh.recover(work.task_id)
        view=WorkService(fresh).get(alice,work.work_id,envelope=envelope())
        assert view.state==('cancelled' if stop else 'completed')
        assert (view.artifact is not None) is (not stop)
        assert retained.read_text()=='Retained workspace data'
        with store.transaction() as tx:
            task=tx.task(work.task_id); dispatch=tx.dispatch(task.attempt_id)
            assert dispatch.run_id=='run-1' and dispatch.observation_sequence==2
        with sqlite3.connect(path) as db: assert db.execute('SELECT count(*) FROM runs').fetchone()[0]==1
    finally: runtime.client.close()


@pytest.mark.postgres
def test_crash_after_observation_cursor_commit_replays_same_terminal_result(work_service, service, service_factory,
        alice, envelope, start, fake_work, store, monkeypatch):
    work=work_service.submit(alice,envelope(),start)
    fake_work.result=lambda *_:RuntimeResult('completed',result(work),observation_sequence=1)
    def crash(*_):raise RuntimeError('after cursor commit')
    monkeypatch.setattr(service,'_finish_work',crash)
    with pytest.raises(RuntimeError):service.run(work.task_id)
    with store.transaction() as tx:
        task=tx.task(work.task_id)
        assert tx.dispatch(task.attempt_id).observation_sequence==1 and task.result is None
    fresh=service_factory();fresh.durable_work_enabled=True
    fresh.recover(work.task_id)
    assert WorkService(fresh).get(alice,work.work_id,envelope=envelope()).state=='completed'
    assert fake_work.start_count==1


@pytest.mark.postgres
def test_stale_and_conflicting_runtime_observations_cannot_promote_output(work_service, service, alice,
        envelope, start, fake_work, store):
    work=work_service.submit(alice,envelope(),start)
    fake_work.mode='running'
    fake_work.result=lambda *_: RuntimeResult('running', observation_sequence=2)
    service.run(work.task_id)
    fake_work.result=lambda *_: RuntimeResult('completed',result(work),observation_sequence=1)
    service.recover(work.task_id)
    assert work_service.get(alice,work.work_id,envelope=envelope()).state=='active'
    fake_work.result=lambda *_: RuntimeResult('completed',result(work),observation_sequence=2)
    service.recover(work.task_id)
    assert work_service.get(alice,work.work_id,envelope=envelope()).state=='waiting'
    with store.transaction() as tx:
        task=tx.task(work.task_id)
        assert tx.dispatch(task.attempt_id).observation_sequence==2 and task.result is None
    fake_work.result=lambda *_: RuntimeResult('completed',result(work),observation_sequence=3)
    service.recover(work.task_id)
    assert work_service.get(alice,work.work_id,envelope=envelope()).state=='completed'
