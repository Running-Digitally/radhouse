"""Owner controls and a separate, narrowly scoped native-worker callback."""
import asyncio
import hmac
import json
import os
from pathlib import Path
import re
import stat

from fastapi import Request
from fastapi.responses import FileResponse
import psycopg

from radhouse.auth.local import LocalAuthError, _verified_connection
from radhouse.storage.postgres import ApplicationStorageError
from radhouse.domain.tasks import Rejected
from .commitment_review import CommitmentReview


def standing_authorizer(auth):
    """Read durable account/binding authority; this does not renew any session.

    Reuses the auth service's verified database connection and binding lookup.
    The responsibility's explicit active/epoch grant is checked separately.
    """
    def authorize(owner, conversation, revision):
        try:
            with auth._connection() as connection:
                _verified_connection(connection, auth._deployment_id, auth._database)
                row = connection.execute("SELECT c.username FROM public.local_credentials c "
                    "JOIN public.actors a USING(principal_id) WHERE c.principal_id=%s AND a.active", (owner,)).fetchone()
                if row is None:
                    return False
                try:
                    binding = auth._binding(connection, owner, row["username"])
                except Rejected:
                    return False
                return binding["conversation_id"] == conversation and binding["binding_revision"] == revision
        except (psycopg.Error, ApplicationStorageError, LocalAuthError):
            raise Rejected("responsibility_authority_unavailable", 503) from None
    return authorize


async def _body(request, maximum=16000):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > maximum:
            raise Rejected("review_body_too_large", 413)
        raw.extend(chunk)
    try:
        value = json.loads(raw)
        if type(value) is not dict:
            raise ValueError
        return value
    except ValueError:
        raise Rejected("invalid_review_request", 422) from None


def install_responsibility_page(app, auth, service):
    @app.get("/responsibilities")
    def page(request: Request):
        service.authorize(auth.session(request))
        return FileResponse(Path(__file__).parent / "static/responsibilities.html")

    @app.get("/responsibilities.js")
    def javascript():
        return FileResponse(Path(__file__).parent / "static/responsibilities.js", media_type="application/javascript")

    @app.get("/responsibilities.css")
    def stylesheet():
        return FileResponse(Path(__file__).parent / "static/responsibilities.css", media_type="text/css")


def install_commitment_review(app, auth, service, review, worker_bearer):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", worker_bearer):
        raise ValueError("invalid_review_worker_bearer")
    app.state.commitment_review = review
    install_responsibility_page(app, auth, service)

    def owner_session(request):
        current = auth.session(request)
        service.authorize(current)
        return current

    def owner_change(operation, *args):
        with service.dispatch_gate.admission():
            return operation(*args)

    def worker(request):
        supplied = request.headers.get("authorization", "")
        if len(supplied) > 160 or not hmac.compare_digest(supplied.encode(), ("Bearer " + worker_bearer).encode()):
            raise Rejected("review_worker_denied", 403)

    @app.get("/chat/responsibilities/commitments")
    def status(request: Request):
        owner_session(request)
        return review.status()

    @app.post("/chat/responsibilities/commitments")
    async def control(request: Request):
        current = await asyncio.to_thread(owner_session, request)
        body = await _body(request, 1024)
        if set(body) != {"active"}:
            raise Rejected("invalid_responsibility", 422)
        return await asyncio.to_thread(owner_change, review.set_active, current.conversation_id,
                                       current.binding_revision, body["active"])

    @app.post("/chat/responsibilities/commitments/{identifier}")
    async def decide(identifier: str, request: Request):
        await asyncio.to_thread(owner_session, request)
        body = await _body(request, 10000)
        if "action" in body:
            return await asyncio.to_thread(owner_change, review.followup_action, identifier, body)
        if set(body) != {"decision"}:
            raise Rejected("invalid_commitment_decision", 422)
        return await asyncio.to_thread(owner_change, review.decide, identifier, body["decision"])

    @app.get("/chat/responsibilities/commitments/{identifier}")
    def item(identifier: str, request: Request):
        owner_session(request)
        return {"item": review.item(identifier)}

    @app.post("/internal/commitment-review/claim")
    def claim(request: Request):
        worker(request)
        with service.dispatch_gate.admission():
            return review.claim(research_capable=request.headers.get('X-Radhouse-Research') == 'v1')

    @app.post('/internal/commitment-review/research')
    async def attach_research(request: Request):
        worker(request)
        body = await _body(request, 45000)
        if (set(body) != {'review_id', 'evidence'} or not isinstance(body['review_id'], str)
                or len(body['review_id']) > 100):
            raise Rejected('invalid_review_request', 422)
        def attach():
            with service.dispatch_gate.admission():
                return review.attach_research(body['review_id'], body['evidence'])
        return await asyncio.to_thread(attach)

    @app.post("/internal/commitment-review/complete")
    async def complete(request: Request):
        worker(request)
        body = await _body(request)
        if (set(body) != {"review_id", "output", "failed"}
                or not isinstance(body["review_id"], str) or len(body["review_id"]) > 100
                or not isinstance(body["output"], str) or type(body["failed"]) is not bool):
            raise Rejected("invalid_review_request", 422)
        def publish():
            with service.dispatch_gate.admission():
                return review.complete(body["review_id"], body["output"], failed=body["failed"])
        return await asyncio.to_thread(publish)


def configure_commitment_review(app, auth, service):
    """No configuration means no source grant, routes or background execution."""
    location = os.environ.get("RADHOUSE_COMMITMENT_REVIEW_CONFIG")
    if not location:
        install_responsibility_page(app, auth, service)
        return None
    path = Path(location)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("review_config_requires_private_file")
    config = json.loads(path.read_text())
    if set(config) != {"store_path", "worker_bearer", "timezone"}:
        raise ValueError("invalid_review_config")
    review = CommitmentReview(config["store_path"], service.store, service.owner_id,
                              standing_authorizer(auth), timezone=config["timezone"])
    install_commitment_review(app, auth, service, review, config["worker_bearer"])
    service.responsibility_context = review.chat_context
    return review
