"""Experimental SPACE management client; not wired into chat or native tools.

The caller must durably save each mutation's key, body and intended owner/run
BEFORE calling, and reconcile uncertain outcomes. This client never retries or
persists credentials. It is not a workspace authority or an execution adapter.
The inspected upstream revision and qualification limits are in
docs/design/space-integration-qualification.md.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import ipaddress
import json
import math
import re
import ssl
import time
from typing import Literal
from urllib.parse import urlsplit

import httpx


MAX_RESPONSE_BYTES = 1_048_576
_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_KINDS = {"create_sandbox", "delete_sandbox", "pause_sandbox", "suspend_sandbox", "wake_sandbox"}
_OPERATION_STATES = {"queued", "running", "succeeded", "failed", "canceled", "expired"}


class SpaceError(RuntimeError):
    """Fixed error code only; no upstream response, token or transport detail."""

    def __init__(self, code: str, *, outcome_unknown: bool = False):
        super().__init__(code)
        self.outcome_unknown = outcome_unknown


def _identifier(value: str, prefix: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(prefix + _UUID, value):
        raise ValueError("invalid_space_identifier")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _origin(endpoint: str) -> str:
    """An operator-configured origin, never one learned from a response."""
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
        valid = (isinstance(endpoint, str) and parsed.scheme in {"https", "http"} and parsed.hostname
                 and parsed.username is None and parsed.password is None
                 and not parsed.query and not parsed.fragment and parsed.path in {"", "/"}
                 and (port is None or port > 0)
                 and not any(c.isspace() or ord(c) < 32 or c == "\\" for c in endpoint))
        if valid and parsed.scheme == "http":
            valid = ipaddress.ip_address(parsed.hostname).is_loopback
    except (TypeError, ValueError, AttributeError):
        valid = False
    if not valid:
        raise ValueError("invalid_space_endpoint")
    return endpoint.rstrip("/")


@dataclass(frozen=True)
class SpacePortSession:
    """Verified HTTP proxy destination and its separate short-lived credential.

    Keep the token in memory; never serialize this object into a journal or
    expose it to Hermes. This receipt does not establish browser readiness.
    """

    sandbox_id: str
    session_id: str
    port: int
    attach_url: str
    expires_at: datetime
    token: str = field(repr=False)

    def authorization(self) -> dict[str, str]:
        if self.expires_at <= datetime.now(timezone.utc):
            raise SpaceError("space_attach_expired")
        return {"Authorization": f"Bearer {self.token}"}


@dataclass(frozen=True)
class SpaceCreateSpec:
    """Pinned, explicit shape for isolated lab creation, requesting deny-all egress.

    Sending policy is not proof of its enforcement. No guest env, credentials,
    file mounts or browser profile are accepted by this initial surface.
    """

    template: str
    vcpu: int
    memory_mib: int
    disk_mib: int

    def __post_init__(self):
        if not isinstance(self.template, str) or not re.fullmatch(
            r"(?!(?:\.|\.\.)@)[A-Za-z0-9._-]{1,255}@sha256:[0-9a-f]{64}", self.template
        ):
            raise ValueError("space_template_digest_required")
        for value in (self.vcpu, self.memory_mib, self.disk_mib):
            if type(value) is not int or not 1 <= value <= 4_294_967_295:
                raise ValueError("invalid_space_resources")

    def payload(self) -> dict:
        return {
            "template": self.template,
            "runtime": "firecracker",
            "resources": {"vcpu": self.vcpu, "memory_mib": self.memory_mib, "disk_mib": self.disk_mib},
            "network_policy": {"version": "v1", "egress": {"default_action": "deny", "allow": [], "deny": []}},
        }


@dataclass(frozen=True)
class SpaceReceipt:
    sandbox_id: str
    operation_id: str
    kind: str

    def __post_init__(self):
        _identifier(self.sandbox_id, "sbx_")
        _identifier(self.operation_id, "op_")
        if self.kind not in _KINDS:
            raise ValueError("invalid_space_operation_kind")


class SpaceClient:
    """Management-only HTTP client. Construction does not make a request."""

    def __init__(self, endpoint: str, bearer_token: str, *,
                 transport: httpx.BaseTransport | None = None,
                 tls_context: ssl.SSLContext | None = None, timeout: float = 10.0):
        endpoint = _origin(endpoint)
        if (not isinstance(bearer_token, str) or not 1 <= len(bearer_token) <= 4096
                or any(not 0x21 <= ord(c) <= 0x7e for c in bearer_token)):
            raise ValueError("invalid_space_bearer")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValueError("invalid_space_timeout")
        if tls_context is not None and (not isinstance(tls_context, ssl.SSLContext)
                or not tls_context.check_hostname or tls_context.verify_mode != ssl.CERT_REQUIRED):
            raise ValueError("invalid_space_tls_context")
        self._timeout = timeout
        self._client = httpx.Client(
            base_url=endpoint.rstrip("/") + "/", transport=transport,
            verify=tls_context if tls_context is not None else True,
            timeout=timeout, follow_redirects=False, trust_env=False,
            headers={"Authorization": f"Bearer {bearer_token}", "Accept": "application/json",
                     "Accept-Encoding": "identity"},
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _request(self, method: str, path: str, *, body=None, key=None, expected_status=None) -> dict:
        mutation = method != "GET"
        headers = {}
        if mutation:
            # Deliberately narrower than upstream's general string: header-safe,
            # caller-owned keys. No random key is ever created inside the client.
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
                raise ValueError("invalid_space_idempotency_key")
            headers["Idempotency-Key"] = key
        started = time.monotonic()
        try:
            with self._client.stream(method, path, json=body, headers=headers) as response:
                if response.status_code != (expected_status if expected_status is not None else (202 if mutation else 200)):
                    raise SpaceError("space_http_error", outcome_unknown=mutation)
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise SpaceError("space_unexpected_encoding", outcome_unknown=mutation)
                raw = bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic() - started > self._timeout:
                        raise SpaceError("space_deadline_exceeded", outcome_unknown=mutation)
                    if len(raw) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise SpaceError("space_response_too_large", outcome_unknown=mutation)
                    raw.extend(chunk)
                if time.monotonic() - started > self._timeout:
                    raise SpaceError("space_deadline_exceeded", outcome_unknown=mutation)
                result = json.loads(raw, object_pairs_hook=_unique_object)
                if not isinstance(result, dict):
                    raise ValueError("not an object")
                return result
        except httpx.HTTPError:
            raise SpaceError("space_transport_error", outcome_unknown=mutation) from None
        except (ValueError, RecursionError):
            raise SpaceError("space_invalid_response", outcome_unknown=mutation) from None

    def _mutation(self, method: str, path: str, kind: str, *, key: str,
                  body=None, sandbox_id: str | None = None) -> SpaceReceipt:
        result = self._request(method, path, body=body, key=key)
        try:
            receipt = SpaceReceipt(result["sandbox_id"], result["operation_id"], kind)
            if sandbox_id is not None and receipt.sandbox_id != sandbox_id:
                raise ValueError("sandbox mismatch")
            return receipt
        except (KeyError, TypeError, ValueError):
            raise SpaceError("space_invalid_receipt", outcome_unknown=True) from None

    def create(self, spec: SpaceCreateSpec, *, key: str) -> SpaceReceipt:
        if not isinstance(spec, SpaceCreateSpec):
            raise ValueError("invalid_space_create_spec")
        return self._mutation("POST", "v1/sandboxes", "create_sandbox", key=key, body=spec.payload())

    def lifecycle(self, sandbox_id: str, action: Literal["pause", "suspend", "wake"], *, key: str) -> SpaceReceipt:
        _identifier(sandbox_id, "sbx_")
        if action not in ("pause", "suspend", "wake"):
            raise ValueError("unsupported_space_action")
        return self._mutation("POST", f"v1/sandboxes/{sandbox_id}:{action}", f"{action}_sandbox",
                              key=key, sandbox_id=sandbox_id)

    def delete(self, sandbox_id: str, *, key: str) -> SpaceReceipt:
        _identifier(sandbox_id, "sbx_")
        return self._mutation("DELETE", f"v1/sandboxes/{sandbox_id}", "delete_sandbox",
                              key=key, sandbox_id=sandbox_id)

    def create_port_session(self, sandbox_id: str, port: int, *, data_plane_origin: str,
                            key: str) -> SpacePortSession:
        """Open one HTTP port session; perform no attachment or automatic retry.

        Upstream may expose the port before returning a session. An invalid or
        lost acknowledgement therefore requires reconciliation, not replay.
        The caller must independently configure the trusted data-plane origin.
        """
        _identifier(sandbox_id, "sbx_")
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("invalid_space_port")
        origin = _origin(data_plane_origin)
        result = self._request("POST", f"v1/sandboxes/{sandbox_id}/port-sessions",
                               body={"port": port, "protocol": "http"}, key=key, expected_status=201)
        try:
            session_id = _identifier(result["id"], "port_")
            if (result["sandbox_id"] != sandbox_id or result["kind"] != "port"
                    or result["state"] not in ("pending", "attaching", "open", "reconnecting")
                    or type(result["target_port"]) is not int or result["target_port"] != port
                    or result["target_protocol"] != "http" or result["scopes"] != ["port:connect"]):
                raise ValueError("session identity or scope mismatch")
            attach = result["attach"]
            path = f"/v1/sessions/{session_id}/proxy"
            if (attach["url"] not in (path, origin + path) or attach.get("events_url") is not None
                    or not isinstance(attach["token_transport"], list)
                    or "authorization_header" not in attach["token_transport"]):
                raise ValueError("invalid attachment destination")
            token = attach["token"]
            if (not isinstance(token, str) or not 1 <= len(token) <= 4096
                    or any(not 0x21 <= ord(c) <= 0x7e for c in token)
                    or f"Bearer {token}" == self._client.headers["Authorization"]):
                raise ValueError("invalid scoped token")
            expiry = datetime.fromisoformat(attach["expires_at"].replace("Z", "+00:00"))
            if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                raise ValueError("invalid expiry")
            return SpacePortSession(sandbox_id, session_id, port, origin + path, expiry, token)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise SpaceError("space_invalid_port_session", outcome_unknown=True) from None

    def revoke_port_session(self, sandbox_id: str, session_id: str, *, key: str) -> None:
        """Revoke one session, with a caller-owned intent key and no retry.

        The pinned upstream revoke endpoint does not deduplicate this key.
        Closing a port session is not removal of the port exposure itself.
        """
        _identifier(sandbox_id, "sbx_")
        _identifier(session_id, "port_")
        result = self._request("DELETE", f"v1/sandboxes/{sandbox_id}/sessions/{session_id}",
                               key=key, expected_status=200)
        if (result.get("id") != session_id or result.get("sandbox_id") != sandbox_id
                or result.get("kind") != "port" or result.get("state") != "revoked"):
            raise SpaceError("space_invalid_session_revocation", outcome_unknown=True)

    def operation_state(self, receipt: SpaceReceipt) -> str:
        """Bind the result to the exact sandbox, operation and mutation kind."""
        result = self._request("GET", f"v1/operations/{receipt.operation_id}")
        state = result.get("state")
        if (result.get("id") != receipt.operation_id or result.get("target_type") != "sandbox"
                or result.get("target_id") != receipt.sandbox_id or result.get("kind") != receipt.kind
                or not isinstance(state, str) or state not in _OPERATION_STATES):
            raise SpaceError("space_invalid_operation")
        return state

    def sandbox_state(self, sandbox_id: str) -> str:
        _identifier(sandbox_id, "sbx_")
        result = self._request("GET", f"v1/sandboxes/{sandbox_id}")
        state = result.get("state")
        # Upstream states are extensible. Retain unknown states as observations;
        # only an explicit running state may pass readiness.
        if (result.get("id") != sandbox_id or not isinstance(state, str)
                or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", state)):
            raise SpaceError("space_invalid_sandbox")
        return state

    def ready(self, receipt: SpaceReceipt) -> bool:
        """One readiness observation, not a poll loop or browser qualification."""
        if receipt.kind not in {"create_sandbox", "wake_sandbox"}:
            raise ValueError("space_readiness_requires_create_or_wake")
        state = self.operation_state(receipt)
        if state in {"failed", "canceled", "expired"}:
            raise SpaceError("space_operation_failed")
        if state != "succeeded" or self.sandbox_state(receipt.sandbox_id) != "running":
            return False
        result = self._request("GET", f"v1/sandboxes/{receipt.sandbox_id}/processes?limit=1")
        if not isinstance(result.get("data"), list):
            raise SpaceError("space_invalid_process_readiness")
        return True
