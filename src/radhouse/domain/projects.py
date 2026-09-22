"""Durable state for one user-visible project delivery thread."""

from dataclasses import dataclass, field, replace
from typing import Literal

from radhouse.domain.tasks import Rejected


ProjectPhase = Literal[
    "intake",
    "planning",
    "research",
    "building",
    "preview_feedback",
    "review",
    "correction",
    "merge_ready",
    "deployment",
    "deployed",
    "blocked",
    "paused",
]


@dataclass(frozen=True)
class ProjectCoordination:
    project_id: str
    revision: int = 1
    phase: ProjectPhase = "intake"
    active_bot_id: str | None = None
    active_task_id: str | None = None
    latest_task_id: str | None = None
    pending_message_id: str | None = None
    repository: str | None = None
    branch: str | None = None
    pull_request: str | None = None
    source_revision: str | None = None
    preview_url: str | None = None
    preview_revision: str | None = None
    preview_digest: str | None = None
    accepted_preview_revision: str | None = None
    reviewed_revision: str | None = None
    reviewer_verdict: str | None = None
    merged_revision: str | None = None
    deployment_url: str | None = None
    deployed_revision: str | None = None
    deployment_status: str | None = None
    # Small public summaries only. Raw files and task content stay in their
    # existing bounded stores rather than being copied into project state.
    status_note: str | None = None
    handoff_bot_id: str | None = None
    handoff_brief: str | None = None
    planning_task_id: str | None = None
    planning_source_message_id: str | None = None

    def evolve(self, **changes) -> "ProjectCoordination":
        return replace(self, revision=self.revision + 1, **changes)

    def validate(self) -> "ProjectCoordination":
        values = (
            self.project_id,
            self.active_bot_id,
            self.active_task_id,
            self.latest_task_id,
            self.pending_message_id,
            self.repository,
            self.branch,
            self.pull_request,
            self.source_revision,
            self.preview_url,
            self.preview_revision,
            self.preview_digest,
            self.accepted_preview_revision,
            self.reviewed_revision,
            self.reviewer_verdict,
            self.merged_revision,
            self.deployment_url,
            self.deployed_revision,
            self.deployment_status,
            self.status_note,
            self.handoff_bot_id,
            self.handoff_brief,
            self.planning_task_id,
            self.planning_source_message_id,
        )
        if (
            self.revision < 1
            or not self.project_id
            or any(value is not None and len(value) > 4096 for value in values)
            or (self.active_task_id is None) != (self.active_bot_id is None)
            or (self.planning_task_id is None) != (self.planning_source_message_id is None)
            or self.planning_task_id is not None
            and self.planning_task_id != self.active_task_id
            or self.accepted_preview_revision is not None
            and self.accepted_preview_revision != self.preview_revision
            or self.reviewed_revision is not None
            and self.reviewed_revision != self.preview_revision
            or self.deployed_revision is not None
            and self.deployed_revision != self.merged_revision
        ):
            raise Rejected("invalid_project_coordination", 422)
        return self
