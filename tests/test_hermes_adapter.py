import json
import base64
from dataclasses import replace
from hashlib import sha256
from datetime import datetime, timezone

import httpx
import pytest

from radhouse.integrations.hermes import (
    HermesAgentWorkAdapter, HermesCapabilities, HermesDispatch, HermesGatewayError,
    HermesRun, HermesRunsClient, MAX_RESPONSE_BYTES, RoutingAgentWork,
)
from radhouse.domain.tasks import Attempt, InputFile, Task


def client(handler):
    return HermesRunsClient(
        "http://127.0.0.1:8642", "control-secret",
        transport=httpx.MockTransport(handler),
    )


def guidance_payload(state="accepted"):
    return {"object": "hermes.run.steer", "run_id": "run-1", "control_id": "control:" + "a" * 64,
            "input_sha256": sha256("  Focus on cost\n".encode()).hexdigest(), "accepted": state != "too_late",
            "state": state, "revision": 1, "reason": None, "checkpoint_id": None,
            "api_request_id": None, "replayed": False}


@pytest.mark.parametrize("state", ["accepted", "applied", "too_late", "not_applied", "unknown"])
def test_identified_guidance_round_trip_preserves_exact_input_and_outcome(state):
    calls = []
    payload = guidance_payload(state)
    if state == "applied":
        payload.update(checkpoint_id="checkpoint:1", api_request_id="request:2")
    def handler(request):
        calls.append(request)
        if request.method == "POST":
            assert json.loads(request.content) == {"input": "  Focus on cost\n", "control_id": payload["control_id"]}
            return httpx.Response(200, json=payload)
        return httpx.Response(200, json={"run_id": "run-1", "status": "completed", "output": "Result",
                                        "guidance_receipts": [payload]})
    with client(handler) as gateway:
        receipt = gateway.steer("run-1", "  Focus on cost\n", control_id=payload["control_id"])
        assert gateway.status("run-1").guidance_receipts == (receipt,)
        assert receipt.state == state and receipt.accepted is (state != "too_late")
    assert [r.method for r in calls] == ["POST", "GET"]


@pytest.mark.parametrize("change", [
    {"run_id": "other-run"}, {"control_id": "control:" + "b" * 64}, {"input_sha256": "0" * 64},
    {"state": "finished"}, {"state": []}, {"revision": True}, {"revision": 0}, {"accepted": False},
    {"state": "too_late"}, {"reason": "Private diagnostic text"}, {"checkpoint_id": []},
    {"state": "applied"}, {"replayed": "false"}, {"object": "unknown"},
])
def test_identified_guidance_rejects_unverifiable_acknowledgement_without_retry(change):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={**guidance_payload(), **change})
    with client(handler) as gateway:
        with pytest.raises(HermesGatewayError):
            gateway.steer("run-1", "  Focus on cost\n", control_id="control:" + "a" * 64)
    assert len(calls) == 1


def test_duplicate_or_unbounded_guidance_receipts_are_not_accepted():
    for receipts in ([guidance_payload()] * 2, [guidance_payload()] * 65, {}, [None]):
        with client(lambda _: httpx.Response(200, json={"run_id": "run-1", "status": "running", "guidance_receipts": receipts})) as gateway:
            with pytest.raises(HermesGatewayError, match="runtime_malformed_guidance"):
                gateway.status("run-1")


def test_steering_and_approval_target_exact_run_and_single_request():
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/steer"):
            assert json.loads(request.content) == {"input": "Focus on cost"}
            return httpx.Response(200, json={"run_id": "run-1", "accepted": True})
        assert json.loads(request.content) == {"request_id": "permission-1", "choice": "once"}
        return httpx.Response(200, json={"run_id": "run-1", "request_id": "permission-1", "choice": "once", "resolved": 1})
    with client(handler) as gateway:
        assert gateway.steer("run-1", "Focus on cost")
        assert gateway.approve("run-1", "permission-1", "once")
        with pytest.raises(ValueError): gateway.approve("run-1", "permission-1", "always")
    assert len(calls) == 2
    assert all("idempotency-key" not in request.headers for request in calls)


def test_approval_status_keeps_only_bounded_action_identity():
    with client(lambda _: httpx.Response(200, json={"run_id": "run-1", "status": "waiting_for_approval",
        "approval": {"request_id": "request-1", "command": "cat report.txt", "private_metadata": "omit"}})) as gateway:
        run = gateway.status("run-1")
    assert run.permission_request == {"run_id": "run-1", "request_id": "request-1", "command": "cat report.txt"}


def test_pollable_status_exposes_only_allowlisted_activity_label():
    with client(lambda _: httpx.Response(200, json={
        "run_id": "run-1",
        "status": "running",
        "last_event": "tool.started",
        "updated_at": 1_795_000_000.75,
        "private_preview": "cat /private/secret.txt",
    })) as gateway:
        run = gateway.status("run-1")
    assert run.activity.run_id == "run-1"
    assert run.activity.event == "tool.started"
    assert run.activity.label == "Using an assigned tool"
    assert run.activity.occurred_at == 1_795_000_000
    assert "secret" not in run.activity.label


def test_pollable_status_without_runtime_timestamps_has_stable_unknown_age():
    with client(lambda _: httpx.Response(200, json={
        "run_id": "run-1", "status": "running", "last_event": "tool.completed",
    })) as gateway:
        first = gateway.status("run-1").activity
        second = gateway.status("run-1").activity
    assert first == second
    assert first.occurred_at == 0


@pytest.mark.parametrize("field,value", [("last_event", []), ("updated_at", True), ("updated_at", "now")])
def test_malformed_runtime_activity_metadata_fails_closed(field, value):
    with client(lambda _: httpx.Response(200, json={
        "run_id": "run-1", "status": "running", field: value,
    })) as gateway:
        with pytest.raises(HermesGatewayError, match="runtime_malformed_response"):
            gateway.status("run-1")


def test_start_and_identical_replay_use_the_pinned_runs_contract():
    requests = []

    def handler(request):
        requests.append(request)
        replayed = len(requests) == 2
        return httpx.Response(
            202,
            headers={"Idempotency-Replayed": "true"} if replayed else {},
            json={"run_id": "run-01", "status": "running" if replayed else "started", "replayed": replayed},
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
    assert first.status == "queued" and replay.status == "running"
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


def test_exact_allowed_tools_are_capability_checked_and_sent_once():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"features": {
                "runs_idempotency": {"supported": True, "durable": True, "retention_seconds": 86400},
                "runs_allowed_tools": {"supported": True, "durable": True, "version": 1,
                    "mode": "exact_subset_of_profile", "max_names": 32},
            }})
        assert json.loads(request.content) == {
            "input": "Use only search_files and read_file.",
            "session_id": "task-01",
            "allowed_tools": ["search_files", "read_file"],
        }
        return httpx.Response(202, json={"run_id": "run-01", "status": "started", "replayed": False})

    task = Task("task-01", "alice", "bot-01", "project-01",
                "Use only search_files and read_file.", "nemo-chat", None, 3,
                allowed_tools=("search_files", "read_file"))
    with client(handler) as gateway:
        adapter = HermesAgentWorkAdapter(
            gateway, runtime_revision="hermes-exact-tools", clock=lambda: datetime.now(timezone.utc)
        )
        dispatch = adapter.start_or_attach(
            task, Attempt("attempt-01", task.task_id, 1, "worker"), "attempt-01"
        )
    assert dispatch.run_id == "run-01"
    assert [request.method for request in requests] == ["GET", "POST"]


def test_verified_screenshot_is_sent_as_one_native_multimodal_user_message():
    requests = []
    image_bytes = b"synthetic-png-bytes"
    digest = sha256(image_bytes).hexdigest()
    image = InputFile(
        "current-preview.png", base64.b64encode(image_bytes).decode(),
        "image/png", "base64", digest,
    )

    def handler(request):
        requests.append(request)
        return httpx.Response(
            202, json={"run_id": "run-vision", "status": "started", "replayed": False}
        )

    with client(handler) as gateway:
        dispatch = gateway.start_or_attach(
            input_text="Improve the group-management experience.", images=(image,),
            session_id="task-vision", dispatch_key="attempt-vision",
        )

    assert dispatch.run_id == "run-vision"
    body = json.loads(requests[0].content)
    assert body["input"] == [{"role": "user", "content": [
        {"type": "text", "text": "Improve the group-management experience."},
        {"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + image.content, "detail": "auto"
        }},
    ]}]


def test_exact_allowed_tools_fail_closed_when_runtime_capability_is_missing():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"features": {
            "runs_idempotency": {"supported": True, "durable": True, "retention_seconds": 86400},
        }})

    task = Task("task-01", "alice", "bot-01", "project-01",
                "Use only read_file.", "nemo-chat", None, 3, allowed_tools=("read_file",))
    with client(handler) as gateway:
        adapter = HermesAgentWorkAdapter(
            gateway, runtime_revision="hermes-exact-tools", clock=lambda: datetime.now(timezone.utc)
        )
        with pytest.raises(HermesGatewayError, match="runtime_exact_tools_restriction_unavailable"):
            adapter.start_or_attach(task, Attempt("attempt-01", task.task_id, 1, "worker"), "attempt-01")
    assert [request.method for request in requests] == ["GET"]


def test_exact_tool_scope_rejects_malformed_direct_callers_before_http():
    def handler(_request):
        raise AssertionError("malformed tool scope must not reach Hermes")

    with client(handler) as gateway:
        with pytest.raises(ValueError, match="invalid_hermes_tool_restriction"):
            gateway.start_or_attach(
                input_text="A bounded task.", session_id="task-01",
                dispatch_key="attempt-01", allowed_tools=(["read_file"],),
            )


@pytest.mark.postgres
def test_started_ack_is_saved_without_unknown_hold_and_completes_by_get(
    service_factory, store, alice, envelope, start, clock,
):
    requests = []
    polls = 0

    def handler(request):
        nonlocal polls
        requests.append(request)
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json={"features": {
                "runs_idempotency": {"supported": True, "durable": True, "retention_seconds": 86400},
                "runs_disable_tools": {"supported": True},
            }})
        if request.method == "POST":
            assert request.url.path == "/v1/runs"
            assert json.loads(request.content)["disable_tools"] is True
            return httpx.Response(202, json={"run_id": "run-started", "status": "started", "replayed": False})
        assert request.method == "GET" and request.url.path == "/v1/runs/run-started"
        polls += 1
        return httpx.Response(200, json={"run_id": "run-started",
            "status": "running" if polls == 1 else "completed",
            **({"output": "The synthetic report."} if polls > 1 else {})})

    with client(handler) as gateway:
        adapter = HermesAgentWorkAdapter(gateway, runtime_revision="hermes-0.21.1", clock=clock)
        service = service_factory(work=adapter)
        task = service.admit(alice, envelope(), replace(start, brief="Use no tools. Summarize the fixture."))
        active = service.run(task.task_id)
        assert active.phase == "active" and active.blockers == ()
        with store.transaction() as tx:
            dispatch = tx.dispatch(active.attempt_id)
            assert dispatch.state == "accepted" and dispatch.run_id == "run-started"
            assert tx.attempt(active.attempt_id).generation == 1
            assert "needs_attention" not in {event.kind for event in tx.events(task.task_id, 0)}
        completed = service.recover(task.task_id)
        assert completed.phase == "closed" and completed.outcome == "completed"
        assert completed.result == "The synthetic report." and completed.blockers == ()
        assert completed.attempt_id == active.attempt_id
        assert completed.budget_remaining == start.budget - 1
        with store.transaction() as tx:
            assert tx.dispatch(active.attempt_id).state == "closed"
            assert "needs_attention" not in {event.kind for event in tx.events(task.task_id, 0)}
    posts = [request for request in requests if request.method == "POST"]
    assert len(posts) == 1 and posts[0].headers["Idempotency-Key"] == active.attempt_id
    assert json.loads(posts[0].content)["session_id"] == task.task_id
    assert polls == 2


def test_capability_preflight_requires_durable_bounded_idempotency():
    response = httpx.Response(200, json={
        "features": {"runs_idempotency": {
            "supported": True, "durable": True, "retention_seconds": 86_400,
        }}
    })
    with client(lambda _request: response) as gateway:
        capabilities = gateway.capabilities()
    assert capabilities.idempotency_retention_seconds == 86_400


@pytest.mark.parametrize("change,supported", [({}, True), ({"max_extra_model_calls": 1}, False),
    ({"max_extra_model_calls": False}, False), ({"checkpoint": "final_response"}, False),
    ({"durable": False}, False), ({"max_receipts": 65}, False), ({"version": True}, False),
    ({"applied_evidence": "queued"}, False)])
def test_guidance_capability_requires_natural_checkpoint_and_no_extra_calls(change, supported):
    capability = {"supported": True, "durable": True, "version": 1, "max_receipts": 64,
                  "checkpoint": "after_tool_batch", "max_extra_model_calls": 0,
                  "applied_evidence": "completed_provider_response", **change}
    with client(lambda _: httpx.Response(200, json={"features": {
        "runs_idempotency": {"supported": True, "durable": True, "retention_seconds": 86400},
        "runs_steering_receipts": capability}})) as gateway:
        assert gateway.capabilities().guidance_receipts is supported


@pytest.mark.parametrize("support", [None, {}, {"supported": False}, {"supported": "true"}, {"supported": True}])
def test_restricted_assignment_requires_capability_before_any_dispatch(support):
    requests = []
    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"features": {
                "runs_idempotency": {"supported": True, "durable": True, "retention_seconds": 86400},
                "runs_disable_tools": support}})
        assert json.loads(request.content)["disable_tools"] is True
        assert request.headers["idempotency-key"] == "attempt-01"
        return httpx.Response(202, json={"run_id": "run-01", "status": "queued", "replayed": False})
    task = Task("task-01", "alice", "bot-01", "project-01", "Use no tools.", "nemo-chat", None, 3, disable_tools=True)
    with client(handler) as gateway:
        adapter = HermesAgentWorkAdapter(gateway, runtime_revision="hermes-restricted", clock=lambda: datetime.now(timezone.utc))
        if support == {"supported": True}:
            assert adapter.start_or_attach(task, Attempt("attempt-01", task.task_id, 1, "worker"), "attempt-01").run_id == "run-01"
            assert [request.method for request in requests] == ["GET", "POST"]
        else:
            with pytest.raises(HermesGatewayError, match="runtime_tools_restriction_unavailable"):
                adapter.start_or_attach(task, Attempt("attempt-01", task.task_id, 1, "worker"), "attempt-01")
            assert [request.method for request in requests] == ["GET"]


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


@pytest.mark.parametrize(("status", "replayed"), [("invented", False), ("started", True)])
def test_admission_does_not_normalize_unknown_or_replayed_started_states(status, replayed):
    response = httpx.Response(202,
        headers={"Idempotency-Replayed": "true"} if replayed else {},
        json={"run_id": "run-01", "status": status, "replayed": replayed})
    with client(lambda _request: response) as gateway, pytest.raises(HermesGatewayError) as caught:
        gateway.start_or_attach(input_text="safe", session_id="session-01", dispatch_key="dispatch-01")
    assert caught.value.code == "runtime_malformed_response"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"run_id": "run-01", "status": "invented"}),
        httpx.Response(200, json={"run_id": "run-01", "status": "started"}),
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
    result = adapter.result(task, dispatch)

    assert dispatch.session_id == task.task_id
    assert dispatch.provider_binding == "nemo-chat"
    assert dispatch.runtime_revision == "hermes-0.21.1"
    assert dispatch.submitted_at == now
    assert int((dispatch.retention_until - now).total_seconds()) == 86_400
    assert result.state == "completed" and result.content == "Cited result"
    assert adapter.stop(task, dispatch)
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
    task = Task(
        "task-01", "alice", "bot-01", "project-01", "Research safely.",
        "nemo-chat", None, 3,
    )
    assert adapter.result(task, dispatch).state == radhouse_state


def test_runtime_router_uses_durable_bot_identity_for_every_operation():
    class Adapter:
        def __init__(self, name):
            self.name = name
            self.calls = []

        def capabilities(self, task):
            self.calls.append(("capabilities", task.bot_id))
            from radhouse.domain.tasks import RuntimeCapabilities
            return RuntimeCapabilities(self.name, 60)

        def start_or_attach(self, task, attempt, dispatch_key):
            self.calls.append(("start", task.bot_id, dispatch_key))
            return "dispatch"

        def result(self, task, dispatch):
            self.calls.append(("result", task.bot_id, dispatch))
            return "result"

        def stop(self, task, dispatch):
            self.calls.append(("stop", task.bot_id, dispatch))
            return True

    alpha, beta = Adapter("alpha"), Adapter("beta")
    router = RoutingAgentWork({"bot-01": alpha, "bot-02": beta})
    task = Task(
        "task-01", "alice", "bot-02", "project-01", "Research safely.",
        "nemo-chat", None, 3,
    )
    attempt = Attempt("attempt-01", task.task_id, 1, "worker")

    assert router.capabilities(task).runtime_revision == "beta"
    assert router.start_or_attach(task, attempt, "dispatch-01") == "dispatch"
    assert router.result(task, "dispatch") == "result"
    assert router.stop(task, "dispatch")
    assert alpha.calls == []
    assert [call[0] for call in beta.calls] == ["capabilities", "start", "result", "stop"]
