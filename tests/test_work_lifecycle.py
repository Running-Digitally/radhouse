"""Outcome acceptance, privacy and recovery against owned real PostgreSQL."""
from dataclasses import asdict, replace
import json

from fastapi.testclient import TestClient
import pytest

from radhouse.api.app import create_app
from radhouse.application.coordinator import Coordinator
from radhouse.application.work_service import WorkService
from radhouse.domain.tasks import Rejected
from radhouse.storage.postgres import PostgresUnitOfWork
from tests.fakes import channel_actor

pytestmark = pytest.mark.postgres


@pytest.fixture
def work_service(service):
    service.durable_work_enabled = True
    return WorkService(service)


def result(work, *, outcome='succeeded', artifact=True, reason=None, **changes):
    value = dict(protocol='work-result-v1', work_id=work.work_id, scope_revision=1,
        step_key='deliver-artifact', outcome=outcome, summary='Prepared the requested report.',
        artifact=dict(name='report.md', media_type='text/markdown', content='# Report\nUseful synthetic result.') if artifact else None,
        reason_code=reason, checkpoint=None)
    value.update(changes)
    return json.dumps(value)


def test_two_requests_coexist_status_is_read_only_and_current_artifact_opens(work_service, service, alice, envelope, start, fake_work):
    first = work_service.submit(alice, envelope(), start)
    second = work_service.submit(alice, envelope(), replace(start, brief='Create another report'))
    assert first.work_id != second.work_id
    fake_work.result_content = result(first)
    service.run(first.task_id)
    done = work_service.get(alice, first.work_id, envelope=envelope())
    assert done.state == 'completed' and done.state_label == 'Done'
    assert done.artifact.sha256 and done.artifact.attempt_id
    assert work_service.artifact(alice, done.work_id, done.artifact.artifact_id, envelope=envelope())[1].startswith('# Report')
    before = len(service.coordination_candidates(100))
    for _ in range(3):
        assert work_service.get(alice, done.work_id, envelope=envelope()) == done
    assert len(service.coordination_candidates(100)) == before
    home = service.work_home(alice, envelope=envelope())
    assert len(home.tasks) == 2 and home.tasks[0].work.work_id == second.work_id
    assert home.attention == () and not home.tasks[1].review.enabled


@pytest.mark.parametrize('content', [
    'Completed. The release is blocked by a token.', '{}', 'null', '{broken json',
])
def test_completed_run_without_valid_contract_remains_visible_and_unfinished(work_service, service, alice, envelope, start, fake_work, content):
    work = work_service.submit(alice, envelope(), start)
    fake_work.result_content = content
    service.run(work.task_id)
    view = work_service.get(alice, work.work_id, envelope=envelope())
    assert view.state == 'waiting' and view.blockers[0].code == 'result_invalid'
    assert not view.needs_input and view.artifact is None
    for _ in range(3): Coordinator(service, 'worker').run_once()
    assert fake_work.start_count == 1
    assert service.work_home(alice, envelope=envelope()).tasks[0].work == view


@pytest.mark.parametrize('outcome,artifact,reason,state', [
    ('succeeded', False, None, 'waiting'),
    ('incomplete', True, 'budget_exhausted', 'waiting'),
    ('blocked', True, 'dependency_unavailable', 'waiting'),
    ('failed', False, 'acceptance_unmet', 'failed'),
    ('cancelled', False, 'acceptance_unmet', 'waiting'),
])
def test_acceptance_is_independent_of_runtime_completion(work_service, service, alice, envelope, start, fake_work, outcome, artifact, reason, state):
    work = work_service.submit(alice, envelope(), start)
    fake_work.result_content = result(work, outcome=outcome, artifact=artifact, reason=reason)
    service.run(work.task_id)
    view = work_service.get(alice, work.work_id, envelope=envelope())
    assert view.state == state and not view.needs_input
    assert bool(view.artifact) == artifact


@pytest.mark.parametrize('changes', [dict(scope_revision=2), dict(work_id='another-work'), dict(reason_code='permission_granted'), dict(checkpoint=42), dict(authority='root')])
def test_runtime_cannot_change_scope_identity_or_authority(work_service, service, alice, envelope, start, fake_work, changes):
    work = work_service.submit(alice, envelope(), start)
    fake_work.result_content = result(work, **changes)
    service.run(work.task_id)
    view = work_service.get(alice, work.work_id, envelope=envelope())
    assert view.state == 'waiting' and view.artifact is None


def test_work_task_and_wakeup_commit_atomically(work_service, service, alice, envelope, start, monkeypatch):
    def fail(*args): raise RuntimeError('injected before parent commit')
    monkeypatch.setattr(PostgresUnitOfWork, 'insert_work', fail)
    with pytest.raises(RuntimeError): work_service.submit(alice, envelope(), start)
    with service.store.transaction() as tx:
        assert tx.tasks() == [] and tx.work_items('alice', 'personal-alice') == []
    assert service.coordination_candidates(10) == ()


def test_lost_admission_reply_replays_same_work_after_new_controller(work_service, service_factory, alice, envelope, start):
    command = envelope()
    first = work_service.submit(alice, command, start)
    fresh = WorkService(service_factory())
    fresh.service.durable_work_enabled = True
    assert fresh.submit(alice, command, start).work_id == first.work_id
    with pytest.raises(Rejected, match='delivery_conflict'):
        fresh.submit(alice, command, replace(start, brief='Different intent'))
    assert fresh.service.coordination_candidates(10) == (first.task_id,)


def test_lost_start_reply_reattaches_original_run(work_service, service, service_factory, alice, envelope, start, fake_work):
    work = work_service.submit(alice, envelope(), start)
    fake_work.mode = 'lost_reply_after_commit'
    fake_work.result_content = result(work)
    service.run(work.task_id)
    fresh = service_factory()
    Coordinator(fresh, 'restarted').run_once()
    assert work_service.get(alice, work.work_id, envelope=envelope()).state == 'completed'
    assert fake_work.start_count == 1 and fake_work.attach_count == 1


def test_private_artifact_denies_other_owner_and_revoked_grant(work_service, service, alice, bob, envelope, start, fake_work):
    command = envelope(project_id='project-shared')
    work = work_service.submit(alice, command, replace(start, project_id='project-shared'))
    fake_work.result_content = result(work); service.run(work.task_id)
    view = work_service.get(alice, work.work_id, envelope=command)
    with pytest.raises(Rejected):
        work_service.artifact(bob, work.work_id, view.artifact.artifact_id,
            envelope=envelope(principal='bob', project_id='project-shared'))
    with service.store.transaction() as tx:
        tx._connection.execute("DELETE FROM bot_grants WHERE principal_id='alice' AND bot_id='bot-alpha'")
    with pytest.raises(Rejected):
        work_service.artifact(alice, work.work_id, view.artifact.artifact_id, envelope=command)


def test_wrong_artifact_work_and_corrupt_content_are_refused(work_service, service, alice, envelope, start, fake_work):
    first = work_service.submit(alice, envelope(), start)
    second = work_service.submit(alice, envelope(), start)
    fake_work.result_content = result(first); service.run(first.task_id)
    view = work_service.get(alice, first.work_id, envelope=envelope())
    with pytest.raises(Rejected, match='artifact_not_found'):
        work_service.artifact(alice, second.work_id, view.artifact.artifact_id, envelope=envelope())
    with service.store.transaction() as tx:
        tx._connection.execute('UPDATE work_artifacts SET content=%s WHERE artifact_id=%s', ('tampered',view.artifact.artifact_id))
    with pytest.raises(Rejected, match='artifact_integrity_failure'):
        work_service.artifact(alice, first.work_id, view.artifact.artifact_id, envelope=envelope())


def test_pause_cancel_and_unknown_workflow_prevent_new_dispatch(work_service, service, alice, envelope, start, fake_work):
    work = work_service.submit(alice, envelope(), start)
    fake_work.mode = 'running'
    task = service.run(work.task_id)
    service.pause(alice, task.task_id, task.state_revision, envelope=envelope())
    service.recover(task.task_id)
    view = work_service.get(alice, work.work_id, envelope=envelope())
    assert view.state == 'paused'
    with service.store.transaction() as tx: task = tx.task(task.task_id)
    service.cancel(alice, task.task_id, task.state_revision, envelope=envelope())
    assert work_service.get(alice, work.work_id, envelope=envelope()).state == 'cancelled'
    another = work_service.submit(alice, envelope(), start)
    with service.store.transaction() as tx:
        row = tx.work_item(another.work_id)
        tx.save_work(replace(row, workflow_version='artifact-v2',state_revision=row.state_revision+1),row.state_revision)
    Coordinator(service,'v1').run_once()
    assert work_service.get(alice, another.work_id, envelope=envelope()).blockers[0].code == 'workflow_upgrade_required'
    service.run(another.task_id)
    assert fake_work.start_count == 1


def test_api_contract_authenticated_status_artifact_and_disabled_admission(service, work_service, alice, envelope, start, fake_work):
    client = TestClient(create_app(service, authenticate=lambda request: alice))
    command = envelope()
    body = {'envelope':asdict(command), 'start':asdict(start)}
    body['start'].pop('allowed_tools')
    admitted = client.post('/v1/work', json=body)
    assert admitted.status_code == 201
    work = work_service.get(alice, admitted.json()['work_id'], envelope=command)
    fake_work.result_content = result(work); service.run(work.task_id)
    params = {'conversation_id':command.conversation_id,'binding_revision':1}
    done = client.get('/v1/work/'+work.work_id,params=params)
    assert done.status_code == 200 and done.headers['cache-control'] == 'no-store'
    artifact = done.json()['artifact']
    opened = client.get('/v1/work/'+work.work_id+'/artifacts/'+artifact['artifact_id'],params=params)
    assert opened.status_code == 200 and opened.text.startswith('# Report')
    assert opened.headers['content-disposition'].startswith('attachment;')
    service.durable_work_enabled = False
    assert client.post('/v1/work',json=body).json()['code'] == 'work_admission_disabled'
    assert client.get('/v1/work/'+work.work_id,params=params).status_code == 200
    anonymous = TestClient(create_app(service,authenticate=lambda request: None))
    assert anonymous.get('/v1/work/'+work.work_id,params=params).status_code == 401


def test_same_application_path_reads_across_channels_without_new_model_call(work_service, service, alice, envelope, start):
    work = work_service.submit(alice, envelope(), start)
    buzz = channel_actor(alice,'buzz')
    assert work_service.get(buzz, work.work_id, envelope=envelope('buzz')).work_id == work.work_id
    assert service.work_home(buzz,envelope=envelope('buzz')).tasks[0].work.work_id == work.work_id


def test_owner_attention_uses_same_permission_projection_as_card(work_service, service, alice, envelope, start, fake_work):
    from radhouse.domain.tasks import RuntimeResult
    work = work_service.submit(alice, envelope(), start)
    fake_work.mode = 'running'
    fake_work.result = lambda *_: RuntimeResult('running', permission_request={'request_id':'decision-one','command':'bounded action'})
    service.run(work.task_id)
    home = service.work_home(alice,envelope=envelope())
    assert home.tasks[0].work.needs_input
    assert home.tasks[0].work.state_label == 'Needs your input'
    assert home.attention == (work.work_id,)


def test_oversized_terminal_output_is_unfinished_without_endless_repoll(work_service, service, alice, envelope, start, fake_work):
    work = work_service.submit(alice,envelope(),start)
    fake_work.result_content = 'x' * 65537
    task = service.run(work.task_id)
    assert task.phase == 'closed' and task.result is None
    assert work_service.get(alice,work.work_id,envelope=envelope()).state == 'waiting'
    assert service.coordination_candidates(10) == ()


def test_duplicate_json_fields_and_raw_protocol_publication_are_denied(work_service, service, alice, envelope, start, fake_work):
    work = work_service.submit(alice,envelope(),start)
    fake_work.result_content = result(work).replace('"scope_revision": 1', '"scope_revision": 1, "scope_revision": 1')
    task = service.run(work.task_id)
    assert work_service.get(alice,work.work_id,envelope=envelope()).state == 'waiting'
    with pytest.raises(Rejected,match='artifact_review_required'):
        service.prepare_review(alice,task.task_id,task.state_revision,('alice',),300,envelope=envelope())
