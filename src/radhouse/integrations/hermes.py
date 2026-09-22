"""Bounded client for the pinned Hermes HTTP Runs API.

The caller owns durable task and dispatch records. This client deliberately has
no provider or model parameters: the Hermes bot profile owns its stable provider
binding, such as ``nemo-chat``.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import ipaddress
import hashlib
import json
import math
import re
import time
from typing import Literal
from urllib.parse import urlsplit

import httpx

from radhouse.application.ports import AgentWorkPort
from radhouse.domain.tasks import (
    Attempt, InputFile, Rejected, RuntimeActivity, RuntimeCapabilities, RuntimeDispatch, RuntimeFailure, RuntimeGuidanceReceipt, RuntimeResult, Task,
    runtime_images, runtime_input,
)


MAX_INPUT_BYTES = 262_144
MAX_RESPONSE_BYTES = 1_048_576
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}")
HermesState = Literal[
    "queued", "running", "waiting_for_approval", "stopping",
    "completed", "failed", "cancelled", "interrupted",
]
_STATES = {
    "queued", "running", "waiting_for_approval", "stopping",
    "completed", "failed", "cancelled", "interrupted",
}
_ACTIVITY_LABELS = {
    "tool.started": "Using an assigned tool",
    "tool.completed": "Completed a tool step and preparing the next step",
    "reasoning.available": "Developing the next step",
    "subagent.start": "Delegating a bounded subtask",
    "subagent.complete": "Reviewing a delegated result",
    "run.steered": "Applying your guidance",
    "approval.responded": "Continuing after your decision",
    "run.stopping": "Stopping the active work",
}


class HermesGatewayError(RuntimeFailure):
    """A sanitized failure code; vendor bodies and credentials are discarded."""

    def __init__(self, code: str):
        super().__init__(code)


@dataclass(frozen=True)
class HermesDispatch:
    run_id: str
    session_id: str
    status: HermesState
    replayed: bool


@dataclass(frozen=True)
class HermesRun:
    run_id: str
    status: HermesState
    output: str | None = None
    permission_request: dict | None = None
    guidance_receipts: tuple[RuntimeGuidanceReceipt, ...] | None = None
    activity: RuntimeActivity | None = None


@dataclass(frozen=True)
class HermesCapabilities:
    idempotency_retention_seconds: int
    disable_tools: bool = False
    allowed_tools: bool = False
    guidance_receipts: bool = False


class HermesRunsClient:
    """Synchronous transport for one authenticated Hermes gateway."""

    def __init__(
        self,
        endpoint: str,
        bearer_token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        connect_timeout: float = 5.0,
        read_timeout: float = 30.0,
        request_deadline: float = 40.0,
    ):
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("invalid_hermes_endpoint")
        if parsed.scheme == "http":
            try:
                if not ipaddress.ip_address(parsed.hostname).is_loopback:
                    raise ValueError("invalid_hermes_endpoint")
            except ValueError:
                raise ValueError("invalid_hermes_endpoint") from None
        if (
            not bearer_token
            or len(bearer_token) > 4096
            or any(ord(character) <= 0x20 or ord(character) > 0x7e for character in bearer_token)
        ):
            raise ValueError("invalid_hermes_bearer")
        if connect_timeout <= 0 or read_timeout <= 0 or request_deadline <= 0:
            raise ValueError("invalid_hermes_timeout")

        timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=read_timeout,
            pool=connect_timeout,
        )
        self._client = httpx.Client(
            base_url=endpoint.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {bearer_token}"},
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self._request_deadline = request_deadline

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HermesRunsClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def capabilities(self) -> HermesCapabilities:
        payload, _ = self._request("GET", "v1/capabilities", expected_status=200)
        features = payload.get("features")
        idempotency = features.get("runs_idempotency") if isinstance(features, dict) else None
        retention = idempotency.get("retention_seconds") if isinstance(idempotency, dict) else None
        if (
            not isinstance(idempotency, dict)
            or idempotency.get("supported") is not True
            or idempotency.get("durable") is not True
            or isinstance(retention, bool)
            or not isinstance(retention, int)
            or not 1 <= retention <= 31 * 24 * 60 * 60
        ):
            raise HermesGatewayError("runtime_idempotency_unavailable")
        restriction = features.get("runs_disable_tools")
        allowed = features.get("runs_allowed_tools")
        steering = features.get("runs_steering_receipts")
        identified_steering = (isinstance(steering, dict)
            and steering.get("supported") is True and steering.get("durable") is True
            and type(steering.get("version")) is int and steering["version"] == 1
            and type(steering.get("max_receipts")) is int and 1 <= steering["max_receipts"] <= 64
            and steering.get("checkpoint") == "after_tool_batch"
            and type(steering.get("max_extra_model_calls")) is int
            and steering["max_extra_model_calls"] == 0
            and steering.get("applied_evidence") == "completed_provider_response")
        return HermesCapabilities(idempotency_retention_seconds=retention,
            disable_tools=isinstance(restriction, dict) and restriction.get("supported") is True,
            allowed_tools=(isinstance(allowed, dict) and allowed.get("supported") is True
                and type(allowed.get("version")) is int and allowed.get("version") == 1
                and allowed.get("durable") is True
                and allowed.get("mode") == "exact_subset_of_profile" and allowed.get("max_names") == 32),
            guidance_receipts=identified_steering)

    def start_or_attach(
        self, *, input_text: str, session_id: str, dispatch_key: str, disable_tools: bool = False,
        allowed_tools: tuple[str, ...] = (), images: tuple[InputFile, ...] = (),
    ) -> HermesDispatch:
        if not input_text or len(input_text.encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError("invalid_hermes_input")
        if (type(allowed_tools) is not tuple or len(allowed_tools) > 32
                or any(type(value) is not str for value in allowed_tools)
                or len(set(allowed_tools)) != len(allowed_tools)
                or any(re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is None for value in allowed_tools)
                or disable_tools and allowed_tools):
            raise ValueError("invalid_hermes_tool_restriction")
        if (type(images) is not tuple or len(images) > 4
                or any(not isinstance(image, InputFile) or not image.is_image or image.encoding != "base64"
                       for image in images)):
            raise ValueError("invalid_hermes_images")
        try:
            image_bytes = tuple(image.bytes() for image in images)
        except Rejected:
            raise ValueError("invalid_hermes_images") from None
        if (sum(map(len, image_bytes)) > 8 * 1024 * 1024
                or any(len(data) > 4 * 1024 * 1024 for data in image_bytes)
                or any(image.sha256 != hashlib.sha256(data).hexdigest()
                       for image, data in zip(images, image_bytes))):
            raise ValueError("invalid_hermes_images")
        session_id = _validated_identifier(session_id, "session")
        dispatch_key = _validated_identifier(dispatch_key, "dispatch")
        payload, response_headers = self._request(
            "POST",
            "v1/runs",
            expected_status=202,
            body={"input": (
                    [{"role": "user", "content": [
                        {"type": "text", "text": input_text},
                        *[{"type": "image_url", "image_url": {
                            "url": f"data:{image.media_type};base64,{image.content}", "detail": "auto"
                        }} for image in images],
                    ]}] if images else input_text
                ), "session_id": session_id,
                  **({"disable_tools": True} if disable_tools else {}),
                  **({"allowed_tools": list(allowed_tools)} if allowed_tools else {})},
            headers={"Idempotency-Key": dispatch_key},
        )
        replayed = payload.get("replayed")
        header_replayed = response_headers.get("Idempotency-Replayed") == "true"
        if not isinstance(replayed, bool) or header_replayed != replayed:
            raise HermesGatewayError("runtime_response_mismatch")
        # The pinned gateway acknowledges a fresh dispatch as "started" before
        # its durable queued/running status is polled. This is admission only.
        status = "queued" if not replayed and payload.get("status") == "started" else _response_state(payload)
        return HermesDispatch(
            run_id=_response_identifier(payload, "run_id"),
            session_id=session_id,
            status=status,
            replayed=replayed,
        )

    def status(self, run_id: str) -> HermesRun:
        run_id = _validated_identifier(run_id, "run")
        payload, _ = self._request("GET", f"v1/runs/{run_id}", expected_status=200)
        if _response_identifier(payload, "run_id") != run_id:
            raise HermesGatewayError("runtime_response_mismatch")
        output = payload.get("output")
        if output is not None and not isinstance(output, str):
            raise HermesGatewayError("runtime_malformed_response")
        permission = None
        if payload.get("status") == "waiting_for_approval":
            value = payload.get("approval")
            if not isinstance(value, dict):
                raise HermesGatewayError("runtime_malformed_response")
            request_id = _response_identifier(value, "request_id")
            command = value.get("command")
            if not isinstance(command, str) or not command or len(command.encode()) > 8192:
                raise HermesGatewayError("runtime_malformed_response")
            permission = {"request_id": request_id, "command": command, "run_id": run_id}
        receipts = None
        if "guidance_receipts" in payload:
            values = payload["guidance_receipts"]
            if not isinstance(values, list) or len(values) > 64:
                raise HermesGatewayError("runtime_malformed_guidance")
            receipts = tuple(_guidance_receipt(value, run_id) for value in values)
            if len({receipt.control_id for receipt in receipts}) != len(receipts):
                raise HermesGatewayError("runtime_malformed_guidance")
        status = _response_state(payload)
        event = payload.get("last_event")
        updated_at = payload.get("updated_at")
        created_at = payload.get("created_at")
        if event is not None and not isinstance(event, str):
            raise HermesGatewayError("runtime_malformed_response")
        if (
            any(isinstance(value, bool) for value in (updated_at, created_at))
            or any(
                value is not None and not isinstance(value, (int, float))
                for value in (updated_at, created_at)
            )
        ):
            raise HermesGatewayError("runtime_malformed_response")
        label = _ACTIVITY_LABELS.get(event or "")
        if label is None:
            label = {
                "queued": "Waiting to start",
                "running": "Working on the assignment",
                "waiting_for_approval": "Waiting for your permission decision",
                "stopping": "Stopping the active work",
                "completed": "Completed the assignment",
                "failed": "The runtime reported a failure",
                "cancelled": "The work was cancelled",
                "interrupted": "The runtime was interrupted",
            }[status]
            event = status
        timestamp = next(
            (
                value for value in (updated_at, created_at)
                if value is not None
                and math.isfinite(value)
                and 0 < value < 4_102_444_800
            ),
            0,
        )
        return HermesRun(
            run_id=run_id,
            status=status,
            output=output,
            permission_request=permission,
            guidance_receipts=receipts,
            activity=RuntimeActivity(run_id, event, label, int(timestamp)),
        )

    def steer(self, run_id: str, text: str, *, control_id: str | None = None) -> bool | RuntimeGuidanceReceipt:
        run_id = _validated_identifier(run_id, "run")
        if not text.strip() or len(text) > 4096:
            raise ValueError("invalid_guidance")
        if control_id is not None and re.fullmatch(r"control:[a-f0-9]{64}", control_id) is None:
            raise ValueError("invalid_guidance_identity")
        payload, _ = self._request("POST", f"v1/runs/{run_id}/steer", expected_status=200,
                                  body={"input": text, **({"control_id": control_id} if control_id is not None else {})})
        if control_id is not None:
            if payload.get("object") != "hermes.run.steer" or type(payload.get("replayed")) is not bool:
                raise HermesGatewayError("runtime_malformed_guidance")
            receipt = _guidance_receipt(payload, run_id)
            if receipt.control_id != control_id or receipt.input_sha256 != hashlib.sha256(text.encode()).hexdigest():
                raise HermesGatewayError("runtime_guidance_identity_mismatch")
            return receipt
        if payload.get("run_id") != run_id or payload.get("accepted") is not True:
            raise HermesGatewayError("runtime_response_mismatch")
        return True

    def approve(self, run_id: str, request_id: str, choice: str) -> bool:
        run_id = _validated_identifier(run_id, "run")
        request_id = _validated_identifier(request_id, "approval")
        if choice not in {"once", "deny"}:
            raise ValueError("invalid_approval_choice")
        payload, _ = self._request("POST", f"v1/runs/{run_id}/approval", expected_status=200,
                                   body={"request_id": request_id, "choice": choice})
        if (payload.get("run_id") != run_id or payload.get("request_id") != request_id
                or payload.get("choice") != choice or type(payload.get("resolved")) is not int
                or payload["resolved"] != 1):
            raise HermesGatewayError("runtime_response_mismatch")
        return True

    def stop(self, run_id: str) -> HermesRun:
        run_id = _validated_identifier(run_id, "run")
        payload, _ = self._request(
            "POST", f"v1/runs/{run_id}/stop", expected_status=200, body={}
        )
        if _response_identifier(payload, "run_id") != run_id:
            raise HermesGatewayError("runtime_response_mismatch")
        return HermesRun(run_id=run_id, status=_response_state(payload))

    def _request(
        self,
        method: str,
        path: str,
        *,
        expected_status: int,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[dict, httpx.Headers]:
        deadline = time.monotonic() + self._request_deadline
        try:
            with self._client.stream(method, path, json=body, headers=headers) as response:
                data = bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic() >= deadline:
                        raise HermesGatewayError("runtime_timeout")
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE_BYTES:
                        raise HermesGatewayError("runtime_response_too_large")
                if response.status_code != expected_status:
                    raise HermesGatewayError(_status_code(response.status_code, path))
        except HermesGatewayError:
            raise
        except httpx.TimeoutException:
            raise HermesGatewayError("runtime_timeout") from None
        except httpx.RequestError:
            raise HermesGatewayError("runtime_unavailable") from None

        try:
            payload = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HermesGatewayError("runtime_malformed_response") from None
        if not isinstance(payload, dict):
            raise HermesGatewayError("runtime_malformed_response")
        return payload, response.headers


def _validated_identifier(value: str, kind: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"invalid_hermes_{kind}_id")
    return value


def _response_identifier(payload: dict, name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise HermesGatewayError("runtime_malformed_response")
    return value


def _response_state(payload: dict) -> HermesState:
    value = payload.get("status")
    if not isinstance(value, str) or value not in _STATES:
        raise HermesGatewayError("runtime_malformed_response")
    return value


def _guidance_receipt(value: object, run_id: str) -> RuntimeGuidanceReceipt:
    if not isinstance(value, dict):
        raise HermesGatewayError("runtime_malformed_guidance")
    if (value.get("run_id") != run_id
            or not isinstance(value.get("control_id"), str)
            or re.fullmatch(r"control:[a-f0-9]{64}", value["control_id"]) is None
            or not isinstance(value.get("input_sha256"), str)
            or re.fullmatch(r"[a-f0-9]{64}", value["input_sha256"]) is None
            or type(value.get("accepted")) is not bool
            or not isinstance(value.get("state"), str)
            or value["state"] not in {"accepted", "applied", "too_late", "not_applied", "unknown"}
            or type(value.get("revision")) is not int or not 1 <= value["revision"] <= 1000000
            or (value["state"] == "too_late") == value["accepted"]):
        raise HermesGatewayError("runtime_malformed_guidance")
    reason = value.get("reason")
    if reason is not None and (not isinstance(reason, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,79}", reason) is None):
        raise HermesGatewayError("runtime_malformed_guidance")
    for field in ("checkpoint_id", "api_request_id"):
        item = value.get(field)
        if item is not None and (not isinstance(item, str) or _IDENTIFIER.fullmatch(item) is None):
            raise HermesGatewayError("runtime_malformed_guidance")
    if value["state"] == "applied" and (value.get("checkpoint_id") is None or value.get("api_request_id") is None):
        raise HermesGatewayError("runtime_malformed_guidance")
    return RuntimeGuidanceReceipt(run_id, value["control_id"], value["input_sha256"],
        value["accepted"], value["state"], value["revision"], reason,
        value.get("checkpoint_id"), value.get("api_request_id"))


def _status_code(status: int, path: str) -> str:
    if status in {401, 403}:
        return "runtime_authentication_failed"
    if status == 400:
        return "runtime_request_rejected"
    if status == 404:
        return "runtime_run_missing"
    if status == 409 and path == "v1/runs":
        return "runtime_dispatch_conflict"
    if status == 409:
        return "runtime_conflict"
    if status == 429:
        return "runtime_capacity_limited"
    return "runtime_unexpected_status"


class HermesAgentWorkAdapter:
    """Translate the pinned wire API into Radhouse's agent-work contract."""

    def __init__(
        self,
        client: HermesRunsClient,
        *,
        runtime_revision: str,
        clock=lambda: datetime.now(timezone.utc),
    ):
        if _IDENTIFIER.fullmatch(runtime_revision) is None:
            raise ValueError("invalid_hermes_runtime_revision")
        self.client = client
        self.runtime_revision = runtime_revision
        self.clock = clock

    def capabilities(self, _task: Task) -> RuntimeCapabilities:
        capabilities = self.client.capabilities()
        if _task.disable_tools and not capabilities.disable_tools:
            raise HermesGatewayError("runtime_tools_restriction_unavailable")
        if _task.allowed_tools and not capabilities.allowed_tools:
            raise HermesGatewayError("runtime_exact_tools_restriction_unavailable")
        return RuntimeCapabilities(
            runtime_revision=self.runtime_revision,
            idempotency_retention_seconds=capabilities.idempotency_retention_seconds,
            guidance_receipts=capabilities.guidance_receipts,
        )

    def start_or_attach(
        self, task: Task, attempt: Attempt, dispatch_key: str
    ) -> RuntimeDispatch:
        capabilities = self.capabilities(task)
        submitted_at = self.clock().astimezone(timezone.utc)
        accepted = self.client.start_or_attach(
            input_text=runtime_input(task),
            session_id=task.task_id,
            dispatch_key=dispatch_key,
            **({"images": runtime_images(task)} if runtime_images(task) else {}),
            **({"disable_tools": True} if task.disable_tools else {}),
            **({"allowed_tools": task.allowed_tools} if task.allowed_tools else {}),
        )
        return RuntimeDispatch(
            run_id=accepted.run_id,
            session_id=accepted.session_id,
            provider_binding=task.provider_binding,
            runtime_revision=capabilities.runtime_revision,
            submitted_at=submitted_at,
            retention_until=submitted_at + timedelta(
                seconds=capabilities.idempotency_retention_seconds
            ),
        )

    def result(self, _task: Task, dispatch: RuntimeDispatch) -> RuntimeResult:
        run = self.client.status(dispatch.run_id)
        if any(item.get("protocol") == "hermes-guidance-v1" and item.get("run_id") == dispatch.run_id
               for item in _task.guidance) and run.guidance_receipts is None:
            raise HermesGatewayError("runtime_guidance_receipts_unavailable")
        receipts = run.guidance_receipts
        if run.status in {"queued", "running", "waiting_for_approval", "stopping"}:
            return RuntimeResult(
                "running",
                permission_request=run.permission_request,
                guidance_receipts=receipts,
                activity=run.activity,
            )
        if run.status == "completed":
            return RuntimeResult(
                "completed", run.output, guidance_receipts=receipts, activity=run.activity
            )
        if run.status == "cancelled":
            return RuntimeResult(
                "cancelled", run.output, guidance_receipts=receipts, activity=run.activity
            )
        if run.status == "interrupted":
            return RuntimeResult(
                "unknown",
                guidance_receipts=receipts,
                guidance_terminal=True,
                activity=run.activity,
            )
        return RuntimeResult(
            "failed", run.output, guidance_receipts=receipts, activity=run.activity
        )

    def stop(self, _task: Task, dispatch: RuntimeDispatch) -> bool:
        return self.client.stop(dispatch.run_id).status in {
            "stopping", "cancelled", "completed", "failed", "interrupted",
        }

    def steer(self, _task: Task, dispatch: RuntimeDispatch, text: str, *, control_id: str) -> RuntimeGuidanceReceipt:
        receipt = self.client.steer(dispatch.run_id, text, control_id=control_id)
        if not isinstance(receipt, RuntimeGuidanceReceipt):
            raise HermesGatewayError("runtime_malformed_guidance")
        return receipt

    def approve(self, _task: Task, dispatch: RuntimeDispatch, request_id: str, choice: str) -> bool:
        return self.client.approve(dispatch.run_id, request_id, choice)


class RoutingAgentWork:
    """Route every runtime operation by the task's durable bot identity."""

    def __init__(self, adapters: dict[str, AgentWorkPort]):
        if not adapters or any(_IDENTIFIER.fullmatch(key) is None for key in adapters):
            raise ValueError("invalid_bot_runtime_routes")
        self.adapters = dict(adapters)

    def _adapter(self, task: Task) -> AgentWorkPort:
        try:
            return self.adapters[task.bot_id]
        except KeyError:
            raise RuntimeFailure("runtime_not_configured") from None

    def capabilities(self, task: Task) -> RuntimeCapabilities:
        return self._adapter(task).capabilities(task)

    def start_or_attach(
        self, task: Task, attempt: Attempt, dispatch_key: str,
    ) -> RuntimeDispatch:
        return self._adapter(task).start_or_attach(task, attempt, dispatch_key)

    def result(self, task: Task, dispatch: RuntimeDispatch) -> RuntimeResult:
        return self._adapter(task).result(task, dispatch)

    def stop(self, task: Task, dispatch: RuntimeDispatch) -> bool:
        return self._adapter(task).stop(task, dispatch)

    def steer(self, task: Task, dispatch: RuntimeDispatch, text: str, *, control_id: str) -> RuntimeGuidanceReceipt:
        return self._adapter(task).steer(task, dispatch, text, control_id=control_id)

    def approve(self, task: Task, dispatch: RuntimeDispatch, request_id: str, choice: str) -> bool:
        return self._adapter(task).approve(task, dispatch, request_id, choice)
