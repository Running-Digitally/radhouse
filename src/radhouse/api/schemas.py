"""Strict public wire values. Authority is never accepted from request bodies."""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from radhouse.channels.commands import Envelope
from radhouse.domain.tasks import StartTask

Identifier = Annotated[str, Field(min_length=1, max_length=200)]
Revision = Annotated[int, Field(ge=1)]
Audience = Annotated[list[Identifier], Field(min_length=1, max_length=32)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, from_attributes=True)


class EnvelopeSchema(StrictModel):
    channel: Identifier
    event_id: Identifier
    conversation_id: Identifier
    binding_revision: Revision
    command_key: Identifier
    mirrored: bool = False

    def command(self) -> Envelope:
        return Envelope(**self.model_dump())


class StartTaskSchema(StrictModel):
    bot_id: Identifier
    project_id: Identifier
    brief: Annotated[str, Field(min_length=1, max_length=4096)]
    provider_binding: Identifier
    resource_key: Identifier | None = None
    budget: Annotated[int, Field(ge=1, le=100)] = 3

    def command(self) -> StartTask:
        return StartTask(**self.model_dump())


class AdmitRequest(StrictModel):
    envelope: EnvelopeSchema
    start: StartTaskSchema


class StateRequest(StrictModel):
    envelope: EnvelopeSchema
    expected_state_revision: Revision


class ReviewRequest(StateRequest):
    audience: Audience
    ttl_seconds: Annotated[int, Field(ge=1, le=300)] = 300


class PublishRequest(StrictModel):
    envelope: EnvelopeSchema
    expected_revision: Revision
    content: Annotated[str, Field(min_length=1, max_length=65536)]
    audience: Audience


class TaskResponse(StrictModel):
    task_id: str
    owner_id: str
    bot_id: str
    project_id: str
    brief: str
    provider_binding: str
    resource_key: str | None
    budget_remaining: int
    task_revision: int
    state_revision: int
    phase: Literal["queued", "active", "recovering", "stopping", "closed"]
    outcome: Literal["completed", "cancelled", "failed"] | None
    blockers: tuple[str, ...]
    attempt_id: str | None
    generation: int
    model_id: str | None
    result: str | None
    result_digest: str | None
    observation_sequence: int


class ReviewResponse(StrictModel):
    review_id: str
    task_id: str
    reviewer_id: str
    digest: str
    audience: tuple[str, ...]
    task_revision: int
    state_revision: int
    expires_at: datetime
    revision: int
    state: str


class PublicationResponse(StrictModel):
    publication_id: str
    task_id: str
    review_id: str
    digest: str
    audience: tuple[str, ...]
    content: str
    channel: str


class EventResponse(StrictModel):
    task_id: str
    kind: str
    state_revision: int
    data: dict
    cursor: int


class EventsResponse(StrictModel):
    task: TaskResponse
    events: list[EventResponse]
    cursor: int
    resync_required: bool


class ErrorResponse(StrictModel):
    code: str
