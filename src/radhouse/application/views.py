"""Permission-aware read models for the operator work home."""
from dataclasses import dataclass

from radhouse.domain.access import BotProfile
from radhouse.domain.tasks import Task, TaskTitle
from radhouse.domain.releases import Publication
from radhouse.domain.projects import ProjectCoordination


@dataclass(frozen=True)
class ActionView:
    enabled: bool
    reason: str | None = None


@dataclass(frozen=True)
class ProjectView:
    project_id: str
    display_name: str
    conversation_id: str
    binding_revision: int
    bot_ids: tuple[str, ...]
    coordination: ProjectCoordination | None = None


@dataclass(frozen=True)
class TaskCard:
    task: Task
    title: TaskTitle
    sequence: int
    cancel: ActionView
    pause: ActionView
    resume: ActionView
    review: ActionView
    publication: Publication | None = None


@dataclass(frozen=True)
class WorkHome:
    principal_id: str
    role: str
    project_id: str
    project_name: str
    agents: tuple[BotProfile, ...]
    tasks: tuple[TaskCard, ...]
    start: ActionView
