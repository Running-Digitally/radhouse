"""One conversation, one pending reply, no work or fleet orchestration."""
import time

from radhouse.domain.tasks import Rejected
from radhouse.integrations.hermes import HermesGatewayError
from .store import TERMINAL


class ChatService:
    def __init__(self, store, hermes, *, owner_id: str, clock=time.time):
        if not owner_id or len(owner_id) > 200:
            raise ValueError("invalid_chat_owner")
        self.store, self.hermes, self.owner_id, self.clock = store, hermes, owner_id, clock

    def authorize(self, session):
        if session.principal_id != self.owner_id:
            raise Rejected("owner_access_required", 403)
        return self.owner_id

    def send(self, owner, request_id, text):
        # Even trusted callers cannot choose another owner or runtime session.
        if owner != self.owner_id:
            raise Rejected("owner_access_required", 403)
        if not text.strip():
            raise Rejected("empty_message", 422)
        turn = self.store.find(owner, request_id)
        if turn:
            if turn["text"] != text:
                raise Rejected("message_conflict", 409)
            if turn["run_id"] or turn["status"] in TERMINAL:
                return self.store.history(owner)
        try:
            capabilities = self.hermes.capabilities()
            if not capabilities.disable_tools:
                raise Rejected("chat_capability_unavailable", 503)
            now = self.clock()
            if turn is None:
                # Leave margin for the transport deadline before Hermes expiry.
                if capabilities.idempotency_retention_seconds <= 60:
                    raise Rejected("chat_capability_unavailable", 503)
                turn = self.store.reserve(owner, request_id, text, now, capabilities.idempotency_retention_seconds - 60)
            retry_until = min(turn["retry_until"], turn["created_at"] + capabilities.idempotency_retention_seconds - 60)
            if now >= retry_until:
                self.store.note_error(turn, "reply_recovery_required")
                raise Rejected("reply_recovery_required", 409)
            dispatch = self.hermes.start_or_attach(input_text=turn["text"],
                session_id=self.store.session_id(owner), dispatch_key=turn["dispatch_key"], disable_tools=True)
            if dispatch.session_id != self.store.session_id(owner):
                raise Rejected("runtime_identity_changed", 503)
            self.store.attach(turn, dispatch.run_id, "queued" if dispatch.status in TERMINAL else dispatch.status)
        except HermesGatewayError:
            if turn:
                self.store.note_error(turn, "reply_dispatch_uncertain")
            raise Rejected("assistant_unavailable", 503) from None
        return self.store.history(owner)

    def poll(self, owner):
        if owner != self.owner_id:
            raise Rejected("owner_access_required", 403)
        turn = self.store.pending(owner)
        if turn and turn["run_id"]:
            try:
                run = self.hermes.status(turn["run_id"])
                if run.status == "completed":
                    if run.output and run.output.strip():
                        self.store.observe(turn, "completed", output=run.output)
                    else:
                        self.store.observe(turn, "failed", error="empty_reply")
                elif run.status in TERMINAL:
                    self.store.observe(turn, run.status, error="reply_" + run.status)
                elif run.status == "waiting_for_approval":
                    self.store.note_error(turn, "unexpected_runtime_approval")
                else:
                    self.store.observe(turn, run.status)
            except HermesGatewayError:
                self.store.note_error(turn, "reply_status_unavailable")
                raise Rejected("assistant_unavailable", 503) from None
        return self.store.history(owner)
