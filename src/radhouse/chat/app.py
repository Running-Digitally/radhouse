"""Standalone authenticated web chat, independent of platform composition."""
from pathlib import Path
from contextlib import asynccontextmanager
import asyncio
import logging
import sqlite3
import re
from urllib.parse import quote
from typing import Annotated

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from radhouse.domain.tasks import Rejected
from .attachments import MAX_FILES, MAX_FILE, MAX_REQUEST, decode_uploads

STATIC = Path(__file__).with_name("static")


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: Annotated[str, Field(min_length=3, max_length=64)]
    password: Annotated[str, Field(min_length=1, max_length=1024)]
    totp_code: Annotated[str, Field(pattern=r"^[0-9]{6}$")]
    remember_browser: bool = False


class Upload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: Annotated[str, Field(min_length=1, max_length=200)]
    content: Annotated[str, Field(min_length=1, max_length=4 * ((MAX_FILE + 2) // 3))]


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: Annotated[str, Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")]
    text: Annotated[str, Field(max_length=16000)]
    attachments: Annotated[list[Upload], Field(max_length=MAX_FILES)] = Field(default_factory=list)


class BoundedBody:
    """Bound streamed bodies before JSON parsing, including chunked requests."""
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect": return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_REQUEST:
                return await JSONResponse({"error":"attachments_too_large"},status_code=413)(scope, receive, send)
            body.extend(chunk)
            if not message.get("more_body", False): break
        delivered = False
        async def bounded_receive():
            nonlocal delivered
            if delivered: return await receive()
            delivered = True
            return {"type":"http.request", "body":bytes(body), "more_body":False}
        await self.app(scope, bounded_receive, send)


def create_app(auth, service):
    @asynccontextmanager
    async def lifespan(_app):
        stop = asyncio.Event()

        async def observe_reply():
            # Save completion even when the browser is closed. Never dispatch.
            while not stop.is_set():
                try:
                    await asyncio.to_thread(service.poll, service.owner_id)
                except (Rejected, sqlite3.Error):
                    logging.getLogger(__name__).warning("Pending reply observation unavailable")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=2)
                except TimeoutError:
                    pass

        observer = asyncio.create_task(observe_reply())
        try:
            yield
        finally:
            stop.set()
            await observer

    app = FastAPI(title="Radhouse", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    app.add_middleware(BoundedBody)

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    @app.exception_handler(Rejected)
    async def rejected(_request, exc):
        return JSONResponse({"error": exc.code}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(_request, _exc):
        # Framework validation errors otherwise echo submitted credentials/text.
        return JSONResponse({"error": "invalid_request"}, status_code=422)

    @app.exception_handler(sqlite3.Error)
    async def storage_unavailable(_request, _exc):
        return JSONResponse({"error": "conversation_unavailable"}, status_code=503)

    def session_payload(session):
        service.authorize(session)
        return {"username": session.username, "csrf_token": session.csrf_token}

    def owner(request):
        return service.authorize(auth.session(request))

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/chat.js")
    def javascript():
        return FileResponse(STATIC / "chat.js", media_type="text/javascript")

    @app.get("/chat.css")
    def stylesheet():
        return FileResponse(STATIC / "chat.css", media_type="text/css")

    @app.get("/icons/{name}.svg")
    def file_icon(name: str):
        if name not in {"pdf", "word", "excel", "powerpoint"}:
            raise Rejected("icon_not_found", 404)
        return FileResponse(STATIC / "icons" / (name + ".svg"), media_type="image/svg+xml")

    @app.post("/auth/login")
    def login(body: Login, request: Request, response: Response):
        auth.verify_origin(request)
        session = auth.login(body.username, body.password, body.totp_code,
                             request.client.host if request.client else "unknown",
                             remember_browser=body.remember_browser)
        payload = session_payload(session)
        response.set_cookie(auth.cookie_name, session.token,
            max_age=30 * 86400 if body.remember_browser else 12 * 3600,
            secure=auth.secure_cookie, httponly=True, samesite="strict", path="/")
        return payload

    @app.get("/auth/session")
    def current_session(request: Request):
        return session_payload(auth.refresh(request))

    @app.post("/auth/logout", status_code=204)
    def logout(request: Request, response: Response):
        auth.revoke(request)
        response.delete_cookie(auth.cookie_name, secure=auth.secure_cookie,
                               httponly=True, samesite="strict", path="/")

    @app.get("/chat/history")
    def history(request: Request, before: Annotated[int | None, Field(gt=0)] = None):
        return service.store.history(owner(request), before)

    @app.post("/chat/messages")
    def send(body: Message, request: Request):
        principal = owner(request)
        return service.send(principal, body.request_id, body.text, decode_uploads([a.model_dump() for a in body.attachments]))

    @app.post("/chat/messages/{request_id}/retry")
    def retry(request_id: str, request: Request):
        return service.retry(owner(request), request_id)

    @app.get("/chat/messages/{request_id}/attachments/{position}")
    def attachment(request_id: str, position: Annotated[int, Field(ge=0,lt=MAX_FILES)], request: Request, download: bool = False):
        attachment = service.store.attachment(owner(request), request_id, position)
        disposition = "inline" if not download and attachment.kind in {"image","audio"} else "attachment"
        headers = {"Content-Disposition":disposition + "; filename*=UTF-8''" + quote(attachment.name,safe=""), "Accept-Ranges":"bytes"}
        data = attachment.data
        range_header = request.headers.get("range")
        if range_header:
            match = re.fullmatch(r"bytes=(\d{0,20})-(\d{0,20})", range_header)
            if not match or not any(match.groups()):
                return Response(status_code=416,headers={"Content-Range":f"bytes */{len(data)}"})
            first,last = match.groups()
            start = int(first) if first else max(0,len(data)-int(last))
            end = min(int(last),len(data)-1) if first and last else len(data)-1
            if start > end or start >= len(data):
                return Response(status_code=416,headers={"Content-Range":f"bytes */{len(data)}"})
            headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
            return Response(data[start:end+1],status_code=206,media_type=attachment.media_type,headers=headers)
        return Response(data,media_type=attachment.media_type,headers=headers)

    @app.get("/chat/reply")
    def reply(request: Request):
        return service.poll(owner(request))

    @app.get("/healthz")
    def health():
        auth.health()
        with service.store.connection() as db:
            db.execute("SELECT seq FROM turns LIMIT 1").fetchone()
        return {"status": "ready", "scope": "web"}

    return app
