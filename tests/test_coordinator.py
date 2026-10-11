from dataclasses import replace

import pytest

from radhouse.application.coordinator import Coordinator
from radhouse.domain.tasks import Rejected
from radhouse.domain.tasks import RuntimeActivity, RuntimeResult


class RecordingService:
    def __init__(self):
        self.seen = []

    def coordination_candidates(self, limit):
        assert limit == 3
        return ("task-one", "task-bad", "task-two")

    def advance(self, task_id, worker_id):
        self.seen.append((task_id, worker_id))
        if task_id == "task-bad":
            raise Rejected("task_state_inconsistent")
        return type("TaskResult", (), {"phase": "closed", "outcome": "completed"})()


def test_cycle_is_bounded_and_continues_after_one_sanitized_failure():
    service = RecordingService()
    cycle = Coordinator(service, "worker-one", max_tasks_per_cycle=3).run_once()

    assert service.seen == [
        ("task-one", "worker-one"),
        ("task-bad", "worker-one"),
        ("task-two", "worker-one"),
    ]
    assert [receipt.error_code for receipt in cycle.receipts] == [
        None, "task_state_inconsistent", None,
    ]


@pytest.mark.parametrize("worker_id", ["", " worker", "worker/one", "x" * 129])
def test_worker_identity_is_bounded(worker_id):
    with pytest.raises(ValueError, match="invalid_worker_id"):
        Coordinator(RecordingService(), worker_id)


@pytest.mark.postgres
def test_cycle_advances_independent_tasks_up_to_its_limit(
    service, alice, envelope, start, fake_work,
):
    tasks = [
        service.admit(alice, envelope(), replace(start, resource_key=f"resource-{index}"))
        for index in range(2)
    ]

    first_cycle = Coordinator(service, "worker-one", max_tasks_per_cycle=1).run_once()
    second_cycle = Coordinator(service, "worker-one", max_tasks_per_cycle=1).run_once()

    assert len(first_cycle.receipts) == len(second_cycle.receipts) == 1
    assert {first_cycle.receipts[0].task_id, second_cycle.receipts[0].task_id} == {
        task.task_id for task in tasks
    }
    assert all(receipt.outcome == "completed" for receipt in (
        first_cycle.receipts[0], second_cycle.receipts[0],
    ))
    assert fake_work.start_count == 2


@pytest.mark.postgres
def test_human_paused_task_waits_until_the_operator_resumes_it(
    service, alice, envelope, start, fake_work,
):
    task = service.admit(alice, envelope(), start)
    active = service.claim(task.task_id, "worker-one")
    paused = service.pause(alice, task.task_id, active.state_revision, envelope=envelope())

    assert Coordinator(service, "worker-one").run_once().receipts == ()
    assert fake_work.start_count == 0

    service.resume(alice, task.task_id, paused.state_revision, envelope=envelope())
    cycle = Coordinator(service, "worker-one").run_once()
    assert cycle.receipts[0].outcome == "completed"
    assert fake_work.start_count == 1


@pytest.mark.postgres
@pytest.mark.parametrize("content", [None, "", " \n\t"])
def test_empty_runtime_completion_stays_unverified_without_redispatch(
    service, store, alice, envelope, start, fake_work, content,
):
    fake_work.result = lambda *_: RuntimeResult("completed", content)
    task = service.admit(alice, envelope(), start)
    first = service.run(task.task_id)
    assert first.phase != "closed" and first.outcome is None
    assert "operation_unknown" in first.blockers
    assert first.result is None and first.result_digest is None
    recovered = service.recover(task.task_id)
    assert recovered.attempt_id == first.attempt_id
    assert recovered.phase != "closed" and recovered.outcome is None
    assert fake_work.start_count == 1
    with store.transaction() as tx:
        assert tx.publication(task.task_id) is None
    fake_work.result = lambda *_: RuntimeResult("failed")
    failed = service.recover(task.task_id)
    assert failed.phase == "closed" and failed.outcome == "failed"
    assert failed.result is None and fake_work.start_count == 1


@pytest.mark.postgres
def test_runtime_activity_is_durable_deduplicated_and_does_not_advance_task_state(
    service, store, alice, envelope, start, fake_work,
):
    activity = RuntimeActivity(
        "run-activity", "tool.started", "Using an assigned tool", 1_795_000_000
    )
    fake_work.result = lambda *_: RuntimeResult("running", activity=activity)
    task = service.admit(alice, envelope(), start)
    active = service.run(task.task_id)
    recovered = service.recover(task.task_id)

    assert recovered.state_revision == active.state_revision
    with store.transaction() as tx:
        events = [event for event in tx.events(task.task_id, 0)
                  if event.kind == "runtime_activity"]
        assert len(events) == 1
        assert events[0].data["label"] == "Using an assigned tool"
        assert tx.latest_event(task.task_id, "runtime_activity") == events[0]


@pytest.mark.postgres
def test_provider_outage_yields_to_healthy_work_across_coordinator_restarts(
    service, service_factory, store, alice, envelope, start, fake_provider, monkeypatch,
):
    with store.transaction() as tx:
        tx._connection.execute("UPDATE bots SET provider_binding='offline-model' WHERE bot_id='bot-alpha'")
    monkeypatch.setattr("radhouse.application.service.uuid4", lambda: "00000000-0000-4000-8000-000000000001")
    blocked = service.admit(alice, envelope(), replace(start, provider_binding="offline-model"))
    monkeypatch.setattr("radhouse.application.service.uuid4", lambda: "ffffffff-ffff-4fff-8fff-ffffffffffff")
    ready = service.admit(alice, envelope(project_id="project-shared"),
                          replace(start, project_id="project-shared", bot_id="bot-beta"))
    monkeypatch.undo()
    describe = fake_provider.describe
    fake_provider.describe = lambda binding: replace(describe(binding), available=binding != "offline-model")
    first = Coordinator(service, "first-process", max_tasks_per_cycle=1).run_once()
    second = Coordinator(service_factory(), "restarted-process", max_tasks_per_cycle=1).run_once()
    assert first.receipts[0].task_id == blocked.task_id
    assert second.receipts[0].task_id == ready.task_id
    assert second.receipts[0].outcome == "completed"


@pytest.mark.postgres
def test_scheduler_rotation_is_fair_and_does_not_grow_task_history(
    service, service_factory, store, alice, envelope, start,
):
    tasks = [service.admit(alice, envelope(), start) for _ in range(3)]
    before = service.events(alice, tasks[0].task_id, envelope=envelope())["events"]
    turns = [service_factory().coordination_candidates(1)[0] for _ in range(9)]
    expected = sorted(task.task_id for task in tasks)
    assert turns == expected * 3
    assert service.events(alice, tasks[0].task_id, envelope=envelope())["events"] == before
    with store.transaction() as tx:
        assert tx._connection.execute("SELECT count(*) AS n FROM task_coordination").fetchone()["n"] == 3


@pytest.mark.postgres
@pytest.mark.parametrize("content, oversized", [("x" * 65536, False), ("é" * 32769, True)])
def test_result_size_limit_closes_dispatch_and_releases_resource_claim(
    service, store, alice, envelope, start, fake_work, content, oversized,
):
    fake_work.result_content = content
    task = service.admit(alice, envelope(), replace(start, resource_key="shared-report"))
    done = service.run(task.task_id)
    assert done.phase == "closed"
    assert done.outcome == ("failed" if oversized else "completed")
    assert ("result_too_large" in done.blockers) == oversized
    assert done.result == (None if oversized else content)
    assert service.recover(task.task_id) == done
    assert fake_work.start_count == 1
    with store.transaction() as tx:
        assert tx.dispatch(done.attempt_id).state == "closed"
        assert tx.attempt(done.attempt_id).state == "finished"
        assert tx._connection.execute("SELECT count(*) AS n FROM claims WHERE task_id=%s AND active", (task.task_id,)).fetchone()["n"] == 0
