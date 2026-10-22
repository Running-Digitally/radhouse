"""SPACE transport contract and failure injection, with no live VM or credentials."""
from dataclasses import replace
import json
import ssl

import httpx
import pytest

from radhouse.integrations.space import (
    MAX_RESPONSE_BYTES, SpaceClient, SpaceCreateSpec, SpaceError, SpaceReceipt,
)


SBX = "sbx_11111111-1111-1111-1111-111111111111"
OTHER_SBX = "sbx_22222222-2222-2222-2222-222222222222"
OP = "op_11111111-1111-1111-1111-111111111111"
SPEC = SpaceCreateSpec("fixture@sha256:" + "a" * 64, 2, 2048, 8192)
RECEIPT = SpaceReceipt(SBX, OP, "create_sandbox")


def client(handler, **options):
    return SpaceClient("https://space.example.test", "synthetic-management-secret",
                       transport=httpx.MockTransport(handler), **options)


def operation(state="succeeded", **changes):
    return {"id": OP, "kind": "create_sandbox", "state": state,
            "target_type": "sandbox", "target_id": SBX, **changes}


def accepted(sandbox_id=SBX):
    return httpx.Response(202, json={"sandbox_id": sandbox_id, "operation_id": OP})


def test_explicit_pinned_create_then_readiness_requires_all_three_observations():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer synthetic-management-secret"
        if request.method == "POST":
            assert request.headers["Idempotency-Key"] == "saved-run:create"
            body = json.loads(request.content)
            assert body["runtime"] == "firecracker"
            assert body["template"] == "fixture@sha256:" + "a" * 64
            assert body["resources"] == {"vcpu": 2, "memory_mib": 2048, "disk_mib": 8192}
            assert body["network_policy"] == {"version": "v1", "egress": {
                "default_action": "deny", "allow": [], "deny": []}}
            assert "env" not in body and "metadata" not in body
            assert request.url.path == "/v1/sandboxes"
            return accepted()
        assert "Idempotency-Key" not in request.headers
        if request.url.path == f"/v1/operations/{OP}":
            return httpx.Response(200, json=operation())
        if request.url.path == f"/v1/sandboxes/{SBX}":
            return httpx.Response(200, json={"id": SBX, "state": "running"})
        assert request.url.path == f"/v1/sandboxes/{SBX}/processes"
        assert request.url.query == b"limit=1"
        return httpx.Response(200, json={"data": [], "next_cursor": None})

    with client(handler) as gateway:
        receipt = gateway.create(SPEC, key="saved-run:create")
        assert receipt == RECEIPT
        assert len(calls) == 1  # Acknowledgement does not poll or start execution.
        assert gateway.ready(receipt) is True
    assert len(calls) == 4


@pytest.mark.parametrize("action", ["pause", "suspend", "wake", "delete"])
def test_lifecycle_and_delete_preserve_exact_target_key_and_operation_kind(action):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["Idempotency-Key"] == "saved-lifecycle-key"
        assert request.method == ("DELETE" if action == "delete" else "POST")
        assert request.url.path == f"/v1/sandboxes/{SBX}" + ("" if action == "delete" else ":" + action)
        return accepted()

    with client(handler) as gateway:
        receipt = (gateway.delete(SBX, key="saved-lifecycle-key") if action == "delete"
                   else gateway.lifecycle(SBX, action, key="saved-lifecycle-key"))
    assert receipt.kind == action + "_sandbox"
    assert len(calls) == 1


def test_lost_ack_does_not_retry_or_generate_another_identity(tmp_path):
    # A caller-owned durable record precedes network admission, as production
    # orchestration must eventually do. No application journal is implied here.
    saved = tmp_path / "intent.json"
    saved.write_text(json.dumps({"key": "persisted-create", "spec": SPEC.__dict__}))
    admitted = {}
    calls = []

    def handler(request):
        key = request.headers["Idempotency-Key"]
        body = json.loads(request.content)
        calls.append((key, body))
        if key not in admitted:
            admitted[key] = body
            raise httpx.ReadTimeout("synthetic-management-secret was in upstream detail")
        assert admitted[key] == body
        return accepted()

    with client(handler) as first:
        with pytest.raises(SpaceError) as failure:
            first.create(SPEC, key="persisted-create")
        assert failure.value.outcome_unknown is True
        assert str(failure.value) == "space_transport_error"
    assert len(calls) == 1
    restored = json.loads(saved.read_text())
    with client(handler) as second:
        assert second.create(SpaceCreateSpec(**restored["spec"]), key=restored["key"]) == RECEIPT
    assert calls[0] == calls[1] and len(admitted) == 1


@pytest.mark.parametrize("status", [301, 302, 307, 308, 401, 403, 404, 409, 429, 500, 503])
def test_unsuccessful_mutation_never_follows_redirect_or_claims_no_effect(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="private diagnostic and synthetic-management-secret",
                              headers={"Location": "https://untrusted.example.test/leak"})

    with client(handler) as gateway:
        with pytest.raises(SpaceError) as failure:
            gateway.delete(SBX, key="persisted-delete")
    assert failure.value.outcome_unknown is True
    assert str(failure.value) == "space_http_error"
    assert len(calls) == 1
    assert calls[0].url.host == "space.example.test"


@pytest.mark.parametrize("body", [[], {}, {"sandbox_id": SBX},
    {"sandbox_id": OTHER_SBX, "operation_id": OP},
    {"sandbox_id": SBX, "operation_id": "../operations/other"}])
def test_invalid_mutation_receipt_preserves_uncertainty(body):
    with client(lambda _: httpx.Response(202, json=body)) as gateway:
        with pytest.raises(SpaceError) as failure:
            gateway.lifecycle(SBX, "wake", key="saved-wake")
    assert failure.value.outcome_unknown


@pytest.mark.parametrize("changes", [{"id": "op_22222222-2222-2222-2222-222222222222"},
    {"target_id": OTHER_SBX}, {"target_type": "template"}, {"kind": "delete_sandbox"},
    {"state": "unknown_future_state"}, {"state": []}])
def test_operation_readiness_rejects_wrong_identity_or_unknown_outcome(changes):
    with client(lambda _: httpx.Response(200, json=operation(**changes))) as gateway:
        with pytest.raises(SpaceError, match="space_invalid_operation"):
            gateway.ready(RECEIPT)


@pytest.mark.parametrize("state", ["queued", "running", "failed", "canceled", "expired"])
def test_incomplete_operation_never_reaches_guest(state):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=operation(state))

    with client(handler) as gateway:
        if state in {"queued", "running"}:
            assert gateway.ready(RECEIPT) is False
        else:
            with pytest.raises(SpaceError, match="space_operation_failed"):
                gateway.ready(RECEIPT)
    assert len(calls) == 1


@pytest.mark.parametrize("state", ["creating", "suspended", "deleted", "future_state"])
def test_operation_success_does_not_make_nonrunning_sandbox_ready(state):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=operation() if "/operations/" in request.url.path
                              else {"id": SBX, "state": state})

    with client(handler) as gateway:
        assert gateway.ready(RECEIPT) is False
    assert len(calls) == 2


@pytest.mark.parametrize("body", [{"data": None}, {"data": {}}, {"other": []}])
def test_running_sandbox_still_requires_guest_readiness(body):
    def handler(request):
        if "/operations/" in request.url.path:
            return httpx.Response(200, json=operation())
        if request.url.path.endswith("/processes"):
            return httpx.Response(200, json=body)
        return httpx.Response(200, json={"id": SBX, "state": "running"})

    with client(handler) as gateway:
        with pytest.raises(SpaceError, match="space_invalid_process_readiness"):
            gateway.ready(RECEIPT)


@pytest.mark.parametrize("endpoint", ["http://space.example.test", "http://localhost", "ftp://host",
    "https://user:password@host", "https://host/v1", "https://host?secret=x", "https://host/#x",
    "https://host:invalid", "https://host:0", "https://host\n", "//host", ""])
def test_invalid_endpoint_is_rejected_before_transport(endpoint):
    with pytest.raises(ValueError, match="invalid_space_endpoint"):
        SpaceClient(endpoint, "fixture")


@pytest.mark.parametrize("endpoint", ["http://127.0.0.1:8000", "http://[::1]:8000", "https://space.example.test/"])
def test_loopback_http_and_verified_https_are_supported(endpoint):
    with SpaceClient(endpoint, "fixture", transport=httpx.MockTransport(lambda _: accepted())):
        pass


def test_disabled_certificate_verification_is_rejected():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with pytest.raises(ValueError, match="invalid_space_tls_context"):
        SpaceClient("https://space.example.test", "fixture", tls_context=context)


@pytest.mark.parametrize("template", ["seed", "seed:latest", "seed@sha256:abcdef012345", "..@sha256:" + "a" * 64])
def test_unpinned_template_is_rejected(template):
    with pytest.raises(ValueError, match="space_template_digest_required"):
        replace(SPEC, template=template)


@pytest.mark.parametrize("value", [0, -1, True, "2", 1.5])
def test_invalid_resource_shape_is_rejected(value):
    with pytest.raises(ValueError, match="invalid_space_resources"):
        replace(SPEC, vcpu=value)


def test_unsupported_actions_paths_and_unowned_keys_make_no_request():
    calls = []
    with client(lambda r: calls.append(r)) as gateway:
        for identifier in ("../host", "sbx_bad", "", SBX + "?x=y"):
            with pytest.raises(ValueError):
                gateway.delete(identifier, key="saved")
        for key in (None, "", "header\ninjection", "a" * 129):
            with pytest.raises(ValueError):
                gateway.create(SPEC, key=key)
        with pytest.raises(ValueError):
            gateway.lifecycle(SBX, "fork", key="saved")
        with pytest.raises(ValueError):
            gateway.ready(replace(RECEIPT, kind="delete_sandbox"))
    assert calls == []


@pytest.mark.parametrize("payload", [b'not json', b'[]', b'"' + b'x' * MAX_RESPONSE_BYTES + b'"'])
def test_invalid_or_oversized_bodies_are_bounded_and_sanitized(payload):
    with client(lambda _: httpx.Response(202, content=payload)) as gateway:
        with pytest.raises(SpaceError) as failure:
            gateway.create(SPEC, key="saved")
    assert failure.value.outcome_unknown
    assert str(failure.value) in {"space_response_too_large", "space_invalid_response"}


def test_environment_proxies_are_disabled(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted.example.test:3128")
    seen = {}
    original = httpx.Client

    def observe_client(**kwargs):
        seen.update(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(httpx, "Client", observe_client)
    with client(lambda _: accepted()) as gateway:
        assert gateway.create(SPEC, key="saved") == RECEIPT
    assert seen["trust_env"] is False and seen["follow_redirects"] is False


def test_deadline_is_checked_even_when_transport_returns_success(monkeypatch):
    times = iter([0.0, 11.0])
    monkeypatch.setattr("radhouse.integrations.space.time.monotonic", lambda: next(times))
    with client(lambda _: accepted()) as gateway:
        with pytest.raises(SpaceError, match="space_deadline_exceeded") as failure:
            gateway.create(SPEC, key="saved")
    assert failure.value.outcome_unknown


@pytest.mark.parametrize("token", [None, "", "injected\nheader", "space in token", "x" * 4097])
def test_invalid_management_credential_fails_before_network(token):
    with pytest.raises(ValueError, match="invalid_space_bearer"):
        SpaceClient("https://space.example.test", token)


@pytest.mark.parametrize("timeout", [0, -1, True, float("inf"), float("nan"), 61])
def test_unbounded_or_invalid_timeouts_are_refused(timeout):
    with pytest.raises(ValueError, match="invalid_space_timeout"):
        client(lambda _: accepted(), timeout=timeout)


def test_duplicate_json_identity_is_not_accepted():
    body = '{"sandbox_id":"' + OTHER_SBX + '","sandbox_id":"' + SBX + '","operation_id":"' + OP + '"}'
    with client(lambda _: httpx.Response(202, content=body)) as gateway:
        with pytest.raises(SpaceError, match="space_invalid_response") as failure:
            gateway.create(SPEC, key="saved")
    assert failure.value.outcome_unknown


def test_compressed_management_response_is_refused():
    import gzip
    body = gzip.compress(json.dumps({"sandbox_id": SBX, "operation_id": OP}).encode())
    with client(lambda _: httpx.Response(202, content=body, headers={"Content-Encoding": "gzip"})) as gateway:
        with pytest.raises(SpaceError, match="space_unexpected_encoding"):
            gateway.create(SPEC, key="saved")


def test_sandbox_observation_is_bound_to_requested_identity():
    with client(lambda _: httpx.Response(200, json={"id": OTHER_SBX, "state": "running"})) as gateway:
        with pytest.raises(SpaceError, match="space_invalid_sandbox"):
            gateway.sandbox_state(SBX)


def test_read_errors_do_not_claim_a_mutation_was_attempted():
    with client(lambda _: httpx.Response(404, text="private diagnostic")) as gateway:
        with pytest.raises(SpaceError) as failure:
            gateway.sandbox_state(SBX)
    assert failure.value.outcome_unknown is False
