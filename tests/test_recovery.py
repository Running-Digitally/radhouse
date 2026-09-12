"""Agent recovery reattaches an exact durable run and never invents evidence."""
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys

import pytest

from radhouse.domain.tasks import Observation, Rejected
from tests.fakes import FakeAgentWork

pytestmark = pytest.mark.postgres


def test_lost_reply_recovers_same_runtime_run_without_repeat(
    service, service_factory, alice, envelope, start, fake_work, clock,
):
    fake_work.mode = "lost_reply_after_commit"
    task = service.admit(alice, envelope(), start)
    interrupted = service.run(task.task_id)
    assert interrupted.phase == "recovering"
    assert "operation_unknown" in interrupted.blockers

    restarted_work = FakeAgentWork(fake_work.path, clock=clock)
    fresh = service_factory(work=restarted_work)
    recovered = fresh.recover(task.task_id)

    assert recovered.outcome == "completed"
    assert recovered.attempt_id == interrupted.attempt_id
    assert recovered.budget_remaining == start.budget - 1
    assert restarted_work.start_count == 1
    assert restarted_work.attach_count == 1
    assert fresh.recover(task.task_id) == recovered
    assert fresh.run(task.task_id) == recovered


def test_absent_runtime_evidence_stays_unknown_across_provider_change(
    service_factory, alice, envelope, start, fake_work, fake_provider, clock,
):
    work = FakeAgentWork(fake_work.path, mode="unknown", clock=clock)
    service = service_factory(work=work)
    task = service.admit(alice, envelope(), start)
    interrupted = service.run(task.task_id)
    fake_provider.model_id = "model-B"
    changed = service.refresh_provider(task.task_id)
    recovered = service.recover(task.task_id)
    recovered_again = service.recover(task.task_id)

    assert changed.model_id == "model-B"
    assert recovered.phase == "recovering" and recovered.outcome is None
    assert recovered_again == recovered
    assert "operation_unknown" in recovered.blockers
    assert recovered.budget_remaining == interrupted.budget_remaining
    assert work.start_count == 1


def test_cancel_stops_only_the_recorded_run_and_reconciles_terminal_state(
    service_factory, alice, envelope, start, fake_work, clock,
):
    work = FakeAgentWork(fake_work.path, mode="running", clock=clock)
    service = service_factory(work=work)
    task = service.admit(alice, envelope(), start)
    active = service.run(task.task_id)
    assert active.phase == "active"

    stopping = service.cancel(
        alice, task.task_id, active.state_revision, envelope=envelope()
    )
    assert stopping.phase == "stopping" and stopping.outcome is None
    assert "cancel_requested" in stopping.blockers
    final = service.recover(task.task_id)

    assert final.outcome == "cancelled" and final.phase == "closed"
    assert work.start_count == 1
    assert service.run(task.task_id) == final
    late = Observation(task.task_id, final.attempt_id, final.generation, 100, "running")
    assert service.observe(late) == final


def test_cancel_after_lost_start_reply_reattaches_then_stops_exact_run(
    service_factory, alice, envelope, start, fake_work, clock,
):
    work = FakeAgentWork(fake_work.path, mode="lost_reply_after_commit", clock=clock)
    service = service_factory(work=work)
    task = service.admit(alice, envelope(), start)
    uncertain = service.run(task.task_id)
    assert uncertain.phase == "recovering"
    stopping = service.cancel(
        alice, task.task_id, uncertain.state_revision, envelope=envelope()
    )
    assert stopping.phase == "stopping"

    final = service.recover(task.task_id)

    assert final.outcome == "cancelled"
    assert work.start_count == 1 and work.attach_count == 1
    assert work.state(final.attempt_id) == "cancelled"


def test_expired_unknown_dispatch_never_reattaches(
    service_factory, alice, envelope, start, fake_work, clock,
):
    work = FakeAgentWork(fake_work.path, mode="lost_reply_after_commit", clock=clock)
    service = service_factory(work=work)
    task = service.admit(alice, envelope(), start)
    uncertain = service.run(task.task_id)
    clock.advance(days=2)

    still_unknown = service.recover(task.task_id)

    assert still_unknown.phase == "recovering"
    assert "operation_unknown" in still_unknown.blockers
    assert work.start_count == 1 and work.attach_count == 0


def test_independent_running_sibling_survives_exact_cancellation(
    service_factory, alice, envelope, start, fake_work, clock,
):
    work = FakeAgentWork(fake_work.path, mode="running", clock=clock)
    service = service_factory(work=work)
    first = service.admit(alice, envelope(), start)
    second = service.admit(alice, envelope(), start)
    first = service.run(first.task_id, "worker-one")
    second = service.run(second.task_id, "worker-two")

    stopping = service.cancel(
        alice, first.task_id, first.state_revision, envelope=envelope()
    )
    final = service.recover(stopping.task_id)

    assert final.outcome == "cancelled"
    assert work.state(first.attempt_id) == "cancelled"
    assert work.state(second.attempt_id) == "running"
    assert service.recover(second.task_id).phase == "active"


def test_withdrawn_grant_stops_an_already_running_exact_run(
    service_factory, alice, envelope, start, fake_work, clock, store,
):
    work = FakeAgentWork(fake_work.path, mode="running", clock=clock)
    service = service_factory(work=work)
    task = service.admit(alice, envelope(), start)
    active = service.run(task.task_id)
    with store.transaction() as tx:
        tx._connection.execute(
            "DELETE FROM public.bot_grants WHERE principal_id='alice' AND bot_id='bot-alpha'"
        )

    stopped = service.recover(task.task_id)

    assert stopped.phase == "closed" and stopped.outcome == "failed"
    assert "grant_withdrawal" in stopped.blockers
    assert work.state(active.attempt_id) == "cancelled"


def test_mismatched_acceptance_retains_exact_run_for_safe_stop(
    service_factory, alice, envelope, start, fake_work, clock, store,
):
    class MismatchedWork(FakeAgentWork):
        def start_or_attach(self, task, attempt, dispatch_key):
            accepted = super().start_or_attach(task, attempt, dispatch_key)
            return replace(accepted, runtime_revision="unexpected-runtime")

    work = MismatchedWork(fake_work.path, mode="running", clock=clock)
    service = service_factory(work=work)
    task = service.admit(alice, envelope(), start)

    attention = service.run(task.task_id)

    assert attention.phase == "recovering"
    assert "operation_unknown" in attention.blockers
    with store.transaction() as tx:
        dispatch = tx.dispatch(attention.attempt_id)
    assert dispatch.state == "accepted" and dispatch.run_id is not None
    stopping = service.cancel(
        alice, task.task_id, attention.state_revision, envelope=envelope()
    )
    assert stopping.phase == "stopping"
    assert service.recover(task.task_id).outcome == "cancelled"


def test_old_generation_duplicate_and_late_observations_do_not_regress(
    service, alice, envelope, start,
):
    task = service.admit(alice, envelope(), start)
    active = service.claim(task.task_id, "observer-worker")
    stale = Observation(task.task_id, active.attempt_id, active.generation - 1, 3, "completed")
    assert service.observe(stale) == active
    accepted = service.observe(replace(stale, generation=active.generation, state="running"))
    assert accepted.observation_sequence == 3
    assert service.observe(replace(stale, generation=active.generation, sequence=2)) == accepted
    assert service.observe(replace(stale, generation=active.generation)) == accepted
    cancelled = service.cancel(
        alice, task.task_id, accepted.state_revision, envelope=envelope()
    )
    assert service.observe(replace(stale, generation=active.generation, sequence=4)) == cancelled


def test_delivery_gap_resynchronizes_only_authorized_snapshot(
    service, alice, bob, envelope, start, store,
):
    task = service.admit(alice, envelope(), start)
    service.run(task.task_id)
    with store.transaction() as tx:
        events = tx.events(task.task_id, 0)
    assert len(events) >= 3
    import psycopg
    with psycopg.connect(os.environ["RADHOUSE_VS0_DSN"]) as connection:
        connection.execute(
            "DELETE FROM events WHERE task_id=%s AND cursor=%s",
            (task.task_id, events[1].cursor),
        )
    page = service.events(alice, task.task_id, events[0].cursor, envelope=envelope())
    assert page["resync_required"] and page["task"].task_id == task.task_id
    with pytest.raises(Rejected):
        service.events(bob, task.task_id, 0, envelope=envelope(principal="bob"))


def test_separate_controller_process_recovers_after_dispatch_commit(
    service, alice, envelope, start, fake_work, store,
):
    task = service.admit(alice, envelope(), start)
    environment = dict(os.environ, RADHOUSE_VS0_FAKE_TARGET=str(fake_work.path))
    script = Path(__file__).resolve().parents[1] / "scripts" / "vs0.py"
    crashed = subprocess.run(
        [sys.executable, str(script), "_controller", "run", task.task_id],
        env=environment, capture_output=True, text=True, timeout=20,
    )
    assert crashed.returncode == 73, crashed.stderr
    with store.transaction() as tx:
        interrupted = tx.task(task.task_id)
        assert tx.dispatch(interrupted.attempt_id).state == "submitted"
    recovered = subprocess.run(
        [sys.executable, str(script), "_controller", "recover", task.task_id],
        env=environment, capture_output=True, text=True, timeout=20,
    )
    assert recovered.returncode == 0, recovered.stderr
    with store.transaction() as tx:
        final = tx.task(task.task_id)
    runtime = FakeAgentWork(fake_work.path)
    assert final.task_id == interrupted.task_id and final.attempt_id == interrupted.attempt_id
    assert final.outcome == "completed" and runtime.start_count == 1
