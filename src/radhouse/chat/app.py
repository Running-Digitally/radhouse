"""Standalone authenticated web chat, independent of platform composition."""
from pathlib import Path
from contextlib import asynccontextmanager
import asyncio
import logging
import sqlite3
from typing import Annotated

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from radhouse.domain.tasks import Rejected

STATIC = Path(__file__).with_name("static")


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: Annotated[str, Field(min_length=3, max_length=64)]
    password: Annotated[str, Field(min_length=1, max_length=1024)]
    totp_code: Annotated[str, Field(pattern=r"^[0-9]{6}$")]
    remember_browser: bool = False


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: Annotated[str, Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")]
    text: Annotated[str, Field(min_length=1, max_length=16000)]


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

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
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
        return service.send(owner(request), body.request_id, body.text)

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
