"""Authenticated relay for the user's independent, unprivileged VM terminal."""
import asyncio
import base64
from datetime import datetime
import hashlib
import math
import re
import time
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from radhouse.domain.tasks import Rejected
from radhouse.integrations.hermes import HermesGatewayError, HermesRunsClient

_UUID = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}")
OPERATIONS = frozenset({"open", "status", "output", "input", "resize", "close", "context-scrub"})
CONTEXT_BYTES = 8192


class HermesTerminalClient:
    def __init__(self, endpoint, bearer_token, *, transport=None):
        # Native polls wait up to 15s; writes can backpressure for 10s. Keep
        # acknowledgements connected and never retry an uncertain command.
        self._client = HermesRunsClient(endpoint, bearer_token, transport=transport,
            connect_timeout=2, read_timeout=20, request_deadline=25)

    def close(self):
        self._client.close()

    def call(self, operation, body):
        if operation not in OPERATIONS:
            raise ValueError("invalid_terminal_operation")
        value, _ = self._client._request("POST", f"v1/owner-terminal/{operation}",
            expected_status=200, body=body)
        return value


def _uuid(value):
    if type(value) is not str or not _UUID.fullmatch(value):
        raise ValueError("invalid_terminal_identity")
    return value


def _status(value):
    keys = {"state", "terminal_id", "generation", "attach_epoch", "next_cursor", "last_sequence", "last_outcome"}
    if type(value) is not dict or set(value) != keys or value["state"] not in {"open", "exited", "closed"}:
        raise ValueError("invalid_terminal_response")
    if value["terminal_id"] is None:
        if value["state"] != "closed" or value["generation"] is not None or value["attach_epoch"] != 0:
            raise ValueError("invalid_terminal_response")
    else:
        _uuid(value["terminal_id"])
        _uuid(value["generation"])
        if type(value["attach_epoch"]) is not int or value["attach_epoch"] < 1:
            raise ValueError("invalid_terminal_response")
    for name in ("next_cursor", "last_sequence"):
        if type(value[name]) is not int or not 0 <= value[name] <= 2**53 - 1:
            raise ValueError("invalid_terminal_response")
    if value["last_outcome"] not in {"none", "written", "uncertain"}:
        raise ValueError("invalid_terminal_response")
    return value


def _snapshot(value):
    keys = {"kind", "label", "terminal_id", "generation", "captured_at", "source", "text", "truncated"}
    if (type(value) is not dict or set(value) != keys or value["kind"] != "terminal_excerpt"
            or value["label"] != "Agent VM terminal" or value["source"] not in {"recent", "selection"}
            or type(value["text"]) is not str or len(value["text"].encode("utf-8")) > CONTEXT_BYTES
            or type(value["truncated"]) is not bool or type(value["captured_at"]) is not str):
        raise ValueError("invalid_terminal_context")
    _uuid(value["terminal_id"])
    _uuid(value["generation"])
    if datetime.fromisoformat(value["captured_at"]).tzinfo is None:
        raise ValueError("invalid_terminal_context")
    return value


class OwnerTerminalService:
    def __init__(self, client, *, owner_id, clock=time.time):
        self.client, self.owner_id, self.clock = client, owner_id, clock

    def binding(self, session, tab):
        if session.principal_id != self.owner_id:
            raise Rejected("owner_access_required", 403)
        try:
            _uuid(tab)
            if (type(session.token) is not str or not session.token
                    or type(session.binding_revision) is not int or session.binding_revision < 1
                    or type(session.conversation_id) is not str or not _ID.fullmatch(session.conversation_id)
                    or not isinstance(session.expires_at, datetime) or session.expires_at.tzinfo is None):
                raise ValueError
            expiry = session.expires_at.timestamp()
            if not math.isfinite(expiry) or expiry <= self.clock():
                raise Rejected("authentication_required", 401)
        except (ValueError, TypeError, OverflowError):
            raise Rejected("terminal_binding_unavailable", 409) from None
        return {"owner": {"principal_id": session.principal_id,
            "auth_session_digest": hashlib.sha256(session.token.encode()).hexdigest(),
            "tab_id": tab, "conversation_id": session.conversation_id,
            "binding_revision": session.binding_revision}, "auth_expires_at": expiry}

    def call(self, session, tab, operation, values=None):
        binding = self.binding(session, tab)
        if operation not in OPERATIONS:
            raise Rejected("terminal_invalid_request", 422)
        try:
            value = self.client.call(operation, {**(values or {}), **binding})
            if operation == "context-scrub":
                result = _snapshot(value)
                for name in ("terminal_id", "generation", "captured_at", "source", "truncated"):
                    if result[name] != values[name]:
                        raise ValueError("terminal_context_mismatch")
                return result
            if operation == "output":
                if type(value) is not dict or set(value) != {"state", "terminal_id", "generation", "attach_epoch",
                        "next_cursor", "last_sequence", "last_outcome", "data_b64", "truncated"}:
                    raise ValueError("invalid_terminal_output")
                _status({name: value[name] for name in value if name not in {"data_b64", "truncated"}})
                if (type(value["data_b64"]) is not str or len(value["data_b64"]) > 87_384
                        or type(value["truncated"]) is not bool):
                    raise ValueError("invalid_terminal_output")
                data = base64.b64decode(value["data_b64"], validate=True)
                if len(data) > 65_536 or value["next_cursor"] < values["cursor"]:
                    raise ValueError("invalid_terminal_output")
            else:
                _status(value)
            if operation not in {"open", "status"}:
                for name in ("terminal_id", "generation", "attach_epoch"):
                    if value[name] != values[name]:
                        raise ValueError("terminal_binding_mismatch")
            if operation == "input" and value["last_sequence"] != values["sequence"]:
                raise ValueError("terminal_ack_mismatch")
            return value
        except (HermesGatewayError, ValueError, TypeError, KeyError):
            raise Rejected("terminal_unavailable", 503) from None

    def scrub_context(self, session, tab, snapshot):
        try:
            _snapshot(snapshot)
        except (ValueError, TypeError, KeyError):
            raise Rejected("terminal_invalid_context", 422) from None
        return self.call(session, tab, "context-scrub",
            {name: snapshot[name] for name in ("terminal_id", "generation", "captured_at", "source", "text", "truncated")})


class TerminalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tab_id: str = Field(pattern=_UUID.pattern, min_length=36, max_length=36)


class OpenRequest(TerminalRequest):
    request_id: str = Field(pattern=_UUID.pattern, min_length=36, max_length=36)
    cols: int = Field(ge=2, le=2000)
    rows: int = Field(ge=2, le=1000)


class BoundRequest(TerminalRequest):
    terminal_id: str = Field(pattern=_UUID.pattern, min_length=36, max_length=36)
    generation: str = Field(pattern=_UUID.pattern, min_length=36, max_length=36)
    attach_epoch: int = Field(ge=1, le=2**53 - 1)


class OutputRequest(BoundRequest):
    cursor: int = Field(ge=0, le=2**53 - 1)
    wait_ms: int = Field(ge=0, le=15000)


class InputRequest(BoundRequest):
    sequence: int = Field(ge=1, le=2**53 - 1)
    data_b64: str = Field(min_length=1, max_length=87384)


class ResizeRequest(BoundRequest):
    cols: int = Field(ge=2, le=2000)
    rows: int = Field(ge=2, le=1000)


class ContextRequest(TerminalRequest):
    terminal_id: str = Field(pattern=_UUID.pattern, min_length=36, max_length=36)
    generation: str = Field(pattern=_UUID.pattern, min_length=36, max_length=36)
    captured_at: str = Field(max_length=64)
    source: Literal["selection", "recent"]
    text: str = Field(max_length=8192, repr=False)
    truncated: bool


def create_router(service, authenticate):
    """The supplied auth check enforces fresh owner auth and POST CSRF."""
    router = APIRouter()

    async def relay(request, body, operation):
        before = authenticate(request)
        service.binding(before, body.tab_id)
        value = await asyncio.to_thread(service.call, before, body.tab_id, operation,
            body.model_dump(exclude={"tab_id"}))
        after = authenticate(request)
        service.binding(after, body.tab_id)
        if any(getattr(before, name) != getattr(after, name)
                for name in ("token", "principal_id", "conversation_id", "binding_revision")):
            raise Rejected("terminal_binding_changed", 409)
        return JSONResponse(value, headers={"Cache-Control": "no-store"})

    @router.post("/chat/terminal/open")
    async def open_terminal(request: Request, body: OpenRequest):
        return await relay(request, body, "open")

    @router.post("/chat/terminal/status")
    async def status(request: Request, body: TerminalRequest):
        return await relay(request, body, "status")

    @router.post("/chat/terminal/output")
    async def output(request: Request, body: OutputRequest):
        return await relay(request, body, "output")

    @router.post("/chat/terminal/input")
    async def input_terminal(request: Request, body: InputRequest):
        return await relay(request, body, "input")

    @router.post("/chat/terminal/resize")
    async def resize(request: Request, body: ResizeRequest):
        return await relay(request, body, "resize")

    @router.post("/chat/terminal/close")
    async def close_terminal(request: Request, body: BoundRequest):
        return await relay(request, body, "close")

    @router.post("/chat/terminal/context-scrub")
    async def context(request: Request, body: ContextRequest):
        return await relay(request, body, "context-scrub")

    return router
