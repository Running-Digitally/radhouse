"""Task state is independent of runtime sessions and channel deliveries."""
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal

Phase = Literal["queued", "active", "recovering", "stopping", "closed"]
Outcome = Literal["completed", "cancelled", "failed"]


class Rejected(Exception):
    """A bounded, public error code; never a vendor payload or credential."""

    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True)
class StartTask:
    bot_id: str
    project_id: str
    brief: str
    provider_binding: str
    resource_key: str | None = None
    budget: int = 3


@dataclass(frozen=True)
class Task:
    task_id: str
    owner_id: str
    bot_id: str
    project_id: str
    brief: str
    provider_binding: str
    resource_key: str | None
    budget_remaining: int
    task_revision: int = 1
    state_revision: int = 1
    phase: Phase = "queued"
    outcome: Outcome | None = None
    blockers: tuple[str, ...] = ()
    attempt_id: str | None = None
    generation: int = 0
    model_id: str | None = None
    result: str | None = None
    result_digest: str | None = None
    observation_sequence: int = 0

    def evolve(self, **changes) -> "Task":
        return replace(self, state_revision=self.state_revision + 1, **changes)

    def blocked(self, reason: str) -> "Task":
        return self.evolve(blockers=tuple(sorted(set(self.blockers) | {reason})))


@dataclass(frozen=True)
class Attempt:
    attempt_id: str
    task_id: str
    generation: int
    worker_id: str
    state: str = "reserved"


@dataclass(frozen=True)
class Operation:
    key: str
    task_id: str
    attempt_id: str
    state: Literal["prepared", "submitted", "confirmed", "unknown", "rejected"]
    result: str | None = None


@dataclass(frozen=True)
class AgentDispatch:
    key: str
    task_id: str
    attempt_id: str
    session_id: str
    provider_binding: str
    request_digest: str
    state: Literal["prepared", "submitted", "accepted", "unknown", "closed"]
    run_id: str | None = None
    runtime_revision: str | None = None
    submitted_at: datetime | None = None
    retention_until: datetime | None = None


@dataclass(frozen=True)
class RuntimeCapabilities:
    runtime_revision: str
    idempotency_retention_seconds: int


@dataclass(frozen=True)
class RuntimeDispatch:
    run_id: str
    session_id: str
    provider_binding: str
    runtime_revision: str
    submitted_at: datetime
    retention_until: datetime


@dataclass(frozen=True)
class RuntimeResult:
    state: Literal["running", "completed", "failed", "cancelled", "unknown"]
    content: str | None = None


@dataclass(frozen=True)
class Observation:
    task_id: str
    attempt_id: str
    generation: int
    sequence: int
    state: Literal["running", "stopped", "completed", "unknown"]


@dataclass(frozen=True)
class ProviderDescription:
    binding: str
    model_id: str
    available: bool = True
    compatible: bool = True


@dataclass(frozen=True)
class EffectResult:
    state: Literal["confirmed", "unknown", "rejected"]
    result: str | None = None


@dataclass(frozen=True)
class Event:
    task_id: str
    kind: str
    state_revision: int
    data: dict = field(default_factory=dict)
    cursor: int = 0


@dataclass(frozen=True)
class SavedCommand:
    principal_id: str
    command_key: str
    fingerprint: str
    task_id: str


@dataclass(frozen=True)
class Delivery:
    channel: str
    event_id: str
    principal_id: str
    fingerprint: str
    task_id: str
    kind: str


class LostReply(Exception):
    """An external operation may have committed; reconcile, never redispatch."""


class RuntimeFailure(Exception):
    """A bounded runtime failure code with no vendor response or credential."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
