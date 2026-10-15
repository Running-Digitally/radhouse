from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace

from fastapi.testclient import TestClient
import pytest

from radhouse.api.app import create_app
from radhouse.application.work_service import WorkService
from radhouse.domain.tasks import Rejected, RuntimeFailure, RuntimeResult
from radhouse.domain.work import WorkCommand
from radhouse.storage.postgres import PostgresUnitOfWork
from tests.fakes import channel_actor
from tests.test_runtime_controls import receipt
from tests.test_work_lifecycle import work_service, result

pytestmark = pytest.mark.postgres


def command(view, kind, text=None):
    return WorkCommand(kind, view.state_revision, view.scope_revision, text)


def test_work_controls_replay_across_channels_and_restart(work_service, service, service_factory, alice, envelope, start):
    work = work_service.submit(alice, envelope(), start)
    identity = envelope('buzz')
    pause = command(work, 'pause')
    paused = work_service.apply_command(channel_actor(alice, 'buzz'), work.work_id, pause, envelope=identity)
    assert paused.work.state == 'paused' and paused.application_state == 'applied'
    fresh = WorkService(service_factory())
    replay = fresh.apply_command(alice, work.work_id, pause,
        envelope=replace(envelope(), command_key=identity.command_key))
    assert replay.receipt == paused.receipt
    resumed = fresh.apply_command(alice, work.work_id, command(replay.work, 'resume'), envelope=envelope())
    historical = fresh.apply_command(alice, work.work_id, pause,
        envelope=replace(envelope(), command_key=identity.command_key))
    assert historical.receipt.application_state == 'applied'
    assert historical.work.state != 'paused'
    stopped = fresh.apply_command(alice, work.work_id, command(resumed.work, 'cancel'), envelope=envelope())
    assert stopped.work.state == 'cancelled' and stopped.application_state == 'applied'
    assert service.coordination_candidates(10) == ()


def test_work_command_receipt_and_transition_are_atomic(work_service, service, alice, envelope, start, monkeypatch):
    work = work_service.submit(alice, envelope(), start)
    identity = envelope()
    def fail(*_): raise RuntimeError('before commit')
    monkeypatch.setattr(PostgresUnitOfWork, 'insert_work_command', fail)
    with pytest.raises(RuntimeError):
        work_service.apply_command(alice, work.work_id, command(work, 'pause'), envelope=identity)
    assert work_service.get(alice, work.work_id, envelope=envelope()) == work
    with service.store.transaction() as tx:
        assert tx.command(alice.principal_id, identity.command_key) is None
        assert tx.delivery(identity.channel, identity.event_id) is None
        assert tx.task(work.task_id).blockers == ()


def test_stale_scope_payload_and_source_conflicts_are_denied(work_service, alice, envelope, start):
    work = work_service.submit(alice, envelope(), start)
    identity = envelope()
    paused = work_service.apply_command(alice, work.work_id, command(work, 'pause'), envelope=identity)
    with pytest.raises(Rejected, match='command_conflict'):
        work_service.apply_command(alice, work.work_id, command(work, 'cancel'), envelope=identity)
    with pytest.raises(Rejected, match='stale_work_state'):
        work_service.apply_command(alice, work.work_id, command(work, 'cancel'), envelope=envelope())
    with pytest.raises(Rejected, match='scope_changed'):
        work_service.apply_command(alice, work.work_id, replace(command(paused.work, 'cancel'), scope_revision=2), envelope=envelope())
    with pytest.raises(Rejected, match='delivery_conflict'):
        work_service.apply_command(alice, work.work_id, command(paused.work, 'resume'),
            envelope=replace(envelope(), event_id=identity.event_id))


def test_concurrent_commands_have_one_revision_winner(work_service, alice, envelope, start):
    work = work_service.submit(alice, envelope(), start)
    def apply(kind):
        try:
            return work_service.apply_command(alice, work.work_id, command(work, kind), envelope=envelope()).receipt.kind
        except Rejected as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as workers:
        values = list(workers.map(apply, ('pause', 'cancel')))
    assert values.count('stale_work_state') == 1
    assert len(set(values) & {'pause', 'cancel'}) == 1


@pytest.mark.parametrize('kind', ['pause', 'cancel'])
def test_crash_after_stop_intent_before_runtime_start_never_starts_work(work_service, service, alice, envelope, start, fake_work, monkeypatch, kind):
    work = work_service.submit(alice, envelope(), start)
    service.claim(work.task_id, 'worker')
    work = work_service.get(alice, work.work_id, envelope=envelope())
    original = service._finish_hold
    def crash(*_): raise RuntimeError('after committed intent')
    monkeypatch.setattr(service, '_finish_hold', crash)
    with pytest.raises(RuntimeError):
        work_service.apply_command(alice, work.work_id, command(work, kind), envelope=envelope())
    monkeypatch.setattr(service, '_finish_hold', original)
    service.recover(work.task_id)
    assert fake_work.start_count == 0
    assert work_service.get(alice, work.work_id, envelope=envelope()).state == ('paused' if kind == 'pause' else 'cancelled')


def test_queued_cancel_is_closed_before_stop_settlement(work_service, service, alice, envelope, start, fake_work, monkeypatch):
    work = work_service.submit(alice, envelope(), start)
    def inspect(*_):
        assert service.coordination_candidates(10) == ()
        assert service.get(alice, work.task_id, envelope=envelope()).outcome == 'cancelled'
    monkeypatch.setattr(service, '_finish_hold', inspect)
    work_service.apply_command(alice, work.work_id, command(work, 'cancel'), envelope=envelope())
    assert fake_work.start_count == 0


def test_queued_pause_receipt_survives_lost_response_then_resume(work_service, service, alice, envelope, start, monkeypatch):
    work = work_service.submit(alice, envelope(), start)
    identity = envelope()
    pause = command(work, 'pause')
    def lose(*_): raise RuntimeError('after committed pause')
    monkeypatch.setattr(service, '_finish_hold', lose)
    with pytest.raises(RuntimeError):
        work_service.apply_command(alice, work.work_id, pause, envelope=identity)
    paused = work_service.get(alice, work.work_id, envelope=envelope())
    work_service.apply_command(alice, work.work_id, command(paused, 'resume'), envelope=envelope())
    replay = work_service.apply_command(alice, work.work_id, pause, envelope=identity)
    assert replay.application_state == 'applied' and replay.work.state == 'queued'


def test_pause_racing_with_capability_io_fences_prepared_runtime_start(work_service, service, alice, envelope, start, fake_work):
    work = work_service.submit(alice, envelope(), start)
    original = fake_work.capabilities
    def pause(task):
        view = work_service.get(alice, work.work_id, envelope=envelope())
        work_service.apply_command(alice, work.work_id, command(view, 'pause'), envelope=envelope())
        return original(task)
    fake_work.capabilities = pause
    service.run(work.task_id)
    assert fake_work.start_count == 0
    assert work_service.get(alice, work.work_id, envelope=envelope()).state == 'paused'


@pytest.mark.parametrize('lost', [False, True])
def test_guidance_uses_one_original_runtime_control_and_durable_work_receipt(work_service, service, service_factory, alice, envelope, start, fake_work, lost):
    work = work_service.submit(alice, envelope(), start)
    fake_work.mode = 'running'
    service.run(work.task_id)
    work = work_service.get(alice, work.work_id, envelope=envelope())
    calls = []
    def steer(task, run, text, control_id):
        calls.append(control_id)
        if lost: raise RuntimeFailure('runtime_lost_reply')
        return receipt(run, control_id, text)
    fake_work.steer = steer
    identity = envelope()
    update = command(work, 'guidance', 'Focus on cost.')
    first = work_service.apply_command(alice, work.work_id, update, envelope=identity)
    fresh = WorkService(service_factory())
    second = fresh.apply_command(alice, work.work_id, update, envelope=identity)
    assert first.receipt == second.receipt and len(calls) == 1
    assert first.application_state == ('unknown' if lost else 'accepted')
    assert fake_work.start_count == 1
    with service.store.transaction() as tx:
        assert tx.command(alice.principal_id, identity.command_key) is not None
        assert tx.operation(calls[0]) is not None


def test_guidance_state_race_does_not_send_or_save_partial_receipt(work_service, service, alice, envelope, start, fake_work):
    work = work_service.submit(alice, envelope(), start)
    fake_work.mode = 'running'
    service.run(work.task_id)
    work = work_service.get(alice, work.work_id, envelope=envelope())
    capabilities = fake_work.capabilities
    calls = []
    def move_state(task):
        work_service.apply_command(alice, work.work_id, command(work, 'pause'), envelope=envelope())
        return capabilities(task)
    fake_work.capabilities = move_state
    fake_work.steer = lambda *_a, **_k: calls.append(True)
    identity = envelope()
    with pytest.raises(Rejected):
        work_service.apply_command(alice, work.work_id, command(work, 'guidance', 'Update'), envelope=identity)
    with service.store.transaction() as tx:
        assert tx.command(alice.principal_id, identity.command_key) is None
    assert not calls


def test_current_authority_is_required_even_for_command_replay(work_service, service, alice, bob, envelope, start):
    work = work_service.submit(alice, envelope(), start)
    identity = envelope()
    pause = command(work, 'pause')
    work_service.apply_command(alice, work.work_id, pause, envelope=identity)
    with pytest.raises(Rejected):
        work_service.apply_command(bob, work.work_id, pause, envelope=envelope(principal='bob'))
    with service.store.transaction() as tx:
        tx._connection.execute("DELETE FROM bot_grants WHERE principal_id='alice'")
    with pytest.raises(Rejected):
        work_service.apply_command(alice, work.work_id, pause, envelope=identity)


def test_api_strict_work_command_and_completed_result_are_not_reopened(work_service, service, alice, envelope, start, fake_work):
    work = work_service.submit(alice, envelope(), start)
    client = TestClient(create_app(service, lambda _: alice))
    body = {'envelope': asdict(envelope()), **asdict(command(work, 'pause'))}
    response = client.post(f'/v1/work/{work.work_id}/commands', json=body)
    assert response.status_code == 200 and response.json()['work']['state'] == 'paused'
    invalid = client.post(f'/v1/work/{work.work_id}/commands', json={**body, 'authority': 'deploy'})
    assert invalid.status_code == 422
    paused = work_service.get(alice, work.work_id, envelope=envelope())
    work_service.apply_command(alice, work.work_id, command(paused, 'resume'), envelope=envelope())
    fake_work.result_content = result(work)
    service.run(work.task_id)
    done = work_service.get(alice, work.work_id, envelope=envelope())
    with pytest.raises(Rejected, match='work_not_accepting_control'):
        work_service.apply_command(alice, work.work_id, command(done, 'resume'), envelope=envelope())
