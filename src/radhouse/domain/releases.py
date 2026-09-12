"""Review decisions bind immutable bytes and a specific audience."""
from dataclasses import dataclass
from datetime import datetime
import hashlib
from .tasks import Rejected


def digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Review:
    review_id: str
    task_id: str
    reviewer_id: str
    digest: str
    audience: tuple[str, ...]
    task_revision: int
    state_revision: int
    expires_at: datetime
    revision: int = 1
    state: str = "pending"


@dataclass(frozen=True)
class Publication:
    publication_id: str
    task_id: str
    review_id: str
    digest: str
    audience: tuple[str, ...]
    content: str
    channel: str


def validate_review(review: Review, content: str, audience: tuple[str, ...], revision: int, now: datetime) -> None:
    if review.state != "pending" or review.revision != revision:
        raise Rejected("review_conflict")
    if review.expires_at <= now:
        raise Rejected("review_expired")
    if digest(content) != review.digest or tuple(sorted(set(audience))) != review.audience:
        raise Rejected("review_scope_changed")
