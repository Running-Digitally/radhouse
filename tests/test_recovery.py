"""Recovery requires durable target evidence, never an optimistic retry."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from radhouse.domain.tasks import EffectResult, LostReply, Observation, Rejected
from tests.fakes import FakeOperations, FakeRuntime

pytestmark = pytest.mark.postgres


def test_lost_reply_recovers_same_operation_without_repeat(service, service_factory, alice, envelope, start, fake_operations):
    fake_operations.mode = "lost_reply_after_commit"
    task = service.admit(alice, envelope(), start)
    interrupted = service.run(task.task_id)
    assert interrupted.phase == "recovering"
    assert "operation_unknown" in interrupted.blockers
    fresh = service_factory(operations=FakeOperations(fake_operations.path), runtime=FakeRuntime(fake_operations.path))
    recovered = fresh.recover(task.task_id)
    assert recovered.outcome == "completed"
    assert recovered.attempt_id == interrupted.attempt_id
    assert recovered.budget_remaining == start.budget - 1
    assert fake_operations.effect_count == fake_operations.execute_count == 1
    assert fresh.recover(task.task_id) == recovered
    assert fresh.run(task.task_id) == recovered


def test_late_lost_reply_does_not_regress_a_terminal_operation(
    service_factory, alice, envelope, start, store,
):
    """Another reconciler may settle the operation before the caller loses its reply."""
    holder = {}

    class SettleThenLoseReply:
        def execute(self, task, operation_key):
            holder["service"].recover(task.task_id)
            raise LostReply()

        def lookup(self, operation_key):
            return EffectResult("rejected")

    service = service_factory(operations=SettleThenLoseReply())
    holder["service"] = service
    task = service.admit(alice, envelope(), start)

    final = service.run(task.task_id)

    assert final.phase == "closed" and final.outcome == "failed"
    with store.transaction() as tx:
        assert tx.operation(task.task_id + ":report").state == "rejected"


def test_late_effect_reply_does_not_regress_a_terminal_operation(
    service_factory, alice, envelope, start, store,
):
    holder = {}

    class SettleThenReply:
        def execute(self, task, operation_key):
            holder["service"].recover(task.task_id)
            return EffectResult("confirmed", "stale reply")

        def lookup(self, operation_key):
            return EffectResult("rejected")

    service = service_factory(operations=SettleThenReply())
    holder["service"] = service
    task = service.admit(alice, envelope(), start)

    final = service.run(task.task_id)

    assert final.phase == "closed" and final.outcome == "failed"
    assert final.result is None
    with store.transaction() as tx:
        assert tx.operation(task.task_id + ":report").state == "rejected"


def test_absent_receipt_stays_unknown_across_recovery_and_provider_change(service, alice, envelope, start, fake_operations, fake_provider):
    fake_operations.mode = "unknown_without_receipt"
    task = service.admit(alice, envelope(), start)
    interrupted = service.run(task.task_id)
    fake_provider.model_id = "model-B"
    changed = service.refresh_provider(task.task_id)
    recovered = service.recover(task.task_id)
    recovered_again = service.recover(task.task_id)
    service.run(task.task_id)
    assert changed.model_id == "model-B"
    assert recovered.phase == "recovering" and recovered.outcome is None
    assert recovered_again == recovered
    assert "operation_unknown" in recovered.blockers
    assert recovered.budget_remaining == interrupted.budget_remaining
    assert fake_operations.execute_count == 1 and fake_operations.effect_count == 0


def test_cancellation_preserves_uncertainty_and_late_receipt_cannot_restart(service, alice, envelope, start, fake_operations):
    fake_operations.mode = "unknown_without_receipt"
    task = service.admit(alice, envelope(), start)
    active = service.run(task.task_id)
    stopped = service.cancel(alice, task.task_id, active.state_revision, envelope=envelope())
    assert stopped.phase == "stopping" and stopped.outcome is None
    assert {"cancel_requested", "operation_unknown"} <= set(stopped.blockers)
    # Simulate later authoritative target evidence, without another execution.
    with fake_operations.connect() as target:
        target.execute("INSERT INTO effects VALUES (?,?,?)", (task.task_id + ":report", task.task_id, "Late committed result"))
    final = service.recover(task.task_id)
    assert final.outcome == "cancelled" and final.phase == "closed"
    assert service.run(task.task_id) == final
    assert service.observe(Observation(task.task_id, final.attempt_id, final.generation, 100, "running")) == final
    assert fake_operations.execute_count == 1


def test_old_generation_duplicate_and_late_observations_do_not_regress(service, alice, envelope, start):
    task = service.admit(alice, envelope(), start)
    active = service.claim(task.task_id, "observer-worker")
    stale = Observation(task.task_id, active.attempt_id, active.generation - 1, 3, "completed")
    assert service.observe(stale) == active
    accepted = service.observe(replace(stale, generation=active.generation, state="running"))
    assert accepted.observation_sequence == 3
    assert service.observe(replace(stale, generation=active.generation, sequence=2)) == accepted
    assert service.observe(replace(stale, generation=active.generation)) == accepted
    cancelled = service.cancel(alice, task.task_id, accepted.state_revision, envelope=envelope())
    assert service.observe(replace(stale, generation=active.generation, sequence=4)) == cancelled


def test_delivery_gap_resynchronizes_only_authorized_snapshot(service, alice, bob, envelope, start, store):
    task = service.admit(alice, envelope(), start)
    service.run(task.task_id)
    with store.transaction() as tx:
        events = tx.events(task.task_id, 0)
    assert len(events) >= 3
    import psycopg
    with psycopg.connect(os.environ["RADHOUSE_VS0_DSN"]) as connection:
        connection.execute("DELETE FROM events WHERE task_id=%s AND cursor=%s", (task.task_id, events[1].cursor))
    page = service.events(alice, task.task_id, events[0].cursor, envelope=envelope())
    assert page["resync_required"] and page["task"].task_id == task.task_id
    with pytest.raises(Rejected):
        service.events(bob, task.task_id, 0, envelope=envelope(principal="bob"))


def test_separate_controller_process_survives_hard_crash_after_target_commit(service, alice, envelope, start, fake_operations, store):
    task = service.admit(alice, envelope(), start)
    environment = dict(os.environ, RADHOUSE_VS0_FAKE_TARGET=str(fake_operations.path))
    script = Path(__file__).resolve().parents[1] / "scripts" / "vs0.py"
    crashed = subprocess.run([sys.executable, str(script), "_controller", "run", task.task_id],
                             env=environment, capture_output=True, text=True, timeout=20)
    assert crashed.returncode == 73, crashed.stderr
    with store.transaction() as tx:
        interrupted = tx.task(task.task_id)
        assert tx.operation(task.task_id + ":report").state == "submitted"
    recovered = subprocess.run([sys.executable, str(script), "_controller", "recover", task.task_id],
                               env=environment, capture_output=True, text=True, timeout=20)
    assert recovered.returncode == 0, recovered.stderr
    with store.transaction() as tx:
        final = tx.task(task.task_id)
    assert final.task_id == interrupted.task_id and final.attempt_id == interrupted.attempt_id
    assert final.outcome == "completed" and fake_operations.execute_count == fake_operations.effect_count == 1
