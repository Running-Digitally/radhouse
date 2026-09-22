"""Expiring navigation locators; possession never supplies authentication."""

import base64
import hashlib
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from coincurve import PublicKeyXOnly
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from radhouse.application.conversations import Conversations
from radhouse.channels.commands import Envelope
from radhouse.domain.tasks import Rejected

TTL = 15 * 60
DOMAIN = b"radhouse:authenticated-web-review:v1\x00"
Identifier = Annotated[str, Field(min_length=1, max_length=200)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class ReviewLocator(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1] = 1
    task_id: Annotated[str, Field(pattern=r"^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$")]
    digest: Digest
    project_id: Identifier
    link_id: Identifier
    binding_revision: Annotated[int, Field(ge=1)]
    agent_pubkey: Digest
    principal_id: Identifier
    issued_at: Annotated[int, Field(ge=0)]
    expires_at: Annotated[int, Field(ge=0)]

    def signing_digest(self):
        return hashlib.sha256(DOMAIN + self.model_dump_json().encode()).digest()


class ReviewLinks:
    def __init__(self, service, origin, candidates):
        parsed = urlsplit(origin)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise ValueError("invalid_review_origin")
        self.service, self.origin = service, origin.rstrip("/")
        self.candidates = {item.candidate.link_id: item for item in candidates}

    def _authorize(self, tx, link, task):
        from radhouse.channels.buzz_enrollment import verify_owner_attestation
        candidate = self.candidates.get(link.link_id) if link else None
        if candidate is None or not candidate.matches(link) or not candidate.candidate.active:
            raise Rejected("review_link_denied", 403)
        Conversations(self.service).authorize(tx, link)
        enrollment = tx.conversation_enrollment(link.link_id)
        if not enrollment or not enrollment.get("ready"):
            raise Rejected("review_link_denied", 403)
        verify_owner_attestation(enrollment.get("auth_tag"), link.owner_pubkey, link.agent_pubkey)
        if (task is None or task.outcome != "completed" or not task.result_digest
                or task.owner_id != link.principal_id or task.project_id != link.project_id
                or task.bot_id != link.bot_id):
            raise Rejected("review_link_denied", 403)
        return candidate

    def issue(self, tx, link, task):
        candidate = self._authorize(tx, link, task)
        now = int(self.service._now().timestamp())
        locator = ReviewLocator(task_id=task.task_id, digest=task.result_digest,
            project_id=link.project_id, link_id=link.link_id, binding_revision=link.binding_revision,
            agent_pubkey=link.agent_pubkey, principal_id=link.principal_id,
            issued_at=now, expires_at=now + TTL)
        body = base64.urlsafe_b64encode(locator.model_dump_json().encode()).decode().rstrip("=")
        return self.origin + "/app/#review=" + body + "." + candidate.relay.sign_review_locator(locator)

    def resolve(self, actor, token):
        # A normal authenticated session is sufficient for this navigation link.
        if actor.channel != "radhouse":
            raise Rejected("review_link_denied", 403)
        try:
            if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,3000}\.[a-f0-9]{128}", token):
                raise ValueError()
            body, signature = token.split(".")
            raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
            locator = ReviewLocator.model_validate_json(raw)
            # Canonical encoding rejects duplicate fields, alternate field order,
            # alternate JSON types and ambiguous base64 encodings.
            if base64.urlsafe_b64encode(locator.model_dump_json().encode()).decode().rstrip("=") != body:
                raise ValueError()
            now = int(self.service._now().timestamp())
            if (locator.principal_id != actor.principal_id or locator.issued_at > now
                    or locator.expires_at <= now or locator.expires_at - locator.issued_at != TTL):
                raise ValueError()
            if not PublicKeyXOnly(bytes.fromhex(locator.agent_pubkey)).verify(
                    bytes.fromhex(signature), locator.signing_digest()):
                raise ValueError()
        except (ValueError, TypeError, ValidationError):
            raise Rejected("review_link_denied", 403) from None
        with self.service.store.transaction() as tx:
            link, task = tx.conversation_link(locator.link_id), tx.task(locator.task_id)
            self._authorize(tx, link, task)
            if (locator.agent_pubkey != link.agent_pubkey or locator.binding_revision != link.binding_revision
                    or locator.project_id != task.project_id or locator.digest != task.result_digest):
                raise Rejected("review_link_denied", 403)
            bindings = [b for b in tx.bindings(actor.channel, actor.subject, actor.principal_id)
                        if b.active and b.project_id == task.project_id]
            if len(bindings) != 1:
                raise Rejected("binding_denied", 403)
            binding = bindings[0]
            envelope = Envelope(actor.channel, "read", binding.conversation_id, binding.revision, "read")
            self.service._authorize(tx, actor, task, envelope)
            return {"task_id": task.task_id, "project_id": task.project_id,
                    "conversation_id": binding.conversation_id, "binding_revision": binding.revision}
