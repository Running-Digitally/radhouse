"""Two read-only callbacks, authorized by a saved turn rather than model claims."""
import base64
import asyncio
from dataclasses import asdict
import hashlib
import hmac
import json
import re
import time
from typing import Annotated

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from radhouse.domain.tasks import Rejected
from radhouse.integrations.hermes import HermesGatewayError
from .attachments import FILE_ID
from .document_access import DocumentAccess

IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$"
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
CATALOG_PAGE = 16


class DocumentCall(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    run_id: Annotated[str, Field(pattern=IDENTIFIER)]
    session_id: Annotated[str, Field(pattern=IDENTIFIER)]
    dispatch_key: Annotated[str, Field(pattern=IDENTIFIER)]
    file_id: Annotated[str, Field(pattern=FILE_ID.pattern)] | None = None
    query: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    locator: Annotated[str, Field(max_length=1024)] | None = None
    cursor: Annotated[str, Field(max_length=4096)] | None = None


class DocumentBridge:
    def __init__(self, store, hermes, *, owner_id, clock=time.time):
        self.store, self.hermes, self.owner_id, self.clock = store, hermes, owner_id, clock

    def grant(self, token):
        if type(token) is not str or TOKEN.fullmatch(token) is None:
            raise Rejected("document_access_denied", 403)
        grant = self.store.document_grant(token, self.clock())
        if grant["owner"] != self.owner_id or not {"document_read", "document_search"} <= set(grant["allowed_tools"]):
            raise Rejected("document_access_denied", 403)
        return grant

    def _authorize(self, token, call):
        grant = self.grant(token)
        if grant["session_id"] != call.session_id or grant["dispatch_key"] != call.dispatch_key or (
                grant["bound_run_id"] not in (None, call.run_id) or grant["run_id"] not in (None, call.run_id)):
            raise Rejected("document_access_denied", 403)
        try:
            run = self.hermes.status(call.run_id)
        except HermesGatewayError:
            raise Rejected("document_runtime_unavailable", 503) from None
        if (run.run_id != call.run_id or run.session_id != call.session_id
                or run.dispatch_key != call.dispatch_key or run.status not in {"queued", "running", "waiting_for_approval"}
                or run.allowed_tools is None or set(run.allowed_tools) != set(grant["allowed_tools"])):
            raise Rejected("document_access_denied", 403)
        self.store.bind_document_grant(token, call.run_id, call.session_id, call.dispatch_key, self.clock())
        return grant

    @staticmethod
    def _catalog_signature(token, value):
        return hmac.new(token.encode(), json.dumps(value, sort_keys=True, separators=(",", ":"),
            allow_nan=False).encode(), hashlib.sha256).hexdigest()

    def _catalog(self, token, grant, cursor):
        position = 0
        if cursor is not None:
            try:
                value = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
                if type(value) is not dict or set(value) != {"body", "signature"}:
                    raise ValueError()
                body, signature = value["body"], value["signature"]
                if (type(body) is not dict or set(body) != {"kind", "offset"} or body["kind"] != "catalog"
                        or type(body["offset"]) is not int or not 0 <= body["offset"] <= len(grant["files"])
                        or type(signature) is not str or re.fullmatch(r"[a-f0-9]{64}", signature) is None
                        or not hmac.compare_digest(signature, self._catalog_signature(token, body))):
                    raise ValueError()
                position = body["offset"]
            except (ValueError, TypeError, RecursionError):
                raise Rejected("document_cursor_invalid", 422) from None
        files = tuple(grant["files"])
        selected = files[position:position + CATALOG_PAGE]
        access = self._access(token, grant, selected)
        next_position = position + len(selected)
        next_cursor = None
        if next_position < len(files):
            body = {"kind": "catalog", "offset": next_position}
            next_cursor = base64.urlsafe_b64encode(json.dumps(
                {"body": body, "signature": self._catalog_signature(token, body)}, separators=(",", ":")).encode()).decode()
        return {"kind": "catalog", "files": access.catalog(), "next_cursor": next_cursor,
                "complete": next_cursor is None}

    def _access(self, token, grant, files=None):
        def resolve(owner, file_id):
            original = self.store.upload(owner, file_id)
            if original.sha256 != grant["files"][file_id]:
                raise Rejected("document_source_changed", 409)
            return original
        return DocumentAccess(resolve, owner=grant["owner"],
            file_ids=frozenset(grant["files"] if files is None else files), cursor_key=token.encode())

    def execute(self, token, call, operation):
        grant = self._authorize(token, call)
        if operation == "search":
            if call.file_id is None or call.query is None or call.locator is not None:
                raise Rejected("document_query_invalid", 422)
            result = {"kind": "passages", **asdict(self._access(token, grant).search(
                call.file_id, call.query, call.cursor))}
        elif operation == "read":
            if call.query is not None or call.file_id is None and call.locator is not None:
                raise Rejected("document_locator_invalid", 422)
            result = self._catalog(token, grant, call.cursor) if call.file_id is None else {
                "kind": "passages", **asdict(self._access(token, grant).read(call.file_id, call.locator, call.cursor))}
        else:
            raise Rejected("invalid_request", 422)
        # Cancellation/expiry during a parser read must not release a stale result.
        self._authorize(token, call)
        return result


def create_document_router(bridge):
    router = APIRouter()

    async def execute(request, operation):
        header = request.headers.get("authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        await asyncio.to_thread(bridge.grant, token)  # Deny before body or runtime probes.
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 16 * 1024:
                raise Rejected("invalid_request", 422)
            body.extend(chunk)
        try:
            call = DocumentCall.model_validate_json(body)
        except ValidationError:
            raise Rejected("invalid_request", 422) from None
        # The app's async loop remains available for callback/cancel observations.
        return await asyncio.to_thread(bridge.execute, token, call, operation)

    @router.post("/internal/documents/search")
    async def search(request: Request):
        return await execute(request, "search")

    @router.post("/internal/documents/read")
    async def read(request: Request):
        return await execute(request, "read")

    return router
