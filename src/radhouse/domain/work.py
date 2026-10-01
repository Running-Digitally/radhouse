"""Requested outcomes are distinct from agent runs. Version one delivers text artifacts."""
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Annotated, Literal
import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError


WorkState = Literal['queued', 'active', 'waiting', 'paused', 'stopping', 'completed', 'failed', 'cancelled']
WorkCommandKind = Literal['pause', 'resume', 'cancel', 'guidance']


@dataclass(frozen=True)
class WorkCommand:
    kind: WorkCommandKind
    expected_state_revision: int
    scope_revision: int
    text: str | None = None


@dataclass(frozen=True)
class WorkCommandReceipt:
    principal_id: str
    command_key: str
    work_id: str
    kind: WorkCommandKind
    scope_revision: int
    accepted_state_revision: int
    task_state_revision: int
    created_at: datetime
    application_state: Literal['accepted', 'applied', 'not_applied', 'unknown'] = 'accepted'


@dataclass(frozen=True)
class WorkBlocker:
    code: str
    resolver: Literal['automatic', 'owner', 'administrator']


@dataclass(frozen=True)
class WorkItem:
    work_id: str
    owner_id: str
    project_id: str
    accountable_bot_id: str
    brief: str
    task_id: str
    created_at: datetime
    updated_at: datetime
    workflow_version: str = 'artifact-v1'
    acceptance: str = 'artifact-present-v1'
    scope_revision: int = 1
    state_revision: int = 1
    state: WorkState = 'queued'
    blockers: tuple[WorkBlocker, ...] = ()
    artifact_id: str | None = None
    verification_id: str | None = None

    def evolve(self, now: datetime, **changes):
        return replace(self, state_revision=self.state_revision + 1, updated_at=now, **changes)


@dataclass(frozen=True)
class ArtifactManifest:
    artifact_id: str
    work_id: str
    scope_revision: int
    task_id: str
    attempt_id: str
    name: str
    media_type: str
    sha256: str
    size_bytes: int
    created_at: datetime


@dataclass(frozen=True)
class VerificationReceipt:
    verification_id: str
    work_id: str
    scope_revision: int
    task_id: str
    result_digest: str
    artifact_id: str | None
    verifier: str
    result: Literal['passed', 'failed', 'incomplete']
    reason_code: str | None
    created_at: datetime


class TextArtifact(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: Annotated[str, Field(min_length=1, max_length=120, pattern=r'^[^/\\\x00-\x1f]+$')]
    media_type: Literal['text/markdown', 'text/plain']
    content: Annotated[str, Field(min_length=1, max_length=48000)]


class StepResultV1(BaseModel):
    """Untrusted runtime claim, parsed strictly before application verification."""
    model_config = ConfigDict(extra='forbid', strict=True)
    protocol: Literal['work-result-v1']
    work_id: str
    scope_revision: Annotated[int, Field(ge=1)]
    step_key: Literal['deliver-artifact']
    outcome: Literal['succeeded', 'incomplete', 'blocked', 'failed', 'cancelled']
    summary: Annotated[str, Field(min_length=1, max_length=500)]
    artifact: TextArtifact | None
    reason_code: Literal['dependency_unavailable', 'acceptance_unmet', 'budget_exhausted'] | None
    checkpoint: Annotated[str, Field(max_length=200)] | None


def parse_result(content: str, work: WorkItem) -> StepResultV1 | None:
    try:
        def unique_fields(pairs):
            value = {}
            for key, part in pairs:
                if key in value:
                    raise ValueError('duplicate_result_field')
                value[key] = part
            return value
        result = StepResultV1.model_validate(json.loads(content, object_pairs_hook=unique_fields))
    except (ValidationError, ValueError):
        return None
    if (result.work_id != work.work_id or result.scope_revision != work.scope_revision
            or not result.summary.strip()
            or result.outcome != 'succeeded' and result.reason_code is None
            or result.outcome == 'succeeded' and result.reason_code is not None
            or result.artifact is not None and not result.artifact.content.strip()):
        return None
    return result


def content_digest(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def runtime_contract(work_id: str) -> str:
    return ('Application output contract: deliver a text artifact for the request. '
            'Return exactly one JSON object, without a code fence. Report incomplete or blocked '
            'when the request cannot be fulfilled; a completed run is not proof of delivery. '
            'Do not claim external merge/deployment verification. Required fields: '
            f'protocol="work-result-v1", work_id="{work_id}", scope_revision=1, '
            'step_key="deliver-artifact", outcome="succeeded|incomplete|blocked|failed|cancelled", '
            'summary (nonempty string), artifact (null or {name, media_type: text/markdown or text/plain, '
            'content}), reason_code (null for succeeded, otherwise dependency_unavailable, '
            'acceptance_unmet or budget_exhausted), checkpoint (string or null). '
            'Success requires a nonempty usable artifact, not just a status message. '
            'This contract does not grant permissions or authorize external actions.')
