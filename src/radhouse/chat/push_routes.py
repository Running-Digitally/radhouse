"""Opt-in device endpoints and completion observer; mounted only when configured."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import logging

from fastapi import Request

from radhouse.domain.tasks import Rejected
from .push import PushBinding, installation_id


def _binding(session):
    if session.expires_at is None:
        raise Rejected("authentication_required", 401)
    return PushBinding(session.principal_id, session.conversation_id, session.binding_revision,
                       hashlib.sha256(session.token.encode()).hexdigest(), session.expires_at.timestamp())


async def _registration_body(request):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 8192:
            raise Rejected("push_registration_too_large", 413)
        data.extend(chunk)
    try:
        value = json.loads(data)
    except ValueError:
        raise Rejected("invalid_push_registration", 422) from None
    if (type(value) is not dict or not {"platform", "token"} <= set(value)
            or set(value) - {"platform", "token", "commitments"}
            or type(value.get("commitments", False)) is not bool):
        raise Rejected("invalid_push_registration", 422)
    return value


def install_push(app, auth, service, outbox, sender):
    def session(request):
        current = auth.session(request)
        service.authorize(current)
        return current

    def authorize(binding):
        return auth.notification_session_active(binding.session_hash, binding.principal_id,
                                                binding.conversation_id, binding.binding_revision)

    def register(identifier, current, body):
        if body.get("commitments") and getattr(app.state, "commitment_review", None) is None:
            raise Rejected("commitment_notifications_unavailable", 409)
        binding = _binding(current)
        if not authorize(binding):
            raise Rejected("authentication_required", 401)
        with service.store.connection() as db:
            latest = db.execute("SELECT coalesce(max(seq),0) FROM turns WHERE owner=?",
                                (current.principal_id,)).fetchone()[0]
        outbox.register(identifier, binding, body["platform"], body["token"], latest_seq=latest,
                        commitments=body.get("commitments", False))

    @app.get("/chat/push/status")
    def push_status(request: Request):
        session(request)
        return {"available": True, **({"commitments": True} if getattr(app.state, "commitment_review", None) is not None else {})}

    @app.put("/chat/push/devices/{identifier}")
    async def push_register(identifier: str, request: Request):
        installation_id(identifier)
        current = await asyncio.to_thread(session, request)
        body = await _registration_body(request)
        await asyncio.to_thread(register, identifier, current, body)
        return {"registered": True}

    @app.delete("/chat/push/devices/{identifier}")
    def push_unregister(identifier: str, request: Request):
        current = session(request)
        outbox.unregister(identifier, current.principal_id, _binding(current).session_hash)
        return {"registered": False}

    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        stop = asyncio.Event()

        def dispatch():
            outbox.reconcile(service.store, service.owner_id)
            review = getattr(app.state, "commitment_review", None)
            if review is not None:
                outbox.enqueue_commitments(service.owner_id, review.notification_items())
            for _ in range(10):
                if stop.is_set() or not outbox.dispatch_one(authorize, sender,
                        commitment_decision=review.notification_decision if review else None):
                    break

        async def observe():
            while not stop.is_set():
                try:
                    await asyncio.to_thread(dispatch)
                except Exception:
                    logging.getLogger(__name__).warning("Push delivery observation unavailable")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=2)
                except TimeoutError:
                    pass

        async with previous(application):
            observer = asyncio.create_task(observe())
            try:
                yield
            finally:
                stop.set()
                await observer

    app.router.lifespan_context = lifespan
