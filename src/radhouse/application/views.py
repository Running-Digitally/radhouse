"""Permission-aware read models for the operator work home."""
from dataclasses import dataclass

from radhouse.domain.access import BotProfile
from radhouse.domain.tasks import Task


@dataclass(frozen=True)
class ActionView:
    enabled: bool
    reason: str | None = None


@dataclass(frozen=True)
class TaskCard:
    task: Task
    cancel: ActionView
    pause: ActionView
    resume: ActionView
    review: ActionView


@dataclass(frozen=True)
class WorkHome:
    principal_id: str
    role: str
    project_id: str
    agents: tuple[BotProfile, ...]
    tasks: tuple[TaskCard, ...]
    start: ActionView
