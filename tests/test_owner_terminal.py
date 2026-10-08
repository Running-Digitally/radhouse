"""Owner-only relay, schema constraints, fresh auth and bounded context."""
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from radhouse.chat.owner_terminal import HermesTerminalClient, OwnerTerminalService, create_router
from radhouse.auth.local import LocalSession
from radhouse.domain.tasks import Rejected

TAB, TERMINAL, GENERATION = (str(uuid4()) for _ in range(3))
SESSION = LocalSession("cookie-never-forwarded", "csrf", "owner", "owner",
    datetime.now(timezone.utc), "conversation", 1, "project", datetime.fromtimestamp(2000, timezone.utc))
STATUS = {"state":"open", "terminal_id":TERMINAL,"generation":GENERATION,"attach_epoch":1,
    "next_cursor":0,"last_sequence":0,"last_outcome":"none"}


class Relay:
    def __init__(self):
        self.calls=[]; self.after=lambda:None; self.result=dict(STATUS)
    def call(self, operation, body):
        self.calls.append((operation,body)); self.after(); return self.result


def test_binding_is_derived_from_current_owner_not_client_cookie():
    relay=Relay(); service=OwnerTerminalService(relay,owner_id="owner",clock=lambda:1000)
    service.call(SESSION,TAB,"status")
    owner=relay.calls[0][1]["owner"]
    assert owner["conversation_id"]=="conversation" and owner["binding_revision"]==1
    assert owner["auth_session_digest"]!="cookie-never-forwarded" and len(owner["auth_session_digest"])==64
    with pytest.raises(Rejected) as error: service.call(replace(SESSION,principal_id="foreign"),TAB,"status")
    assert error.value.status==403 and len(relay.calls)==1
    with pytest.raises(Rejected) as error: service.call(replace(SESSION,expires_at=datetime.fromtimestamp(900,timezone.utc)),TAB,"status")
    assert error.value.status==401


def test_reauth_after_wait_refuses_new_conversation_or_revocation():
    relay=Relay(); sessions=[SESSION]
    service=OwnerTerminalService(relay,owner_id="owner",clock=lambda:1000)
    app=FastAPI(); app.include_router(create_router(service,lambda _:sessions[0]))
    @app.exception_handler(Rejected)
    async def rejected(request,error):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error":error.code},status_code=error.status)
    relay.after=lambda:sessions.__setitem__(0,replace(SESSION,binding_revision=2))
    response=TestClient(app).post("/chat/terminal/status",json={"tab_id":TAB})
    assert response.status_code==409 and response.json()["error"]=="terminal_binding_changed"


def test_strict_routes_reject_shell_configuration_and_oversized_poll():
    relay=Relay(); app=FastAPI()
    app.include_router(create_router(OwnerTerminalService(relay,owner_id="owner",clock=lambda:1000),lambda _:SESSION))
    client=TestClient(app)
    for body in ({"tab_id":TAB,"argv":["sudo"]}, {"tab_id":TAB,"rows":True,"cols":80,"request_id":str(uuid4())}):
        assert client.post("/chat/terminal/open",json=body).status_code==422
    assert client.post("/chat/terminal/output",json={"tab_id":TAB,"terminal_id":TERMINAL,"generation":GENERATION,
        "attach_epoch":1,"cursor":0,"wait_ms":15001}).status_code==422
    assert relay.calls==[]


def test_scrub_response_cannot_change_capture_identity_or_leave_bounds():
    relay=Relay(); service=OwnerTerminalService(relay,owner_id="owner",clock=lambda:1000)
    snapshot={"kind":"terminal_excerpt","label":"Agent VM terminal","terminal_id":TERMINAL,"generation":GENERATION,
        "captured_at":"2026-10-08T18:00:00+00:00","source":"selection","text":"synthetic secret","truncated":False}
    relay.result={**snapshot,"text":"[REDACTED]"}
    assert service.scrub_context(SESSION,TAB,snapshot)["text"]=="[REDACTED]"
    relay.result={**snapshot,"captured_at":"2026-10-08T18:01:00+00:00"}
    with pytest.raises(Rejected): service.scrub_context(SESSION,TAB,snapshot)
    with pytest.raises(Rejected): service.scrub_context(SESSION,TAB,{**snapshot,"text":"é"*8192})


def test_native_http_single_dispatch_and_sufficient_ack_timeout():
    requests=[]
    def handle(request):
        requests.append(request)
        assert request.extensions["timeout"]["read"]==20
        return httpx.Response(200,json=STATUS)
    client=HermesTerminalClient("http://127.0.0.1:18643","synthetic-bearer",transport=httpx.MockTransport(handle))
    assert client.call("status",{})==STATUS and len(requests)==1
    client.close()
