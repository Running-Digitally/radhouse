from dataclasses import replace

import pytest

from radhouse.application.coordinator import Coordinator
from radhouse.domain.tasks import Rejected


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
