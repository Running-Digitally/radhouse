"""Configured web routes survive a native agent outage and recover in place."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest

from radhouse.chat import main
from radhouse.chat.browser import HermesBrowserClient
from radhouse.integrations.hermes import HermesRunsClient
from tests.test_minimal_chat import SyntheticAuth


TAB="a8b1f224-53a5-4a0a-bc67-5e51c4f5e2a6"
HEADERS={"Origin":"http://127.0.0.1","X-Radhouse-CSRF":"synthetic-csrf","X-Radhouse-Browser-Tab":TAB}


class Auth(SyntheticAuth):
    def __init__(self,_dsn,**_kwargs):super().__init__()
    def session(self,request):
        return replace(super().session(request),expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    refresh=session
    def session_limits(self):
        return {"idle_timeout_seconds":1800,"maximum_session_seconds":43200,"remembered_session_seconds":2592000}
    def management_role(self,_session):return "admin"


@pytest.fixture
def factory(tmp_path,monkeypatch):
    # Positive source-custody assertion: the reusable interpreter has another editable install.
    assert Path(main.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1]/"src")
    state={"offline":True,"cap_offline":False,"control":True,"vault":{"supported":True,"version":1,"scope":"local_login_only"},"session":None}
    calls=[]
    def respond(request):
        calls.append((request.url.path,json.loads(request.content) if request.content else None))
        if state["offline"]:raise httpx.ConnectError("synthetic agent unavailable",request=request)
        if request.url.path=="/v1/capabilities":
            if state["cap_offline"]:raise httpx.ConnectError("synthetic capability probe unavailable",request=request)
            return httpx.Response(200,json={"features":{
                "runs_idempotency":{"supported":True,"durable":True,"retention_seconds":3600},
                "runs_disable_tools":{"supported":True},
                "runs_allowed_tools":{"supported":True,"version":1,"durable":True,"mode":"exact_subset_of_profile","max_names":32},
                "runs_browser_view":{"supported":True,"version":1,"mode":"same_session_view_only"},
                "runs_browser_control":{"supported":state["control"],"version":1,"mode":"owner_session"},
                "browser_credential_vault":state["vault"]}})
        if request.url.path=="/v1/runs":
            return httpx.Response(202,json={"run_id":"run-1","status":"started","replayed":False})
        if request.url.path=="/v1/runs/run-1":
            return httpx.Response(200,json={"run_id":"run-1","status":"running","output":None})
        body=json.loads(request.content)
        if request.url.path.endswith("/open"):state["session"]=body["session_id"]
        return httpx.Response(200,json={"session_id":state["session"],"state":"live","generation":"generation-1",
            "url":"https://example.org/login","title":"Example","viewport":{"width":960,"height":540},
            "control":{"mode":"human","revision":1,"can_take":False,"lease_id":"lease-1",
                "lease_expires_at":datetime.now(timezone.utc).timestamp()+60,"next_sequence":1}})
    config={"auth_dsn":"synthetic","auth_database":"synthetic","deployment_id":"synthetic","auth_encryption_key":"synthetic",
        "origin":"http://127.0.0.1","owner_id":"alice","hermes_endpoint":"http://127.0.0.1","hermes_bearer":"synthetic-bearer",
        "transcript_path":str(tmp_path/"chat.sqlite3"),"browser_enabled":True}
    monkeypatch.setattr(main,"_load_chat_config",lambda:config)
    monkeypatch.setattr(main,"LocalAuthService",Auth)
    monkeypatch.setattr(main,"HermesRunsClient",lambda endpoint,bearer,**kwargs:HermesRunsClient(endpoint,bearer,transport=httpx.MockTransport(respond),**kwargs))
    monkeypatch.setattr(main,"HermesBrowserClient",lambda endpoint,bearer:HermesBrowserClient(endpoint,bearer,transport=httpx.MockTransport(respond)))
    app=main.app_factory()
    assert calls==[]
    with TestClient(app,base_url="http://127.0.0.1") as client:
        client.cookies.set(Auth.cookie_name,"synthetic-cookie")
        yield client,state,calls


def test_factory_and_non_agent_views_survive_outage_then_browser_recovers(factory):
    client,state,calls=factory
    client.cookies.clear()
    assert client.post("/auth/login",headers={"Origin":"http://127.0.0.1"},json={
        "username":"alice","password":"synthetic-password","totp_code":"123456"}).status_code==200
    for path in ("/auth/session","/chat/history","/chat/library","/admin/settings","/settings","/browser"):
        assert client.get(path).status_code==200
    assert calls==[]
    assert client.post("/chat/browser/open",headers=HEADERS,json={}).status_code==503
    assert client.get("/auth/session").status_code==200
    state["offline"]=False
    response=client.post("/chat/browser/open",headers=HEADERS,json={})
    assert response.status_code==200 and response.json()["vault_enabled"] is True
    assert client.get("/chat/browser",headers=HEADERS).json()["generation"]=="generation-1"
    state["cap_offline"]=True
    assert client.get("/chat/browser",headers=HEADERS).json()["vault_enabled"] is False
    state["cap_offline"]=False
    state["vault"]={"supported":False,"version":1,"scope":"local_login_only"}
    assert client.get("/chat/browser",headers=HEADERS).json()["vault_enabled"] is False
    state["vault"]={"supported":True,"version":1,"scope":"local_login_only"}
    assert client.get("/chat/browser",headers=HEADERS).json()["vault_enabled"] is True


@pytest.mark.parametrize("vault",[None,{"supported":False,"version":1,"scope":"local_login_only"},
    {"supported":True,"version":2,"scope":"local_login_only"},{"supported":True,"version":1,"scope":"external_manager"}])
def test_unqualified_runtime_never_enables_or_receives_vault_tools(factory,vault):
    client,state,calls=factory;state.update(offline=False,vault=vault)
    assert client.post("/chat/browser/open",headers=HEADERS,json={}).json()["vault_enabled"] is False
    response=client.post("/chat/messages",headers=HEADERS,json={"request_id":str(uuid4()),"text":"Open this website"})
    assert response.status_code==200
    dispatch=next(body for path,body in calls if path=="/v1/runs")
    assert not {"browser_login_list","browser_login_fill"}&set(dispatch["allowed_tools"])


def test_missing_control_runtime_keeps_web_available_and_dispatch_unadmitted(factory):
    client,state,calls=factory;state.update(offline=False,control=False)
    assert client.get("/auth/session").status_code==200
    assert client.post("/chat/browser/open",headers=HEADERS,json={}).json()["vault_enabled"] is False
    response=client.post("/chat/messages",headers=HEADERS,json={"request_id":str(uuid4()),"text":"Open this website"})
    assert response.status_code==503
    assert not any(path=="/v1/runs" for path,_ in calls)
