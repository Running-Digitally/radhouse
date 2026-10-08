"""Standalone authenticated web chat, independent of platform composition."""
from pathlib import Path
from contextlib import asynccontextmanager
import asyncio
import logging
import sqlite3
import re
import os
import hashlib
from urllib.parse import quote
from typing import Annotated

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from radhouse.domain.tasks import Rejected
from .attachments import FILE_ID, classify


JAVASCRIPT_MEDIA_TYPE = 'text/javascript'

STATIC = Path(__file__).with_name("static")


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: Annotated[str, Field(min_length=3, max_length=64)]
    password: Annotated[str, Field(min_length=1, max_length=1024)]
    totp_code: Annotated[str, Field(pattern=r"^[0-9]{6}$")]
    remember_browser: bool = False


class BrowserContextBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    generation: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")]
    revision: Annotated[int, Field(gt=0)]
    lease_id: Annotated[str | None, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")] = None


class InferenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: Annotated[str | None, Field(min_length=1, max_length=512)] = None
    thinking: Annotated[str, Field(min_length=1, max_length=32)] = "default"


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: Annotated[str, Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")]
    text: Annotated[str, Field(max_length=16000)]
    attachments: list[Annotated[str, Field(pattern=FILE_ID.pattern)]] = Field(default_factory=list)
    browser_context: BrowserContextBody | None = None
    use_previous_browser: bool = False
    inference: InferenceSelection | None = None
    terminal_context: dict | None = None


def _recheck_browser_binding(auth, service, browser, request, before, tab):
    """Discard stale authentication after native waits, before fresh dispatch."""
    after = auth.session(request)
    service.authorize(after)
    browser.binding(after, tab)
    names = ("principal_id", "conversation_id", "binding_revision", "token")
    if any(getattr(before, name) != getattr(after, name) for name in names):
        raise Rejected("browser_binding_changed", 409)


def create_app(auth, service, *, admin=None, documents=None, browser=None, about_you=None,
               owner_terminal=None, inference=None):
    lifespan = _reply_lifespan(service)
    app = FastAPI(title="Radhouse", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    _install_response_handlers(app)
    def session_payload(session):
        service.authorize(session)
        payload = {"username": session.username, "csrf_token": session.csrf_token,
            "features": {"documents": getattr(service, "document_access", False) is True,
                         "browser": getattr(service, "browser_enabled", False) is True,
                         "browser_control": getattr(browser, "control_enabled", False) is True,
                         "about_you": about_you is not None,
                         "terminal": owner_terminal is not None,
                         "inference": inference is not None}}
        if admin is not None:
            try:
                can_read = auth.management_role(session) in {"admin", "operator"}
            except Rejected:
                can_read = False  # Management availability must not block chat.
            payload["management"] = {"read": can_read, "write": False}
        return payload

    def owner(request):
        return service.authorize(auth.session(request))

    def authenticated(request):
        session = auth.session(request)
        service.authorize(session)
        return session

    if about_you is not None:
        from .about_you import create_router
        app.include_router(create_router(about_you, authenticated))
    if owner_terminal is not None:
        from .owner_terminal import create_router
        app.include_router(create_router(owner_terminal, authenticated))
    if inference is not None:
        @app.get("/chat/inference")
        def inference_options(request: Request, refresh: bool = False):
            before = authenticated(request)
            payload = inference.options(refresh=refresh)
            after = authenticated(request)
            if (before.principal_id, before.conversation_id, before.binding_revision, before.token) != (
                    after.principal_id, after.conversation_id, after.binding_revision, after.token):
                raise Rejected("identity_binding_denied", 403)
            return payload

    if documents is not None:
        from .document_bridge import create_document_router
        app.include_router(create_document_router(documents))

    if admin is not None:
        from .admin import create_admin_router

        def management_session(request):
            session = auth.session(request)
            service.authorize(session)
            if auth.management_role(session) not in {"admin", "operator"}:
                raise Rejected("management_access_required", 403)
            return session

        app.include_router(create_admin_router(admin, management_session))

    _install_assets(app)
    _install_browser_routes(app, browser, owner, auth, service)
    _install_icon_route(app)
    _install_auth_routes(app, auth, session_payload)
    @app.get("/chat/history")
    def history(request: Request, before: Annotated[int | None, Field(gt=0)] = None):
        return service.store.history(owner(request), before)

    @app.post("/chat/messages")
    def send(body: Message, request: Request):
        session = auth.session(request)
        principal = service.authorize(session)
        selection = body.inference.model_dump() if body.inference is not None else None
        existing = service.store.find(principal, body.request_id)
        if existing and existing.get("request_options"):
            import json
            request_options = json.loads(existing["request_options"])
            if (selection != request_options.get("selection")
                    or body.terminal_context != request_options.get("terminal_context")):
                raise Rejected("message_options_changed", 409)
        else:
            if selection is not None and inference is None:
                raise Rejected("inference_catalog_unavailable", 503)
            request_options = {}
            if selection is not None:
                request_options.update(selection=selection, runtime=inference.resolve(selection))
            if body.terminal_context is not None:
                if owner_terminal is None:
                    raise Rejected("terminal_unavailable", 503)
                request_options["terminal_context"] = owner_terminal.scrub_context(session,
                    request.headers.get("x-radhouse-browser-tab"), body.terminal_context)
            after = authenticated(request)
            if (session.principal_id, session.conversation_id, session.binding_revision, session.token) != (
                    after.principal_id, after.conversation_id, after.binding_revision, after.token):
                raise Rejected("identity_binding_denied", 403)
        browser_data = None
        if getattr(browser, "control_enabled", False):
            existing = service.store.find(principal, body.request_id)
            if existing and existing.get("browser_context"):
                import json
                browser_data = json.loads(existing["browser_context"])
                saved = browser_data.get("browser_context")
                expected = {key: saved[key] for key in ("generation", "revision", "lease_id")} if saved else None
                if (body.browser_context.model_dump() if body.browser_context else None) != expected or bool(browser_data.get("use_previous_browser")) != body.use_previous_browser or browser_data["browser_owner"] != {
                        "principal_id": session.principal_id, "conversation_id": session.conversation_id}:
                    raise Rejected("browser_context_changed", 409)
            else:
                browser_data = browser.dispatch_data(session, request.headers.get("x-radhouse-browser-tab"),
                    body.browser_context.model_dump() if body.browser_context else None, use_previous=body.use_previous_browser)
        elif body.browser_context is not None or body.use_previous_browser:
            raise Rejected("browser_context_unavailable", 409)
        if getattr(browser, "control_enabled", False):
            _recheck_browser_binding(auth, service, browser, request, session,
                request.headers.get("x-radhouse-browser-tab"))
        result = service.send(principal, body.request_id, body.text,
            tuple(service.store.upload(principal, file_id) for file_id in body.attachments), browser_data=browser_data,
            request_options=request_options)
        if getattr(browser, "control_enabled", False):
            _recheck_browser_binding(auth, service, browser, request, session,
                request.headers.get("x-radhouse-browser-tab"))
        return result

    @app.get("/chat/messages/{request_id}")
    def message_receipt(request_id: str, request: Request):
        principal = owner(request)
        turn = service.store.find(principal, request_id)
        if turn is None: raise Rejected("message_not_found", 404)
        return {"turn": service.store.history(principal, before=turn["seq"] + 1, limit=1)["turns"][0]}

    _install_file_routes(app, service, owner)
    @app.get("/chat/library")
    def library(request: Request,
                before: Annotated[str | None, Field(max_length=256)] = None,
                query: Annotated[str, Field(max_length=512)] = "",
                source: Annotated[str, Field(pattern=r"^(all|user|assistant)$")] = "all"):
        return service.store.library(owner(request), before=before, query=query, source=source)

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

def _reply_lifespan(service):
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
    return lifespan


def _install_response_handlers(app):
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


def _install_assets(app):
    @app.get("/")
    @app.get("/library")
    @app.get("/browser")
    @app.get("/terminal")
    @app.get("/about-you")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/chat.js")
    def javascript():
        return FileResponse(STATIC / "chat.js", media_type=JAVASCRIPT_MEDIA_TYPE)

    @app.get("/format.js")
    def answer_formatter():
        return FileResponse(STATIC / "format.js", media_type=JAVASCRIPT_MEDIA_TYPE)

    @app.get("/chat.css")
    def stylesheet():
        return FileResponse(STATIC / "chat.css", media_type="text/css")

    @app.get("/browser-view.js")
    def browser_javascript():
        return FileResponse(STATIC / "browser-view.js", media_type=JAVASCRIPT_MEDIA_TYPE)

    @app.get("/browser-view.css")
    def browser_stylesheet():
        return FileResponse(STATIC / "browser-view.css", media_type="text/css")

    @app.get("/navigation.js")
    def navigation_javascript():
        return FileResponse(STATIC / "navigation.js", media_type=JAVASCRIPT_MEDIA_TYPE)

    @app.get("/navigation.css")
    def navigation_stylesheet():
        return FileResponse(STATIC / "navigation.css", media_type="text/css")

    @app.get("/library.js")
    def library_javascript():
        return FileResponse(STATIC / "library.js", media_type=JAVASCRIPT_MEDIA_TYPE)

    @app.get("/workspace-assets/{name}")
    def workspace_asset(name: str):
        if name not in {"about-you.js", "about-you.css", "owner-terminal.js", "owner-terminal.css",
                        "inference-controls.js", "inference-controls.css"}:
            raise Rejected("asset_not_found", 404)
        return FileResponse(STATIC / name,
            media_type=JAVASCRIPT_MEDIA_TYPE if name.endswith(".js") else "text/css")

    @app.get("/workspace-vendor/xterm/{name}")
    def terminal_vendor_asset(name: str):
        if name not in {"xterm.js", "xterm.css", "addon-fit.js"}:
            raise Rejected("asset_not_found", 404)
        return FileResponse(STATIC / "vendor" / "xterm" / name,
            media_type=JAVASCRIPT_MEDIA_TYPE if name.endswith(".js") else "text/css")


def _install_browser_routes(app, browser, owner, auth, service):
    if getattr(browser, "control_enabled", False):
        _install_controlled_browser_routes(app, browser, auth, service)
        return
    @app.get("/chat/browser")
    async def browser_status(request: Request):
        principal = await asyncio.to_thread(owner, request)
        if browser is None:
            raise Rejected("browser_unavailable", 503)
        status = await asyncio.to_thread(browser.status, principal)
        await asyncio.to_thread(owner, request)  # A concurrent logout discards metadata too.
        return status

    @app.get("/chat/browser/frame")
    async def browser_frame(request: Request,
            run_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")]):
        principal = await asyncio.to_thread(owner, request)
        if browser is None:
            raise Rejected("browser_unavailable", 503)
        frame = await asyncio.to_thread(browser.frame, principal, run_id)
        await asyncio.to_thread(owner, request)  # Never release pixels after login revocation.
        return Response(frame.jpeg, media_type="image/jpeg", headers={
            "X-Radhouse-Browser-Generation": frame.generation,
            "X-Radhouse-Browser-Frame-Id": frame.frame_id,
            "X-Radhouse-Browser-Received-At": str(frame.received_at)})


def _install_icon_route(app):
    @app.get("/icons/{name}.svg")
    def file_icon(name: str):
        if name not in {"pdf", "word", "excel", "powerpoint"}:
            raise Rejected("icon_not_found", 404)
        return FileResponse(STATIC / "icons" / (name + ".svg"), media_type="image/svg+xml")


def _install_auth_routes(app, auth, session_payload):
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


def _install_file_routes(app, service, owner):
    def file_receipt(attachment):
        return {"file_id":attachment.file_id, "name":attachment.name, "size":attachment.size,
                "sha256":attachment.sha256, "media_type":attachment.media_type, "kind":attachment.kind}

    @app.put("/chat/files/{file_id}")
    async def upload_file(file_id: str, request: Request, name: str):
        principal = await asyncio.to_thread(owner, request)  # Authorize before body consumption.
        digest, size, prefix = hashlib.sha256(), 0, bytearray()
        path = None
        try:
            stream, path = await asyncio.to_thread(service.store.begin_upload, principal, file_id, name)
            with stream:
                async for chunk in request.stream():
                    # Offload disk writes; never assemble the file in memory.
                    await asyncio.to_thread(stream.write, chunk)
                    digest.update(chunk); size += len(chunk)
                    prefix.extend(chunk[:max(0,4096-len(prefix))])
                await asyncio.to_thread(stream.flush)
                await asyncio.to_thread(os.fsync, stream.fileno())
            media, kind = classify(name, bytes(prefix))
            attachment = await asyncio.to_thread(service.store.commit_upload, principal, file_id, name, path, media, kind, digest.hexdigest(), size)
            return file_receipt(attachment)
        except OSError:
            raise Rejected("file_storage_unavailable", 507) from None
        finally:
            if path is not None: path.unlink(missing_ok=True)

    @app.get("/chat/files/{file_id}")
    def upload_receipt(file_id: str, request: Request):
        return file_receipt(service.store.upload(owner(request), file_id))

    @app.get("/chat/files/{file_id}/content")
    def original(file_id: str, request: Request, download: bool = False):
        return _original_response(service.store.upload(owner(request), file_id), request, download)

    @app.post("/chat/messages/{request_id}/retry")
    def retry(request_id: str, request: Request):
        return service.retry(owner(request), request_id)

    @app.get("/chat/messages/{request_id}/attachments/{position}")
    def attachment(request_id: str, position: Annotated[int, Field(ge=0)], request: Request, download: bool = False):
        attachment = service.store.attachment(owner(request), request_id, position)
        return _original_response(attachment, request, download)


def _original_response(attachment, request, download):
    disposition = "inline" if not download and attachment.kind in {"image", "audio"} else "attachment"
    headers = {"Content-Disposition": disposition + "; filename*=UTF-8''" + quote(attachment.name, safe=""), "Accept-Ranges": "bytes"}
    if isinstance(attachment.data, Path):
        return FileResponse(attachment.data, media_type=attachment.media_type, headers=headers)
    return _byte_response(attachment.data, attachment.media_type, headers, request.headers.get("range"))


def _byte_response(data, media_type, headers, range_header):
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
        return Response(data[start:end+1],status_code=206,media_type=media_type,headers=headers)
    return Response(data,media_type=media_type,headers=headers)


class BrowserControlBody(BrowserContextBody):
    pass


class BrowserTakeBody(BrowserControlBody):
    request_id: Annotated[str, Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")]


class BrowserInputBody(BrowserControlBody):
    sequence: Annotated[int, Field(gt=0)]
    frame_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")]
    viewport: dict[str, int]
    operation: Annotated[str, Field(pattern=r"^(click|text|press|scroll|navigate|back|reload)$")]
    arguments: dict


class BrowserReturnBody(BrowserControlBody):
    request_id: Annotated[str, Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")]


class BrowserVaultBody(BrowserControlBody):
    sequence: Annotated[int, Field(gt=0)]


class BrowserLoginBody(BrowserVaultBody):
    label: Annotated[str, Field(min_length=1, max_length=256)]
    identifier_type: Annotated[str, Field(pattern=r"^(email|phone|username)$")]
    identifier: Annotated[str, Field(min_length=1, max_length=512)]
    password: Annotated[str, Field(min_length=1, max_length=16384, repr=False)]


def _install_controlled_browser_routes(app, browser, auth, service):
    def access(request):
        session = auth.session(request)
        service.authorize(session)
        tab = request.headers.get("x-radhouse-browser-tab", "")
        browser.binding(session, tab)
        return session, tab

    def recheck(request, before, tab):
        if request.headers.get("x-radhouse-browser-tab", "") != tab:
            raise Rejected("browser_binding_changed", 409)
        _recheck_browser_binding(auth, service, browser, request, before, tab)

    async def call(request, method, *values):
        session, tab = await asyncio.to_thread(access, request)
        result = await asyncio.to_thread(method, session, tab, *values)
        await asyncio.to_thread(recheck, request, session, tab)
        return result

    @app.get("/chat/browser")
    async def browser_status(request: Request):
        return await call(request, browser.status)

    @app.post("/chat/browser/open")
    async def browser_open(request: Request):
        return await call(request, browser.open)

    @app.get("/chat/browser/frame")
    async def browser_frame(request: Request,
            generation: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")]):
        frame = await call(request, browser.frame, generation)
        return Response(frame.jpeg, media_type="image/jpeg", headers={
            "X-Radhouse-Browser-Generation": frame.generation,
            "X-Radhouse-Browser-Frame-Id": frame.frame_id,
            "X-Radhouse-Browser-Received-At": str(frame.received_at),
            "X-Radhouse-Browser-Width": str(frame.width), "X-Radhouse-Browser-Height": str(frame.height)})

    @app.post("/chat/browser/control/take")
    async def browser_take(body: BrowserTakeBody, request: Request):
        return await call(request, browser.control, "take", body.model_dump(exclude_none=True))

    @app.post("/chat/browser/control/heartbeat")
    async def browser_heartbeat(body: BrowserControlBody, request: Request):
        return await call(request, browser.control, "heartbeat", body.model_dump(exclude_none=True))

    @app.post("/chat/browser/control/input")
    async def browser_input(body: BrowserInputBody, request: Request):
        return await call(request, browser.control, "input", body.model_dump(exclude_none=True))

    @app.post("/chat/browser/control/pause")
    async def browser_pause(body: BrowserControlBody, request: Request):
        return await call(request, browser.control, "pause", body.model_dump(exclude_none=True))

    @app.post("/chat/browser/control/close")
    async def browser_close(body: BrowserControlBody, request: Request):
        return await call(request, browser.control, "close", body.model_dump(exclude_none=True))

    @app.post("/chat/browser/return")
    async def browser_return(body: BrowserReturnBody, request: Request):
        session, tab = await asyncio.to_thread(access, request)
        existing = service.store.find(session.principal_id, body.request_id)
        if existing and existing.get("browser_context"):
            import json
            data = json.loads(existing["browser_context"])
            if data.get("browser_owner") != {"principal_id": session.principal_id,
                    "conversation_id": session.conversation_id}:
                raise Rejected("browser_binding_changed", 409)
        else:
            await asyncio.to_thread(service.poll, session.principal_id)
            if service.store.pending(session.principal_id) is not None:
                raise Rejected("reply_pending", 409)
            data = await asyncio.to_thread(browser.dispatch_data, session, tab,
                body.model_dump(exclude={"request_id"}))
        await asyncio.to_thread(recheck, request, session, tab)
        result = await asyncio.to_thread(service.send, session.principal_id, body.request_id,
            "I’m returning the browser to you. Continue from the current page.", browser_data=data)
        await asyncio.to_thread(recheck, request, session, tab)
        return result

    @app.post("/chat/browser/logins/list")
    async def browser_logins(body: BrowserVaultBody, request: Request):
        return await call(request, browser.logins, "list", body.model_dump())

    @app.post("/chat/browser/logins")
    async def browser_login(body: BrowserLoginBody, request: Request):
        return await call(request, browser.logins, "save", body.model_dump())

    @app.delete("/chat/browser/logins/{entry_id}")
    async def browser_remove_login(entry_id: str, body: BrowserVaultBody, request: Request):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}", entry_id):
            raise Rejected("invalid_request", 422)
        return await call(request, browser.logins, "remove", {**body.model_dump(), "entry_id": entry_id})
