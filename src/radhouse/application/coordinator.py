"""One bounded coordinator cycle over durable task state.

The process scheduler owns repetition and shutdown. This component performs no
sleeping and emits only bounded public codes, so it is straightforward to run
under a service manager and to test without timing races.
"""
from dataclasses import dataclass
import re

from radhouse.application.service import Service
from radhouse.domain.tasks import Rejected, RuntimeFailure


_WORKER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


@dataclass(frozen=True)
class TaskAdvanceReceipt:
    task_id: str
    phase: str | None
    outcome: str | None
    error_code: str | None = None


@dataclass(frozen=True)
class CoordinatorCycle:
    worker_id: str
    receipts: tuple[TaskAdvanceReceipt, ...]


class Coordinator:
    def __init__(self, service: Service, worker_id: str, *, max_tasks_per_cycle: int = 16):
        if not _WORKER_ID.fullmatch(worker_id):
            raise ValueError("invalid_worker_id")
        if not 1 <= max_tasks_per_cycle <= 100:
            raise ValueError("invalid_cycle_limit")
        self.service = service
        self.worker_id = worker_id
        self.max_tasks_per_cycle = max_tasks_per_cycle

    def run_once(self) -> CoordinatorCycle:
        receipts = []
        for task_id in self.service.coordination_candidates(self.max_tasks_per_cycle):
            try:
                task = self.service.advance(task_id, self.worker_id)
                receipts.append(TaskAdvanceReceipt(task_id, task.phase, task.outcome))
            except (Rejected, RuntimeFailure) as error:
                # Codes are application-owned and bounded; vendor bodies and
                # exception representations do not enter coordinator evidence.
                receipts.append(TaskAdvanceReceipt(task_id, None, None, str(error)))
        return CoordinatorCycle(self.worker_id, tuple(receipts))
