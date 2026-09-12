"""Current permissions are evaluated independently of a channel's input."""
from dataclasses import dataclass
from datetime import datetime
from .tasks import Rejected, Task


@dataclass(frozen=True)
class AuthContext:
    principal_id: str
    channel: str
    subject: str
    assurance_until: datetime | None = None


@dataclass(frozen=True)
class Access:
    principal_id: str
    role: str
    bots: frozenset[str]
    projects: frozenset[str]
    active: bool = True


@dataclass(frozen=True)
class Binding:
    channel: str
    subject: str
    conversation_id: str
    principal_id: str
    project_id: str
    revision: int
    active: bool = True


@dataclass(frozen=True)
class BotProfile:
    bot_id: str
    display_name: str
    role_name: str
    provider_binding: str
    state: str = "ready"


def require_access(access: Access | None, bot_id: str, project_id: str, *, write: bool) -> None:
    if access is None or not access.active or bot_id not in access.bots or project_id not in access.projects:
        raise Rejected("access_denied", 403)
    if write and access.role not in {"admin", "operator"}:
        raise Rejected("write_denied", 403)


def require_assurance(actor: AuthContext, now: datetime) -> None:
    if actor.assurance_until is None or actor.assurance_until <= now:
        raise Rejected("fresh_assurance_required", 403)
