import json
from datetime import datetime, timezone

import httpx
import pytest

from radhouse.integrations.hermes import (
    HermesAgentWorkAdapter, HermesCapabilities, HermesDispatch, HermesGatewayError,
    HermesRun, HermesRunsClient, MAX_RESPONSE_BYTES,
)
from radhouse.domain.tasks import Attempt, Task


def client(handler):
    return HermesRunsClient(
        "http://127.0.0.1:8642", "control-secret",
        transport=httpx.MockTransport(handler),
    )


def test_start_and_identical_replay_use_the_pinned_runs_contract():
    requests = []

    def handler(request):
        requests.append(request)
        replayed = len(requests) == 2
        return httpx.Response(
            202,
            headers={"Idempotency-Replayed": "true"} if replayed else {},
            json={"run_id": "run-01", "status": "queued", "replayed": replayed},
        )

    with client(handler) as gateway:
        first = gateway.start_or_attach(
            input_text="Research a synthetic topic.",
            session_id="researcher-01",
            dispatch_key="task-01-attempt-01",
        )
        replay = gateway.start_or_attach(
            input_text="Research a synthetic topic.",
            session_id="researcher-01",
            dispatch_key="task-01-attempt-01",
        )

    assert first.run_id == replay.run_id == "run-01"
    assert first.replayed is False
    assert replay.replayed is True
    assert len(requests) == 2
    for request in requests:
        assert request.method == "POST"
        assert request.url == httpx.URL("http://127.0.0.1:8642/v1/runs")
        assert request.headers["authorization"] == "Bearer control-secret"
        assert request.headers["idempotency-key"] == "task-01-attempt-01"
        assert json.loads(request.content) == {
            "input": "Research a synthetic topic.",
            "session_id": "researcher-01",
        }
        assert "model" not in request.content.decode()
        assert "provider" not in request.content.decode()


def test_capability_preflight_requires_durable_bounded_idempotency():
    response = httpx.Response(200, json={
        "features": {"runs_idempotency": {
            "supported": True, "durable": True, "retention_seconds": 86_400,
        }}
    })
    with client(lambda _request: response) as gateway:
        capabilities = gateway.capabilities()
    assert capabilities.idempotency_retention_seconds == 86_400


@pytest.mark.parametrize(
    "idempotency",
    [
        {},
        {"supported": False, "durable": True, "retention_seconds": 86_400},
        {"supported": True, "durable": False, "retention_seconds": 86_400},
        {"supported": True, "durable": True, "retention_seconds": 0},
        {"supported": True, "durable": True, "retention_seconds": True},
    ],
)
def test_capability_preflight_fails_closed(idempotency):
    response = httpx.Response(200, json={"features": {"runs_idempotency": idempotency}})
    with client(lambda _request: response) as gateway, pytest.raises(HermesGatewayError) as caught:
        gateway.capabilities()
    assert caught.value.code == "runtime_idempotency_unavailable"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "runtime_authentication_failed"),
        (409, "runtime_dispatch_conflict"),
        (429, "runtime_capacity_limited"),
        (503, "runtime_unexpected_status"),
        (307, "runtime_unexpected_status"),
    ],
)
def test_refusals_are_sanitized_and_redirects_are_not_followed(status, code):
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        headers = {"location": "http://example.invalid/stolen"} if status == 307 else {}
        return httpx.Response(status, headers=headers, text="control-secret vendor detail")

    with client(handler) as gateway, pytest.raises(HermesGatewayError) as caught:
        gateway.start_or_attach(
            input_text="safe", session_id="session-01", dispatch_key="dispatch-01"
        )
    assert caught.value.code == code
    assert "control-secret" not in str(caught.value)
    assert calls == 1


def test_status_and_stop_target_only_the_recorded_run():
    requests = []

    def handler(request):
        requests.append((request.method, request.url.path))
        if request.url.path.endswith("/stop"):
            return httpx.Response(200, json={"run_id": "run-01", "status": "stopping"})
        return httpx.Response(
            200,
            json={"run_id": "run-01", "status": "completed", "output": "cited result"},
        )

    with client(handler) as gateway:
        result = gateway.status("run-01")
        stopped = gateway.stop("run-01")

    assert result.output == "cited result"
    assert result.status == "completed"
    assert stopped.status == "stopping"
    assert requests == [
        ("GET", "/v1/runs/run-01"),
        ("POST", "/v1/runs/run-01/stop"),
    ]


def test_missing_run_and_inactive_stop_remain_distinct():
    def handler(request):
        status = 409 if request.url.path.endswith("/stop") else 404
        return httpx.Response(status, json={"error": "untrusted"})

    with client(handler) as gateway:
        with pytest.raises(HermesGatewayError) as missing:
            gateway.status("run-01")
        with pytest.raises(HermesGatewayError) as inactive:
            gateway.stop("run-01")
    assert missing.value.code == "runtime_run_missing"
    assert inactive.value.code == "runtime_conflict"


def test_admission_rejects_a_replay_marker_disagreement():
    response = httpx.Response(
        202,
        json={"run_id": "run-01", "status": "queued", "replayed": True},
    )
    with client(lambda _request: response) as gateway, pytest.raises(HermesGatewayError) as caught:
        gateway.start_or_attach(
            input_text="safe", session_id="session-01", dispatch_key="dispatch-01"
        )
    assert caught.value.code == "runtime_response_mismatch"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"run_id": "run-01", "status": "invented"}),
        httpx.Response(200, json={"run_id": "different", "status": "running"}),
    ],
)
def test_untrusted_status_payloads_fail_closed(response):
    with client(lambda _request: response) as gateway, pytest.raises(HermesGatewayError):
        gateway.status("run-01")


def test_oversized_response_is_rejected_before_json_parsing():
    response = httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))
    with client(lambda _request: response) as gateway, pytest.raises(HermesGatewayError) as caught:
        gateway.status("run-01")
    assert caught.value.code == "runtime_response_too_large"


def test_transport_failure_is_a_bounded_runtime_error():
    def handler(request):
        raise httpx.ConnectError("control-secret internal route", request=request)

    with client(handler) as gateway, pytest.raises(HermesGatewayError) as caught:
        gateway.status("run-01")
    assert caught.value.code == "runtime_unavailable"
    assert "control-secret" not in str(caught.value)


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp://127.0.0.1:8642",
        "http://user:password@127.0.0.1:8642",
        "http://127.0.0.1:8642/base",
        "http://127.0.0.1:8642/?token=secret",
        "http://192.0.2.10:8642",
        "http://gateway.internal:8642",
    ],
)
def test_endpoint_must_be_a_plain_http_origin(endpoint):
    with pytest.raises(ValueError, match="invalid_hermes_endpoint"):
        HermesRunsClient(endpoint, "secret", transport=httpx.MockTransport(lambda _: None))


def test_https_origin_can_be_supplied_by_the_private_deployment_overlay():
    gateway = HermesRunsClient(
        "https://hermes.example", "secret",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"features": {}})
        ),
    )
    gateway.close()


class StubHermesClient:
    def __init__(self, status="completed"):
        self.run_status = status
        self.stopped = []

    def capabilities(self):
        return HermesCapabilities(86_400)

    def start_or_attach(self, *, input_text, session_id, dispatch_key):
        assert (input_text, session_id, dispatch_key) == (
            "Research safely.", "task-01", "attempt-01",
        )
        return HermesDispatch("run-01", session_id, "queued", False)

    def status(self, run_id):
        return HermesRun(run_id, self.run_status, "Cited result")

    def stop(self, run_id):
        self.stopped.append(run_id)
        return HermesRun(run_id, "stopping")


def test_agent_work_adapter_preserves_task_session_and_provider_binding():
    now = datetime(2026, 9, 12, 15, tzinfo=timezone.utc)
    client = StubHermesClient()
    adapter = HermesAgentWorkAdapter(
        client, runtime_revision="hermes-0.21.1", clock=lambda: now,
    )
    task = Task(
        "task-01", "alice", "bot-01", "project-01", "Research safely.",
        "nemo-chat", None, 3,
    )
    attempt = Attempt("attempt-01", task.task_id, 1, "worker")

    dispatch = adapter.start_or_attach(task, attempt, attempt.attempt_id)
    result = adapter.result(dispatch)

    assert dispatch.session_id == task.task_id
    assert dispatch.provider_binding == "nemo-chat"
    assert dispatch.runtime_revision == "hermes-0.21.1"
    assert dispatch.submitted_at == now
    assert int((dispatch.retention_until - now).total_seconds()) == 86_400
    assert result.state == "completed" and result.content == "Cited result"
    assert adapter.stop(dispatch)
    assert client.stopped == ["run-01"]


@pytest.mark.parametrize(
    ("hermes_state", "radhouse_state"),
    [
        ("queued", "running"),
        ("waiting_for_approval", "running"),
        ("failed", "failed"),
        ("cancelled", "cancelled"),
        ("interrupted", "unknown"),
    ],
)
def test_agent_work_adapter_maps_runtime_states_without_inventing_completion(
    hermes_state, radhouse_state,
):
    client = StubHermesClient(hermes_state)
    adapter = HermesAgentWorkAdapter(client, runtime_revision="hermes-0.21.1")
    from radhouse.domain.tasks import RuntimeDispatch
    now = datetime.now(timezone.utc)
    dispatch = RuntimeDispatch(
        "run-01", "task-01", "nemo-chat", "hermes-0.21.1", now, now,
    )
    assert adapter.result(dispatch).state == radhouse_state
