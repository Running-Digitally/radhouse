"""Task state is independent of runtime sessions and channel deliveries."""
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal
import base64
import binascii
import hashlib
import re

Phase = Literal["queued", "active", "recovering", "stopping", "closed"]
Outcome = Literal["completed", "cancelled", "failed"]
TitleSource = Literal["brief", "agent", "owner"]
TITLE_LIMIT = 100


class Rejected(Exception):
    """A bounded, public error code; never a vendor payload or credential."""

    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True)
class TaskTitle:
    task_id: str
    title: str
    source: TitleSource
    revision: int


def normalize_task_title(value: str) -> str:
    """Return one compact plain-text title without changing task identity."""
    if type(value) is not str:
        raise Rejected("invalid_task_title", 422)
    title = re.sub(r"\s+", " ", value).strip()
    title = re.sub(r"^new task:\s*", "", title, flags=re.I)
    if not title:
        raise Rejected("invalid_task_title", 422)
    if len(title) > TITLE_LIMIT:
        shortened = title[:TITLE_LIMIT + 1].rsplit(" ", 1)[0]
        title = shortened if len(shortened) >= TITLE_LIMIT // 2 else title[:TITLE_LIMIT]
        title = title.rstrip(" ,.;:-") + "…"
        if len(title) > TITLE_LIMIT:
            title = title[:TITLE_LIMIT - 1].rstrip() + "…"
    return title


def initial_task_title(brief: str) -> str:
    first = next((line.strip() for line in brief.splitlines() if line.strip()), brief)
    sentence = re.split(r"(?<=[.!?])\s+", first, maxsplit=1)[0]
    return normalize_task_title(sentence)


def agent_task_title(result: str) -> str | None:
    """Use a heading the agent already produced; never request a title-only turn."""
    for line in result.splitlines():
        match = re.fullmatch(r"\s{0,3}#{1,6}\s+(.+?)\s*#*\s*", line)
        if match:
            value = re.sub(r"[`*_~]", "", match.group(1))
            try:
                return normalize_task_title(value)
            except Rejected:
                return None
    return None


@dataclass(frozen=True)
class InputFile:
    name: str
    content: str
    media_type: str = "text/plain"
    encoding: Literal["utf-8", "base64"] = "utf-8"
    sha256: str | None = None

    def bytes(self) -> bytes:
        if self.encoding == "utf-8":
            return self.content.encode("utf-8")
        if self.encoding == "base64":
            try:
                return base64.b64decode(self.content, validate=True)
            except (binascii.Error, ValueError):
                raise Rejected("invalid_input_files", 422) from None
        raise Rejected("invalid_input_files", 422)

    @property
    def is_image(self) -> bool:
        return self.media_type in {"image/png", "image/jpeg", "image/webp"}


def validate_input_files(files: tuple[InputFile, ...], *, code: str = "invalid_input_files") -> None:
    """Validate the shared durable attachment shape used by API and Buzz."""
    try:
        decoded = tuple((file, file.bytes()) for file in files)
    except (AttributeError, Rejected):
        raise Rejected(code, 422) from None
    if (type(files) is not tuple or len(files) > 4
            or sum(len(data) for file, data in decoded if not file.is_image) > 65536
            or sum(len(data) for file, data in decoded if file.is_image) > 8 * 1024 * 1024
            or any(file.is_image and len(data) > 4 * 1024 * 1024 for file, data in decoded)
            or any((file.is_image and (
                        file.encoding != "base64"
                        or file.sha256 != hashlib.sha256(data).hexdigest()
                    )) or (not file.is_image and (
                        file.encoding != "utf-8"
                        or file.media_type.startswith("image/")
                        or file.sha256 is not None
                    )) for file, data in decoded)
            or any(not file.name or len(file.name) > 200
                   or any(character in file.name for character in "/\\\x00\n\r")
                   for file in files)):
        raise Rejected(code, 422)


@dataclass(frozen=True)
class StartTask:
    bot_id: str
    project_id: str
    brief: str
    provider_binding: str
    resource_key: str | None = None
    budget: int = 3
    files: tuple[InputFile, ...] = ()
    follows_task_id: str | None = None
    disable_tools: bool = False
    allowed_tools: tuple[str, ...] = ()


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
    files: tuple[InputFile, ...] = ()
    follows_task_id: str | None = None
    previous_result: str | None = None
    guidance: tuple[dict, ...] = ()
    permission_request: dict | None = None
    disable_tools: bool = False
    allowed_tools: tuple[str, ...] = ()

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
    guidance_receipts: bool = False


@dataclass(frozen=True)
class RuntimeDispatch:
    run_id: str
    session_id: str
    provider_binding: str
    runtime_revision: str
    submitted_at: datetime
    retention_until: datetime


@dataclass(frozen=True)
class RuntimeGuidanceReceipt:
    run_id: str
    control_id: str
    input_sha256: str
    accepted: bool
    state: Literal["accepted", "applied", "too_late", "not_applied", "unknown"]
    revision: int
    reason: str | None = None
    checkpoint_id: str | None = None
    api_request_id: str | None = None


@dataclass(frozen=True)
class RuntimeActivity:
    """One sanitized, pollable runtime activity snapshot."""

    run_id: str
    event: str
    label: str
    occurred_at: int


@dataclass(frozen=True)
class RuntimeResult:
    state: Literal["running", "completed", "failed", "cancelled", "unknown"]
    content: str | None = None
    permission_request: dict | None = None
    guidance_receipts: tuple[RuntimeGuidanceReceipt, ...] | None = None
    guidance_terminal: bool = False
    activity: RuntimeActivity | None = None


def runtime_input(task: Task) -> str:
    """Immutable input snapshot, including only explicitly selected context."""
    parts = [task.brief]
    if task.previous_result is not None:
        parts.append("Previous task result (reference material):\n" + task.previous_result)
    for file in task.files:
        if file.is_image:
            parts.append(
                "Attached screenshot: " + file.name + " (" + file.media_type + ", sha256 "
                + (file.sha256 or "not supplied") + "). Inspect the attached pixels directly."
            )
        else:
            parts.append("Attached reference file: " + file.name + "\n" + file.content)
    return "\n\n".join(parts)


def runtime_images(task: Task) -> tuple[InputFile, ...]:
    """Image inputs kept separate from the text prompt until the provider request."""
    return tuple(file for file in task.files if file.is_image)


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
