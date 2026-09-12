"""Bounded client for the pinned Hermes HTTP Runs API.

The caller owns durable task and dispatch records. This client deliberately has
no provider or model parameters: the Hermes bot profile owns its stable provider
binding, such as ``nemo-chat``.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import re
import time
from typing import Literal
from urllib.parse import urlsplit

import httpx

from radhouse.application.ports import AgentWorkPort
from radhouse.domain.tasks import (
    Attempt, RuntimeCapabilities, RuntimeDispatch, RuntimeFailure, RuntimeResult, Task,
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


@dataclass(frozen=True)
class HermesCapabilities:
    idempotency_retention_seconds: int


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
        return HermesCapabilities(idempotency_retention_seconds=retention)

    def start_or_attach(
        self, *, input_text: str, session_id: str, dispatch_key: str
    ) -> HermesDispatch:
        if not input_text or len(input_text.encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError("invalid_hermes_input")
        session_id = _validated_identifier(session_id, "session")
        dispatch_key = _validated_identifier(dispatch_key, "dispatch")
        payload, response_headers = self._request(
            "POST",
            "v1/runs",
            expected_status=202,
            body={"input": input_text, "session_id": session_id},
            headers={"Idempotency-Key": dispatch_key},
        )
        replayed = payload.get("replayed")
        header_replayed = response_headers.get("Idempotency-Replayed") == "true"
        if not isinstance(replayed, bool) or header_replayed != replayed:
            raise HermesGatewayError("runtime_response_mismatch")
        return HermesDispatch(
            run_id=_response_identifier(payload, "run_id"),
            session_id=session_id,
            status=_response_state(payload),
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
        return HermesRun(run_id=run_id, status=_response_state(payload), output=output)

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
        body: dict[str, str] | None = None,
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
    if value not in _STATES:
        raise HermesGatewayError("runtime_malformed_response")
    return value


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
        return RuntimeCapabilities(
            runtime_revision=self.runtime_revision,
            idempotency_retention_seconds=capabilities.idempotency_retention_seconds,
        )

    def start_or_attach(
        self, task: Task, attempt: Attempt, dispatch_key: str
    ) -> RuntimeDispatch:
        capabilities = self.capabilities(task)
        submitted_at = self.clock().astimezone(timezone.utc)
        accepted = self.client.start_or_attach(
            input_text=task.brief,
            session_id=task.task_id,
            dispatch_key=dispatch_key,
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
        if run.status in {"queued", "running", "waiting_for_approval", "stopping"}:
            return RuntimeResult("running")
        if run.status == "completed":
            return RuntimeResult("completed", run.output)
        if run.status == "cancelled":
            return RuntimeResult("cancelled", run.output)
        if run.status == "interrupted":
            return RuntimeResult("unknown")
        return RuntimeResult("failed", run.output)

    def stop(self, _task: Task, dispatch: RuntimeDispatch) -> bool:
        return self.client.stop(dispatch.run_id).status in {
            "stopping", "cancelled", "completed", "failed", "interrupted",
        }


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
