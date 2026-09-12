"""Deterministic database races use distinct transaction connections, no sleeps."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import pytest

from radhouse.domain.tasks import Attempt, Rejected, Task
from radhouse.storage.postgres import FixtureBoundaryError, PostgresStore


RUN_ID = "abcdef1234567890"
DATABASE = f"radhouse_vs0_{RUN_ID}"


@pytest.mark.parametrize("dsn", [
    f"host=192.0.2.1 dbname={DATABASE}",
    f"host=example.invalid dbname={DATABASE}",
    f"host=/tmp dbname={DATABASE}",
    f"dbname={DATABASE}",
    f"host=127.0.0.1,192.0.2.1 dbname={DATABASE}",
    f"host=127.0.0.1 hostaddr=192.0.2.1 dbname={DATABASE}",
    f"host=192.0.2.1 hostaddr=127.0.0.1 dbname={DATABASE}",
    "host=127.0.0.1 dbname=postgres",
    f"host=127.0.0.1 dbname={DATABASE}0",
    f"host=127.0.0.1 dbname={DATABASE} service=alternate",
    f"host=127.0.0.1 dbname={DATABASE} options='-c search_path=unowned'",
    "postgresql://fixture@192.0.2.1:5432/" + DATABASE,
])
def test_unowned_or_remote_targets_rejected_before_connect(dsn, monkeypatch):
    def forbidden_connect(*args, **kwargs):
        raise AssertionError("a refused target must never be contacted")
    monkeypatch.setattr("radhouse.storage.postgres.psycopg.connect", forbidden_connect)
    with pytest.raises(FixtureBoundaryError):
        PostgresStore(dsn, RUN_ID)


@pytest.mark.parametrize("run_id", ["", "not-a-run", "../abcdef123456", "ABCDEF123456", "a" * 49])
def test_invalid_run_id_rejected_before_connect(run_id):
    with pytest.raises(FixtureBoundaryError):
        PostgresStore(f"host=127.0.0.1 dbname=radhouse_vs0_{run_id}", run_id)


def _parallel(*actions):
    gate = Barrier(len(actions))

    def run(action):
        gate.wait(timeout=10)
        return action()

    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        futures = [pool.submit(run, action) for action in actions]
        return [future.result(timeout=20) for future in futures]


def _insert_task(store, alice):
    task = Task(f"task-{uuid4().hex}", alice.principal_id, "bot-alpha", "personal-alice",
                "Synthetic reservation test", "fake-local", "synthetic-resource", 3)
    with store.transaction() as uow:
        uow.insert_task(task)
    return task


@pytest.mark.postgres
def test_stale_cas_cannot_overwrite_concurrent_progress(store, alice):
    task = _insert_task(store, alice)

    def save(brief):
        try:
            with store.transaction() as uow:
                uow.save_task(task.evolve(brief=brief, task_revision=2), task.state_revision)
            return "saved"
        except Rejected as exc:
            return exc.code

    outcomes = _parallel(lambda: save("Synthetic edit one"), lambda: save("Synthetic edit two"))
    assert sorted(outcomes) == ["revision_conflict", "saved"]
    with store.transaction() as uow:
        current = uow.task(task.task_id)
        assert current.state_revision == 2
        assert current.brief in {"Synthetic edit one", "Synthetic edit two"}


@pytest.mark.postgres
def test_claim_and_budget_roll_back_together(store, alice):
    task = _insert_task(store, alice)
    attempt = Attempt(f"attempt-{uuid4().hex}", task.task_id, 1, "worker-synthetic")
    with pytest.raises(RuntimeError, match="fixture_interrupt"):
        with store.transaction() as uow:
            assert uow.claim(task, attempt)
            active = task.evolve(phase="active", attempt_id=attempt.attempt_id,
                                 generation=1, budget_remaining=2)
            uow.save_task(active, task.state_revision)
            raise RuntimeError("fixture_interrupt")
    with store.transaction() as uow:
        assert uow.task(task.task_id) == task
        assert uow.attempt(attempt.attempt_id) is None
        # A later attempt can obtain the same resource: no orphaned claim or
        # per-attempt reservation survived the failed transaction.
        assert uow.claim(task, attempt)
        uow.save_task(task.evolve(phase="active", attempt_id=attempt.attempt_id,
                                 generation=1, budget_remaining=2), task.state_revision)


@pytest.mark.postgres
@pytest.mark.parametrize("same_delivery", [False, True])
def test_concurrent_idempotent_admission_has_one_task(service, store, alice, envelope, start, same_delivery):
    first = envelope(command_key="synthetic-command", event_id="synthetic-event-one")
    second = first if same_delivery else envelope(command_key="synthetic-command", event_id="synthetic-event-two")
    results = _parallel(lambda: service.admit(alice, first, start),
                        lambda: service.admit(alice, second, start))
    assert results[0].task_id == results[1].task_id
    with store.transaction() as uow:
        assert len(uow.tasks()) == 1
        assert uow.command(alice.principal_id, first.command_key).task_id == results[0].task_id
        assert uow.delivery(first.channel, first.event_id).task_id == results[0].task_id
        assert uow.delivery(second.channel, second.event_id).task_id == results[0].task_id
    with pytest.raises(Rejected, match="command_conflict"):
        service.admit(alice, envelope(command_key=first.command_key), replace(start, brief="Different synthetic input"))


@pytest.mark.postgres
def test_two_workers_reserve_one_attempt_and_one_budget_unit(service, store, alice, envelope, start):
    task = service.admit(alice, envelope(), start)
    results = _parallel(lambda: service.claim(task.task_id, "worker-one"),
                        lambda: service.claim(task.task_id, "worker-two"))
    assert {result.phase for result in results} == {"active"}
    assert len({result.attempt_id for result in results}) == 1
    assert {result.budget_remaining for result in results} == {start.budget - 1}
    with store.transaction() as uow:
        current = uow.task(task.task_id)
        assert current.generation == 1
        assert uow.attempt(current.attempt_id).worker_id in {"worker-one", "worker-two"}
        # Direct count checks independent invariant columns, not a cached snapshot.
        row = uow._connection.execute(
            "SELECT (SELECT count(*) FROM public.attempts WHERE task_id=%s AND is_current) AS owners, "
            "(SELECT sum(amount) FROM public.budget_reservations WHERE task_id=%s) AS spent",
            (task.task_id, task.task_id),
        ).fetchone()
        assert row == {"owners": 1, "spent": 1}


@pytest.mark.postgres
def test_two_workers_execute_one_agent_run(service, store, fake_work, alice, envelope, start):
    task = service.admit(alice, envelope(), start)
    _parallel(lambda: service.run(task.task_id, "worker-one"),
              lambda: service.run(task.task_id, "worker-two"))
    with store.transaction() as uow:
        current = uow.task(task.task_id)
    assert current.outcome == "completed"
    assert current.budget_remaining == start.budget - 1
    assert fake_work.start_count == 1


@pytest.mark.postgres
def test_independent_tasks_stay_active_and_cancel_preserves_other_claim(service, store, alice, envelope, start):
    first = service.admit(alice, envelope(), replace(start, resource_key="synthetic-resource-a"))
    second = service.admit(alice, envelope(), replace(start, resource_key="synthetic-resource-b"))
    active_first, active_second = _parallel(lambda: service.claim(first.task_id, "worker-one"),
                                          lambda: service.claim(second.task_id, "worker-two"))
    assert active_first.phase == active_second.phase == "active"
    assert active_first.bot_id == active_second.bot_id
    assert active_first.attempt_id != active_second.attempt_id
    cancelled = service.cancel(alice, first.task_id, active_first.state_revision, envelope=envelope())
    assert cancelled.outcome == "cancelled"
    with store.transaction() as uow:
        assert uow.task(second.task_id) == active_second
        assert uow.attempt(active_first.attempt_id).state == "finished"
        assert uow.attempt(active_second.attempt_id).state == "reserved"
    conflicting = service.admit(alice, envelope(), replace(start, resource_key="synthetic-resource-b"))
    waiting = service.claim(conflicting.task_id, "worker-three")
    assert waiting.phase == "queued"
    assert "resource_busy" in waiting.blockers
    assert waiting.budget_remaining == start.budget
    assert service.get(alice, second.task_id, envelope=envelope()) == active_second


@pytest.mark.postgres
def test_conflicting_claim_waits_without_spending_budget_then_proceeds_after_cancel(service, alice, envelope, start):
    scoped = replace(start, resource_key="synthetic-exclusive-resource")
    first = service.admit(alice, envelope(), scoped)
    second = service.admit(alice, envelope(), scoped)
    results = _parallel(lambda: service.claim(first.task_id, "worker-one"),
                        lambda: service.claim(second.task_id, "worker-two"))
    assert sorted(result.phase for result in results) == ["active", "queued"]
    active = next(result for result in results if result.phase == "active")
    waiting = next(result for result in results if result.phase == "queued")
    assert waiting.attempt_id is None
    assert waiting.generation == 0
    assert waiting.budget_remaining == start.budget
    assert "resource_busy" in waiting.blockers
    service.cancel(alice, active.task_id, active.state_revision, envelope=envelope())
    claimed = service.claim(waiting.task_id, "worker-three")
    assert claimed.phase == "active"
    assert claimed.generation == 1
    assert claimed.budget_remaining == start.budget - 1
    assert not claimed.blockers


@pytest.mark.postgres
def test_pause_resume_preserves_prepared_attempt_and_spent_budget(service, store, fake_work, alice, envelope, start):
    task = service.admit(alice, envelope(), start)
    active = service.claim(task.task_id, "worker-one")
    paused = service.pause(alice, task.task_id, active.state_revision, envelope=envelope())
    assert paused.phase == "active"
    assert "human_pause" in paused.blockers
    assert paused.attempt_id == active.attempt_id
    assert paused.budget_remaining == active.budget_remaining == start.budget - 1
    assert service.run(task.task_id, "worker-one").blockers == paused.blockers
    assert fake_work.start_count == 0
    resumed = service.resume(alice, task.task_id, paused.state_revision, envelope=envelope())
    assert resumed.attempt_id == active.attempt_id
    finished = service.run(task.task_id, "worker-one")
    assert finished.outcome == "completed"
    assert finished.attempt_id == active.attempt_id
    assert finished.budget_remaining == start.budget - 1
    assert fake_work.start_count == 1
    with store.transaction() as uow:
        assert uow.dispatch(active.attempt_id).attempt_id == active.attempt_id


@pytest.mark.postgres
@pytest.mark.parametrize("statement", [
    "CREATE TABLE public.forbidden_runtime_ddl (value integer)",
    "UPDATE public.fixture_ownership SET run_id=run_id",
    "UPDATE public.radhouse_metadata SET schema_version=schema_version",
])
def test_runtime_role_cannot_modify_schema_or_identity_ownership(store, statement):
    from psycopg.errors import InsufficientPrivilege

    with pytest.raises(InsufficientPrivilege):
        with store.transaction() as uow:
            uow._connection.execute(statement)
            # Roll back even when this security assertion fails on a bad fixture.
            raise AssertionError("runtime role unexpectedly has bootstrap authority")


@pytest.mark.parametrize("ownership", [
    None,
    [],
    [{"run_id": "0000000000000000", "database": DATABASE}],
    [{"run_id": RUN_ID, "database": "postgres"}],
    [{"run_id": RUN_ID, "database": DATABASE}] * 2,
])
def test_missing_or_mismatched_marker_never_exposes_unit_of_work(monkeypatch, ownership):
    from psycopg.errors import UndefinedTable

    class MarkerConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, parameters=()):
            if "public.fixture_ownership" not in query:
                raise AssertionError("unowned connections cannot proceed beyond ownership check")
            if ownership is None:
                raise UndefinedTable("synthetic absent marker")
            return self

        def fetchall(self):
            return ownership

    monkeypatch.setattr("radhouse.storage.postgres.psycopg.connect", lambda **kwargs: MarkerConnection())
    store = PostgresStore(f"host=127.0.0.1 dbname={DATABASE}", RUN_ID)
    with pytest.raises(FixtureBoundaryError):
        with store.transaction():
            raise AssertionError("an unowned fixture exposed transactional access")
