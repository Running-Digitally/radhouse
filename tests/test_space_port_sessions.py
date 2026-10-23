"""Scoped browser-transport admission; no live credentials or network."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import httpx
import pytest

from radhouse.integrations.space import SpaceClient, SpaceError

SBX = "sbx_11111111-1111-1111-1111-111111111111"
SESSION = "port_11111111-1111-1111-1111-111111111111"
PATH = f"/v1/sessions/{SESSION}/proxy"


def response():
    return {"id": SESSION, "sandbox_id": SBX, "kind": "port", "state": "pending",
            "target_port": 8080, "target_protocol": "http", "scopes": ["port:connect"],
            "attach": {"url": "https://data.example.test" + PATH, "events_url": None,
                       "token": "synthetic-scoped-secret", "token_transport": ["authorization_header"],
                       "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}}


def client(handler):
    return SpaceClient("https://management.example.test", "synthetic-management-secret",
                       transport=httpx.MockTransport(handler))


def create(gateway):
    return gateway.create_port_session(SBX, 8080, data_plane_origin="https://data.example.test", key="saved-port-intent")


@pytest.mark.parametrize("relative", [False, True])
def test_create_binds_scoped_destination_without_attaching(relative):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.host == "management.example.test"
        assert request.url.path == f"/v1/sandboxes/{SBX}/port-sessions"
        assert request.headers["Authorization"] == "Bearer synthetic-management-secret"
        assert request.headers["Idempotency-Key"] == "saved-port-intent"
        assert json.loads(request.content) == {"port": 8080, "protocol": "http"}
        data = response()
        if relative:
            data["attach"]["url"] = PATH
        return httpx.Response(201, json=data)
    with client(handler) as gateway:
        session = create(gateway)
    assert len(calls) == 1
    assert session.attach_url == "https://data.example.test" + PATH
    assert session.authorization() == {"Authorization": "Bearer synthetic-scoped-secret"}
    assert "secret" not in repr(session)
    with pytest.raises(SpaceError, match="space_attach_expired"):
        replace(session, expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)).authorization()


@pytest.mark.parametrize("field,value", [
    ("url", "https://evil.example.test" + PATH), ("url", "//data.example.test" + PATH),
    ("url", "http://data.example.test" + PATH), ("url", "https://data.example.test" + PATH + "?token=secret"),
    ("url", PATH + "/../other"), ("url", PATH + "#fragment"), ("url", PATH.replace("11111111", "22222222")),
    ("url", "https://data.example.test\\@evil.example.test" + PATH),
    ("expires_at", "2000-01-01T00:00:00Z"), ("expires_at", "2099-01-01T00:00:00"),
    ("expires_at", None), ("token", "secret\r\nX-Other: value"), ("token", ""),
    ("token", "synthetic-management-secret"),
    ("token_transport", "authorization_header"), ("token_transport", ["first_frame"]),
    ("events_url", "https://evil.example.test/events"),
])
def test_bad_attach_receipt_preserves_uncertain_outcome(field, value):
    data = response(); data["attach"][field] = value
    with client(lambda _: httpx.Response(201, json=data)) as gateway:
        with pytest.raises(SpaceError) as error:
            create(gateway)
    assert error.value.outcome_unknown and str(error.value) == "space_invalid_port_session"


@pytest.mark.parametrize("field,value", [("id", SESSION.replace("port_", "proc_")),
    ("sandbox_id", SBX.replace("11111111", "22222222")), ("target_port", 9222),
    ("target_port", True), ("kind", "terminal"), ("target_protocol", "tcp"),
    ("scopes", ["port:connect", "terminal:connect"]), ("state", "revoked"), ("attach", None)])
def test_wrong_session_rejected(field, value):
    data = response(); data[field] = value
    with client(lambda _: httpx.Response(201, json=data)) as gateway:
        with pytest.raises(SpaceError, match="space_invalid_port_session"):
            create(gateway)


@pytest.mark.parametrize("port,origin", [(True,"https://data.example.test"), (0,"https://data.example.test"),
    (65536,"https://data.example.test"), (8080,"http://private.example.test"),
    (8080,"https://data.example.test/path"), (8080,"https://data.example.test\\@other.test")])
def test_invalid_configuration_rejected_before_mutation(port, origin):
    calls=[]
    with client(lambda request: calls.append(request)) as gateway:
        with pytest.raises(ValueError):
            gateway.create_port_session(SBX,port,data_plane_origin=origin,key="saved")
    assert not calls


def test_lost_ack_is_not_replayed_and_does_not_expose_transport_detail():
    calls=[]
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("synthetic-management-secret")
    with client(handler) as gateway:
        with pytest.raises(SpaceError) as error:
            create(gateway)
    assert len(calls)==1 and error.value.outcome_unknown
    assert str(error.value)=="space_transport_error"


def test_revocation_checks_exact_session_and_requires_explicit_success():
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.method=="DELETE" and request.url.path==f"/v1/sandboxes/{SBX}/sessions/{SESSION}"
        data=response();data['state']='revoked';data['attach']=None
        return httpx.Response(200,json=data)
    with client(handler) as gateway:
        gateway.revoke_port_session(SBX,SESSION,key="saved-revoke")
    assert len(calls)==1
    for data in ({}, {**response(),"state":"open"}, {**response(),"state":"revoked","sandbox_id":"wrong"}):
        with client(lambda _: httpx.Response(200,json=deepcopy(data))) as gateway:
            with pytest.raises(SpaceError) as error:
                gateway.revoke_port_session(SBX,SESSION,key="saved-revoke")
            assert error.value.outcome_unknown
