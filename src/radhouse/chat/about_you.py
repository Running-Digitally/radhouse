"""The authenticated owner can inspect the assistant's built-in saved notes."""
import asyncio
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from radhouse.domain.tasks import Rejected
from radhouse.integrations.hermes import HermesGatewayError

SCHEMA = "radhouse.saved-memory.v1"
SOURCES = (("user", "USER.md"), ("memory", "MEMORY.md"))
SOURCE_KEYS = {"target", "source_filename", "state", "entries", "file_modified_at", "complete"}
STATES = {"available", "empty", "missing", "unreadable", "too_large"}


def _timestamp(value):
    if type(value) is not str or len(value) > 64:
        raise ValueError("invalid_timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("invalid_timestamp")
    return value


def _snapshot(value):
    if (type(value) is not dict or set(value) != {"schema", "checked_at", "sources"}
            or value["schema"] != SCHEMA or type(value["sources"]) is not list
            or len(value["sources"]) != len(SOURCES)):
        raise ValueError("invalid_memory_snapshot")
    _timestamp(value["checked_at"])
    for source, (target, filename) in zip(value["sources"], SOURCES):
        if (type(source) is not dict or set(source) != SOURCE_KEYS or source["target"] != target
                or source["source_filename"] != filename or source["state"] not in STATES
                or type(source["complete"]) is not bool):
            raise ValueError("invalid_memory_source")
        if source["file_modified_at"] is not None:
            _timestamp(source["file_modified_at"])
        state, entries = source["state"], source["entries"]
        if state in {"unreadable", "too_large"}:
            if entries is not None or source["complete"]:
                raise ValueError("invalid_memory_source")
        elif (not source["complete"] or type(entries) is not list
                or any(type(entry) is not str or not entry.strip() for entry in entries)
                or (state == "available") != bool(entries)):
            raise ValueError("invalid_memory_source")
    return value


class AboutYouService:
    def __init__(self, client, *, owner_id):
        self.client, self.owner_id = client, owner_id

    def authorize(self, session):
        if session.principal_id != self.owner_id:
            raise Rejected("owner_access_required", 403)

    def snapshot(self, session):
        self.authorize(session)
        try:
            payload, _ = self.client._request("GET", "v1/radhouse/memory", expected_status=200)
            return _snapshot(payload)
        except (HermesGatewayError, ValueError, TypeError, KeyError):
            raise Rejected("memory_unavailable", 503) from None


def create_router(service, authenticate):
    """authenticate(request) returns a freshly checked owner Session each time."""
    router = APIRouter()

    @router.get("/chat/about-you")
    async def about_you(request: Request):
        before = authenticate(request)
        service.authorize(before)
        value = await asyncio.to_thread(service.snapshot, before)
        after = authenticate(request)
        service.authorize(after)
        fields = ("principal_id", "conversation_id", "binding_revision", "token")
        if any(getattr(before, field) != getattr(after, field) for field in fields):
            raise Rejected("memory_binding_changed", 409)
        return JSONResponse(value, headers={"Cache-Control": "no-store"})

    return router
