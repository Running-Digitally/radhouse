"""API factory: the caller must supply a real authentication boundary.

VS0 exercises this factory in-process with authenticators owned by its test
harness. This module has no fixture identity, environment bypass, or listener.
"""
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, TYPE_CHECKING

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from radhouse.api.schemas import (
    AdmitRequest, ErrorResponse, EventsResponse, PublicationResponse,
    PublishRequest, ReviewRequest, ReviewResponse, StateRequest, TaskResponse,
    WorkHomeResponse, LoginRequest, AuthSessionResponse, ProjectResponse, ReauthenticateRequest,
    GuidanceRequest, PermissionRequest, ReviewLocatorRequest,
    TaskTitleRequest, TaskTitleResponse, CreateProjectRequest,
)
from radhouse.domain.access import AuthContext
from radhouse.channels.commands import Envelope
from radhouse.domain.tasks import Rejected

if TYPE_CHECKING:
    from radhouse.application.service import Service
    from radhouse.auth.local import LocalAuthService, LocalSession


def create_app(
    service: "Service", authenticate: Callable[[Request], AuthContext],
    *, web_root: Path | None = None, local_auth: "LocalAuthService | None" = None,
) -> FastAPI:
    if not callable(authenticate):
        raise TypeError("authenticate must be an explicitly supplied callable")

    app = FastAPI(title="Radhouse operator contract")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'; object-src 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if (
            request.url.path == "/app"
            or request.url.path.startswith((
                "/app/", "/auth/", "/tasks", "/reviews", "/work-home",
                "/projects", "/conversations", "/agent-enrollment",
            ))
        ):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Rejected)
    async def rejected(_request: Request, error: Rejected) -> JSONResponse:
        return JSONResponse(status_code=error.status, content={"code": error.code})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _error: RequestValidationError) -> JSONResponse:
        # Validation errors can echo attacker-controlled or sensitive input.
        return JSONResponse(status_code=422, content={"code": "invalid_request"})

    def authenticated(request: Request) -> AuthContext:
        actor = authenticate(request)
        if not isinstance(actor, AuthContext):
            raise Rejected("authentication_required", 401)
        return actor

    Actor = Annotated[AuthContext, Depends(authenticated)]
    Conversation = Annotated[str, Query(min_length=1, max_length=200)]
    BindingRevision = Annotated[int, Query(ge=1)]
    from radhouse.api.conversations import install_conversation_routes
    install_conversation_routes(app,service,authenticated)
    errors = {status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422)}

    def session_response(session: "LocalSession", request: Request) -> AuthSessionResponse:
        return AuthSessionResponse(
            principal_id=session.principal_id,
            username=session.username,
            assurance_until=session.assurance_until,
            conversation_id=session.conversation_id,
            binding_revision=session.binding_revision,
            project_id=session.project_id,
            csrf_token=session.csrf_token,
        )

    if local_auth is not None:
        @app.get("/healthz")
        def health():
            local_auth.health()
            return {"status": "ready"}

        @app.post("/auth/login", response_model=AuthSessionResponse, responses=errors)
        def login(body: LoginRequest, request: Request, response: Response):
            local_auth.verify_origin(request)
            session = local_auth.login(
                body.username, body.password, body.totp_code,
                request.client.host if request.client is not None else "unknown",
                remember_browser=body.remember_browser,
            )
            response.set_cookie(
                local_auth.cookie_name, session.token,
                max_age=(30 * 24 * 60 * 60 if body.remember_browser else 12 * 60 * 60),
                secure=local_auth.secure_cookie, httponly=True, samesite="strict",
                path="/",
            )
            response.headers["Cache-Control"] = "no-store"
            return session_response(session, request)

        @app.get("/auth/session", response_model=AuthSessionResponse, responses=errors)
        def current_session(request: Request, response: Response):
            response.headers["Cache-Control"] = "no-store"
            return session_response(local_auth.refresh(request), request)

        @app.post("/auth/logout", status_code=204, responses=errors)
        def logout(request: Request, response: Response):
            local_auth.revoke(request)
            response.status_code = 204
            response.delete_cookie(
                local_auth.cookie_name, secure=local_auth.secure_cookie,
                httponly=True, samesite="strict", path="/",
            )
            response.headers["Cache-Control"] = "no-store"
            return response

        @app.post("/auth/reauthenticate", response_model=AuthSessionResponse, responses=errors)
        def reauthenticate(body: ReauthenticateRequest, request: Request):
            return session_response(local_auth.reauthenticate(request, body.password, body.totp_code), request)

    def read_envelope(actor: AuthContext, conversation: str, revision: int) -> Envelope:
        # Reads check the same current binding, without adding a delivery receipt.
        return Envelope(actor.channel, "read", conversation, revision, "read")

    @app.get("/work-home", response_model=WorkHomeResponse, responses=errors)
    def work_home(actor: Actor, conversation_id: Conversation, binding_revision: BindingRevision):
        return service.work_home(
            actor, envelope=read_envelope(actor, conversation_id, binding_revision)
        )

    @app.get("/projects", response_model=tuple[ProjectResponse, ...], responses=errors)
    def projects(actor: Actor, request: Request):
        values = service.projects(actor)
        return values

    @app.post("/projects", response_model=ProjectResponse, responses=errors)
    def create_project(body: CreateProjectRequest, actor: Actor):
        return service.create_project(
            actor, body.envelope.command(), body.display_name, tuple(body.bot_ids),
        )

    @app.post("/reviews/resolve", responses=errors)
    def resolve_review(body: ReviewLocatorRequest, actor: Actor):
        if service.review_links is None:
            raise Rejected("review_link_denied", 403)
        return service.review_links.resolve(actor, body.locator)

    @app.get("/tasks/{task_id}/review-audience", response_model=tuple[str, ...], responses=errors)
    def review_audience(task_id: str, actor: Actor, conversation_id: Conversation, binding_revision: BindingRevision):
        return service.review_audience(actor, task_id, envelope=read_envelope(actor, conversation_id, binding_revision))

    @app.get("/tasks/{task_id}/result", responses=errors)
    def download_result(task_id: str, actor: Actor, conversation_id: Conversation, binding_revision: BindingRevision):
        task = service.get(actor, task_id, envelope=read_envelope(actor, conversation_id, binding_revision))
        if task.result is None:
            raise Rejected("result_not_ready", 409)
        return PlainTextResponse(task.result, headers={
            "Content-Disposition": 'attachment; filename="radhouse-result.txt"',
            "Cache-Control": "no-store",
        })

    @app.post("/tasks", response_model=TaskResponse, responses=errors)
    def admit(body: AdmitRequest, actor: Actor):
        return service.admit(actor, body.envelope.command(), body.start.command())

    @app.get("/tasks/{task_id}", response_model=TaskResponse, responses=errors)
    def get_task(task_id: str, actor: Actor, conversation_id: Conversation, binding_revision: BindingRevision):
        return service.get(actor, task_id, envelope=read_envelope(actor, conversation_id, binding_revision))

    @app.post("/tasks/{task_id}/cancel", response_model=TaskResponse, responses=errors)
    def cancel(task_id: str, body: StateRequest, actor: Actor):
        return service.cancel(actor, task_id, body.expected_state_revision, envelope=body.envelope.command())

    @app.post("/tasks/{task_id}/guidance", response_model=TaskResponse, responses=errors)
    def guide(task_id: str, body: GuidanceRequest, actor: Actor):
        return service.guide(actor, task_id, body.expected_state_revision, body.text, envelope=body.envelope.command())

    @app.post("/tasks/{task_id}/title", response_model=TaskTitleResponse, responses=errors)
    def rename_task(task_id: str, body: TaskTitleRequest, actor: Actor):
        return service.rename_task(
            actor, task_id, body.expected_title_revision, body.title,
            envelope=body.envelope.command(),
        )

    @app.post("/tasks/{task_id}/permission", response_model=TaskResponse, responses=errors)
    def permission(task_id: str, body: PermissionRequest, actor: Actor):
        return service.respond_permission(actor, task_id, body.expected_state_revision,
            body.request_id, body.digest, body.choice, envelope=body.envelope.command())

    @app.post("/tasks/{task_id}/pause", response_model=TaskResponse, responses=errors)
    def pause(task_id: str, body: StateRequest, actor: Actor):
        return service.pause(actor, task_id, body.expected_state_revision, envelope=body.envelope.command())

    @app.post("/tasks/{task_id}/resume", response_model=TaskResponse, responses=errors)
    def resume(task_id: str, body: StateRequest, actor: Actor):
        return service.resume(actor, task_id, body.expected_state_revision, envelope=body.envelope.command())

    @app.post("/tasks/{task_id}/review", response_model=ReviewResponse, responses=errors)
    def prepare_review(task_id: str, body: ReviewRequest, actor: Actor):
        return service.prepare_review(
            actor, task_id, body.expected_state_revision,
            tuple(body.audience), body.ttl_seconds,
            envelope=body.envelope.command(),
        )

    @app.post("/reviews/{review_id}/publish", response_model=PublicationResponse, responses=errors)
    def publish(review_id: str, body: PublishRequest, actor: Actor):
        return service.publish(
            actor, body.envelope.command(), review_id,
            body.expected_revision, body.content, tuple(body.audience),
        )

    @app.get("/tasks/{task_id}/publication", response_model=PublicationResponse, responses=errors)
    def publication(task_id: str, actor: Actor, conversation_id: Conversation, binding_revision: BindingRevision):
        return service.get_publication(actor, task_id, envelope=read_envelope(actor, conversation_id, binding_revision))

    @app.get("/tasks/{task_id}/events", response_model=EventsResponse, responses=errors)
    def events(
        task_id: str, actor: Actor, conversation_id: Conversation,
        binding_revision: BindingRevision, after: Annotated[int, Query(ge=0)] = 0,
    ):
        return service.events(actor, task_id, after, envelope=read_envelope(actor, conversation_id, binding_revision))

    if web_root is not None:
        # Static assets contain no principal data. Every data request still
        # crosses the caller-supplied authentication and authorization boundary.
        app.mount("/app", StaticFiles(directory=web_root, html=True), name="operator-app")

    return app
