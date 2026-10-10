"""Pre-chat browser, current-auth relay and vault privacy contracts."""
import base64
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest

from radhouse.chat.app import create_app
from radhouse.chat.browser import BrowserSessionService, HermesBrowserClient
from radhouse.chat.service import ChatService
from radhouse.chat.store import ChatStore
from radhouse.domain.tasks import Rejected
from radhouse.integrations.hermes import HermesBrowserAdmissionRejected, HermesGatewayError, HermesRunsClient
from tests.test_chat_browser import JPEG
from tests.test_minimal_chat import SyntheticAuth


TAB = "a8b1f224-53a5-4a0a-bc67-5e51c4f5e2a6"
OTHER_TAB = "b8b1f224-53a5-4a0a-bc67-5e51c4f5e2a6"
HEADERS = {"Origin":"http://127.0.0.1", "X-Radhouse-CSRF":"synthetic-csrf", "X-Radhouse-Browser-Tab":TAB}
CONTROL = {"generation":"generation-1", "revision":3, "lease_id":"lease-1"}
LOGIN = {**CONTROL, "sequence":1,"label":"Example","identifier_type":"username",
    "identifier":"synthetic-account","password":"SYNTHETIC-SECRET-DO-NOT-STORE"}


class Auth(SyntheticAuth):
    revision = 1
    expires = 2000
    def session(self, request):
        return replace(super().session(request), binding_revision=self.revision,
            expires_at=datetime.fromtimestamp(self.expires,timezone.utc))
    refresh = session


class Native:
    def __init__(self):
        self.calls=[];self.after=lambda:None;self.active=False;self.holder=TAB
        self.page={"url":"https://example.org/login?token=discard#discard","title":"Example sign-in"}
        self.next=1
    def browser_session(self, session, operation, body):
        self.calls.append((session,operation,deepcopy(body)));self.after()
        public={"session_id":session,"state":"live" if self.active else "idle",
            "generation":"generation-1" if self.active else None,
            "url":self.page["url"] if self.active else None,"title":self.page["title"] if self.active else None,
            "viewport":{"width":960,"height":540} if self.active else None,
            "control":{"mode":"human","revision":3,"can_take":False} if self.active else None,
            "page_context":{"current":self.page if self.active else None,"previous":None if self.active else self.page}}
        if operation=="open":self.active=True;return self.browser_session(session,"status",body)
        if self.active and body["owner"]["tab_id"]==self.holder:
            public["control"].update(lease_id="lease-1",lease_expires_at=1800,next_sequence=self.next)
        if operation=="frame":
            return {**public,"jpeg":base64.b64encode(JPEG).decode(),"frame_id":"frame-1","received_at":1000.0,"captured_at":None}
        if operation=="control/input":
            return {"sequence":body["sequence"],"outcome":"applied"}
        if operation.startswith("logins/"):
            if body["owner"]["tab_id"]!=self.holder:raise HermesGatewayError("runtime_conflict")
            item={"id":"entry-1","kind":"login","label":"Example","origin":"https://example.org",
                "created_at":"2026-10-08T12:00:00Z","identifier_type":"username","identifier":"synthetic-account"}
            return {"success":True,"outcome":"applied","sequence":body["sequence"],
                "items":[item],"item":item,"removed":True,"password":"NEVER-RELEASE-THIS"}
        return public


@pytest.fixture
def app(tmp_path):
    auth,native=Auth(),Native()
    store=ChatStore(tmp_path/"chat.sqlite3")
    service=ChatService(store,None,owner_id="alice",clock=lambda:1000,browser_enabled=True,browser_control=True)
    browser=BrowserSessionService(store,native,owner_id="alice",chat_service=service,credential_vault=True,clock=lambda:1000)
    with TestClient(create_app(auth,service,browser=browser),base_url="http://127.0.0.1") as client:
        client.cookies.set(auth.cookie_name,"synthetic-cookie")
        yield client,auth,native,store,browser


def test_viewing_before_chat_does_not_open_or_create_session(app):
    client,_,native,store,_=app
    assert client.get("/browser").status_code==200
    result=client.get("/chat/browser",headers=HEADERS).json()
    assert result["state"]=="idle" and result["generation"] is None
    assert native.calls==[] and store.browser_session("alice") is None
    assert store.history("alice")["turns"]==[]


def test_explicit_open_before_chat_uses_durable_same_session_and_hashed_auth(app):
    client,_,native,store,_=app
    response=client.post("/chat/browser/open",headers=HEADERS,json={})
    assert response.status_code==200
    payload=response.json()
    assert payload["state"]=="live" and payload["control"]["next_sequence"]==1
    assert "session_id" not in payload and "synthetic-cookie" not in response.text
    native_session,operation,body=native.calls[0]
    assert operation=="open" and native_session==store.browser_session("alice")
    assert body["owner"]["auth_session_digest"]==hashlib.sha256(b"synthetic-cookie").hexdigest()
    assert body["auth_expires_at"]==2000
    assert payload["url"]=="https://example.org/login"
    assert store.history("alice")["turns"]==[]


@pytest.mark.parametrize("headers", [{},{"Origin":"https://foreign.example"}, {"Origin":"http://127.0.0.1","X-Radhouse-CSRF":"wrong"}])
def test_mutating_origin_and_csrf_are_checked_before_native_or_session_creation(app,headers):
    client,_,native,store,_=app
    assert client.post("/chat/browser/open",headers=headers,json={}).status_code==403
    assert native.calls==[] and store.browser_session("alice") is None


def test_sibling_tab_cannot_receive_human_lease(app):
    client,_,_,_,_=app
    client.post("/chat/browser/open",headers=HEADERS,json={})
    status=client.get("/chat/browser",headers={**HEADERS,"X-Radhouse-Browser-Tab":OTHER_TAB}).json()
    assert status["control"]=={"mode":"human","revision":3,"can_take":False}
    assert "lease-1" not in json.dumps(status)


@pytest.mark.parametrize("change",["logout","revision"])
def test_late_frame_is_discarded_after_auth_or_binding_changes(app,change):
    client,auth,native,_,_=app
    client.post("/chat/browser/open",headers=HEADERS,json={})
    native.after=(lambda:setattr(auth,"active",False)) if change=="logout" else (lambda:setattr(auth,"revision",2))
    response=client.get("/chat/browser/frame?generation=generation-1",headers=HEADERS)
    assert response.status_code==(401 if change=="logout" else 409)
    assert JPEG not in response.content


@pytest.mark.parametrize("change", ["logout", "revision"])
def test_completed_owner_input_ack_is_discarded_after_authentication_changes(app, change):
    client, auth, native, _, _ = app
    client.post("/chat/browser/open", headers=HEADERS, json={})
    count = len(native.calls)
    native.after = ((lambda: setattr(auth, "active", False)) if change == "logout"
        else (lambda: setattr(auth, "revision", 2)))
    response = client.post("/chat/browser/control/input", headers=HEADERS, json={
        **CONTROL, "sequence": 1, "operation": "navigate",
        "arguments": {"url": "https://example.org/"}, "frame_id": "frame-1",
        "viewport": {"width": 960, "height": 540}})
    assert response.status_code == (401 if change == "logout" else 409)
    assert "applied" not in response.text
    assert len(native.calls) == count + 1
    assert native.calls[-1][1] == "control/input"


def test_frame_geometry_is_published_and_no_native_session_leaks(app):
    client,_,_,_,_=app
    client.post("/chat/browser/open",headers=HEADERS,json={})
    result=client.get("/chat/browser/frame?generation=generation-1",headers=HEADERS)
    assert result.content==JPEG
    assert result.headers["x-radhouse-browser-width"]=="960"
    assert result.headers["x-radhouse-browser-height"]=="540"
    assert result.headers["cache-control"]=="no-store"


def test_owner_save_is_relayed_to_native_but_never_saved_or_echoed_by_web(app):
    client,_,native,store,_=app
    client.post("/chat/browser/open",headers=HEADERS,json={})
    response=client.post("/chat/browser/logins",headers=HEADERS,json=LOGIN)
    assert response.status_code==200
    assert response.json()["item"]["origin"]=="https://example.org"
    assert "password" not in response.text and LOGIN["password"] not in response.text
    call=native.calls[-1]
    assert call[1]=="logins/save" and call[2]["arguments"]["password"]==LOGIN["password"]
    assert set(call[2]["arguments"])=={"label","identifier_type","identifier","password"}
    assert "password" not in {key for key in call[2] if key != "arguments"}
    assert LOGIN["password"].encode() not in store.path.read_bytes()
    assert store.history("alice")["turns"]==[] and store.library("alice")["files"]==[]


@pytest.mark.parametrize("extra",[{"origin":"https://attacker.example"},{"owner":{"principal_id":"mallory"}},{"otp":"DO-NOT-ECHO"}])
def test_save_login_authority_and_unsupported_fields_rejected_without_secret_echo(app,extra):
    client,_,native,_,_=app
    client.post("/chat/browser/open",headers=HEADERS,json={});count=len(native.calls)
    response=client.post("/chat/browser/logins",headers=HEADERS,json={**LOGIN,**extra})
    assert response.status_code==422 and response.json()=={"error":"invalid_request"}
    assert len(native.calls)==count and LOGIN["password"] not in response.text


def test_save_login_expired_auth_is_denied_before_secret_relay(app):
    client,auth,native,_,_=app
    client.post("/chat/browser/open",headers=HEADERS,json={});count=len(native.calls);auth.expires=999
    response=client.post("/chat/browser/logins",headers=HEADERS,json=LOGIN)
    assert response.status_code==401 and len(native.calls)==count
    assert LOGIN["password"] not in response.text


def test_previous_closed_page_is_only_trusted_locator_metadata(app):
    client,auth,native,store,browser=app
    client.post("/chat/browser/open",headers=HEADERS,json={});native.active=False
    request=httpx.Request("GET","http://127.0.0.1",headers=HEADERS)
    session=replace(auth.login("alice","synthetic-password","123456","local",remember_browser=False),
        expires_at=datetime.fromtimestamp(2000,timezone.utc))
    data=browser.dispatch_data(session,TAB,use_previous=True)
    assert "browser_context" not in data
    assert data["page"]=={"url":"https://example.org/login","title":"Example sign-in","state":"previous"}
    assert data["use_previous_browser"] is True and store.history("alice")["turns"]==[]


def test_actual_private_http_save_route_and_error_bodies_never_escape():
    calls=[]
    def respond(request):
        calls.append((request.url.path,json.loads(request.content)))
        return httpx.Response(200,json={"success":True,"outcome":"applied","sequence":1})
    relay=HermesBrowserClient("http://127.0.0.1","synthetic-bearer",transport=httpx.MockTransport(respond))
    try:
        result=relay.browser_session("chat:one","logins/save",LOGIN)
        assert result["outcome"]=="applied"
        assert calls[0][0]=="/v1/browser-sessions/chat:one/logins/save"
        assert calls[0][1]["password"]==LOGIN["password"]
    finally:relay.close()


def dispatch_client(*, rejection=None, lose_ack=False):
    calls=[]
    state={"lose":lose_ack,"rejection":rejection,
        "vault":{"supported":True,"version":1,"scope":"local_login_only"}}
    def respond(request):
        if request.url.path=="/v1/capabilities":
            return httpx.Response(200,json={"features":{
                "runs_idempotency":{"supported":True,"durable":True,"retention_seconds":3600},
                "runs_disable_tools":{"supported":True},
                "runs_allowed_tools":{"supported":True,"version":1,"durable":True,"mode":"exact_subset_of_profile","max_names":32},
                "runs_browser_view":{"supported":True,"version":1,"mode":"same_session_view_only"},
                "runs_browser_control":{"supported":True,"version":1,"mode":"owner_session"},
                "browser_credential_vault":state["vault"]}})
        if request.method=="POST":
            calls.append((request.headers["Idempotency-Key"],json.loads(request.content)))
            if state["lose"]:
                state["lose"]=False;raise httpx.ReadError("synthetic lost acknowledgement",request=request)
            if state["rejection"] is not None:return httpx.Response(409,json=state["rejection"])
            replayed=len(calls)>1
            return httpx.Response(202,headers={"Idempotency-Replayed":"true" if replayed else "false"},
                json={"run_id":"run-1","status":"started" if not replayed else "running","replayed":replayed})
        return httpx.Response(200,json={"run_id":"run-1","status":"completed","output":"Done"})
    return HermesRunsClient("http://127.0.0.1","synthetic-bearer",transport=httpx.MockTransport(respond)),calls,state


@pytest.mark.parametrize("vault,owned,selected",[
    ({"supported":True,"version":1,"scope":"local_login_only"},True,True),
    ({"supported":False,"version":1,"scope":"local_login_only"},True,False),
    ({"supported":True,"version":2,"scope":"local_login_only"},True,False),
    ({"supported":True,"version":1,"scope":"external_manager"},True,False),
    ({"supported":True,"version":1,"scope":"local_login_only"},False,False),
])
def test_new_owned_browser_task_can_reuse_saved_logins_without_live_handoff(tmp_path,vault,owned,selected):
    runtime,calls,state=dispatch_client();state["vault"]=vault
    store=ChatStore(tmp_path/"chat.sqlite3")
    service=ChatService(store,runtime,owner_id="alice",clock=lambda:1000,browser_enabled=True,browser_control=True)
    owner={"principal_id":"alice","conversation_id":"personal-alice:alice:radhouse"}
    try:
        if not owned:
            with pytest.raises(Rejected,match="browser_binding_unavailable"):
                service.send("alice",str(uuid4()),"Open my saved login site")
            assert calls==[]
            return
        service.send("alice",str(uuid4()),"Open my saved login site",browser_data={"browser_owner":owner} if owned else None)
        body=calls[0][1]
        assert {"browser_login_list","browser_login_fill"}.issubset(body["allowed_tools"]) is selected
        assert "browser_context" not in body
        assert body.get("browser_owner")== (owner if owned else None)
    finally:runtime.close()


def test_real_run_handoff_freezes_current_page_not_secrets_and_retries_exact_payload(app):
    client,auth,native,store,browser=app
    client.post("/chat/browser/open",headers=HEADERS,json={})
    runtime,calls,_=dispatch_client(lose_ack=True)
    service=ChatService(store,runtime,owner_id="alice",clock=lambda:1000,browser_enabled=True,browser_control=True)
    session=replace(auth.login("alice","synthetic-password","123456","local",remember_browser=False),
        expires_at=datetime.fromtimestamp(2000,timezone.utc))
    data=browser.dispatch_data(session,TAB,CONTROL)
    request_id=str(uuid4())
    try:
        with pytest.raises(Rejected,match="assistant_unavailable"):
            service.send("alice",request_id,"Work through this page",browser_data=data)
        saved=store.find("alice",request_id)
        assert "synthetic-cookie" not in saved["browser_context"]
        assert "token=discard" not in saved["input_text"]
        assert "current page" in saved["input_text"] and "Example sign-in" in saved["input_text"]
        assert "browser_login_list" in json.loads(saved["tool_policy"])
        service.retry("alice",request_id)
        assert calls[0]==calls[1]
        body=calls[1][1]
        assert body["session_id"]==store.browser_session("alice")
        assert body["browser_owner"]=={"principal_id":"alice","conversation_id":session.conversation_id}
        assert body["browser_context"]["generation"]=="generation-1"
        assert body["browser_context"]["lease_id"]=="lease-1"
    finally:runtime.close()


@pytest.mark.parametrize("change", ["logout", "revision"])
@pytest.mark.parametrize("route", ["/chat/messages", "/chat/browser/return"])
def test_browser_wait_cannot_admit_fresh_run_after_authentication_changes(app, change, route):
    client, auth, native, store, browser = app
    client.post("/chat/browser/open", headers=HEADERS, json={})
    runtime, calls, _ = dispatch_client()
    service = ChatService(store, runtime, owner_id="alice", clock=lambda: 1000,
        browser_enabled=True, browser_control=True)
    native.after = ((lambda: setattr(auth, "active", False)) if change == "logout"
        else (lambda: setattr(auth, "revision", 2)))
    request_id = str(uuid4())
    body = {"request_id": request_id, **CONTROL}
    if route == "/chat/messages":
        body = {"request_id": request_id, "text": "Continue from this page",
            "browser_context": CONTROL}
    try:
        with TestClient(create_app(auth, service, browser=browser),
                base_url="http://127.0.0.1") as fresh_client:
            fresh_client.cookies.set(auth.cookie_name, "synthetic-cookie")
            response = fresh_client.post(route, headers=HEADERS, json=body)
        assert response.status_code == (401 if change == "logout" else 409)
        assert calls == []
        assert store.find("alice", request_id) is None
    finally:
        runtime.close()


@pytest.mark.parametrize("proof,terminal",[
    ({"error":"browser_context_rejected","admitted":False},True),
    ({"error":"different_error","admitted":False},False),
    ({"error":"browser_context_rejected","admitted":True},False),
])
def test_only_positive_exact_pre_admission_proof_can_close_expired_handoff(app,proof,terminal):
    client,auth,_,store,browser=app
    client.post("/chat/browser/open",headers=HEADERS,json={})
    runtime,_,_=dispatch_client(rejection=proof)
    service=ChatService(store,runtime,owner_id="alice",clock=lambda:1000,browser_enabled=True,browser_control=True)
    session=replace(auth.login("alice","synthetic-password","123456","local",remember_browser=False),
        expires_at=datetime.fromtimestamp(2000,timezone.utc))
    try:
        request_id=str(uuid4())
        with pytest.raises(Rejected):service.send("alice",request_id,"Continue",browser_data=browser.dispatch_data(session,TAB,CONTROL))
        saved=store.find("alice",request_id)
        assert saved["status"]==("failed" if terminal else "awaiting_dispatch")
        assert (store.pending("alice") is None)==terminal
    finally:runtime.close()


def test_web_save_and_remove_match_real_runtime_human_login_contract(tmp_path,monkeypatch):
    """The actual runtime function consumes the actual web relay's HTTP payload."""
    import threading
    from types import SimpleNamespace
    from tests.test_hermes_runtime_bridge import bridge
    from tests.test_browser_control import control
    from tests.test_native_control import native
    store=ChatStore(tmp_path/"chat.sqlite3")
    session_id=store.browser_session("alice",create=True)
    conversation="personal-alice:alice:radhouse"
    identity=control.BrowserIdentity(conversation,session_id,"generation-1")
    owner=control.OwnerBinding("alice",hashlib.sha256(b"synthetic-cookie").hexdigest(),1,TAB)
    controller=control.BrowserController(tmp_path/"native-control.sqlite3",maintenance_held=lambda:False,clock=lambda:1000)
    bound=controller.bind_browser(identity,None,principal_id="alice")
    pending=controller.request_takeover(identity,owner,"open-1",revision=bound.revision,auth_expires_at=2000)
    taken=controller.confirm_takeover(identity,pending.revision,control.FenceObservation(identity,None,True))
    values={**LOGIN,"revision":taken.revision,"lease_id":taken.lease.lease_id}
    item={"id":"entry-1","kind":"login","label":"Example","origin":"https://example.org",
        "created_at":"2026-10-08T12:00:00Z","identifier_type":"username","identifier":"synthetic-account"}
    seen=[]
    class Vault:
        def save_login(self,access,**arguments):
            seen.append(arguments)
            assert set(arguments)=={"label","identifier_type","identifier","password"}
            return {"success":True,"item":item}
        def remove_login(self,access,*,handle):
            assert handle=="entry-1";return {"success":True,"removed":True}
    monkeypatch.setattr(bridge,"_control_modules",lambda:(control,native))
    monkeypatch.setattr(bridge,"_controller",controller)
    monkeypatch.setattr(bridge,"_vault",Vault())
    monkeypatch.setattr(bridge,"_redacted",lambda value:value)
    owned=SimpleNamespace(identity=identity,operation_lock=threading.RLock(),last_handle=None)
    def respond(request):
        body=json.loads(request.content)
        private_owner=control.OwnerBinding(**{k:v for k,v in body["owner"].items() if k!="conversation_id"})
        operation=request.url.path.rsplit("/",1)[-1]
        return httpx.Response(200,json=bridge._human_login(owned,private_owner,body,operation))
    relay=HermesBrowserClient("http://127.0.0.1","synthetic-bearer",transport=httpx.MockTransport(respond))
    service=BrowserSessionService(store,relay,owner_id="alice",chat_service=None,credential_vault=True,clock=lambda:1000)
    session=replace(SyntheticAuth().login("alice","synthetic-password","123456","local",remember_browser=False),
        expires_at=datetime.fromtimestamp(2000,timezone.utc))
    try:
        assert service.logins(session,TAB,"save",values)=={"item":item}
        assert seen[0]["password"]==LOGIN["password"]
        assert service.logins(session,TAB,"remove",{**CONTROL,"revision":taken.revision,
            "lease_id":taken.lease.lease_id,"sequence":2,"entry_id":"entry-1"})=={"removed":True}
        assert LOGIN["password"].encode() not in store.path.read_bytes()
        assert LOGIN["password"].encode() not in controller.database_path.read_bytes()
    finally:relay.close()
