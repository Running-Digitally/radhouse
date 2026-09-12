"""Read-only capability probes for OpenAI-compatible local model servers."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import re
import time
from urllib.parse import urlsplit

import httpx

from radhouse.application.ports import ProviderPort
from radhouse.domain.tasks import ProviderDescription


MAX_CATALOG_BYTES = 1_048_576
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")
_CAPABILITIES = frozenset({"text", "tools", "structured_output", "vision"})
_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(cidr) for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


@dataclass(frozen=True)
class ProviderRequirements:
    """Capabilities already admitted for one stable provider binding."""

    required_capabilities: frozenset[str] = frozenset({"text"})
    admitted_capabilities: frozenset[str] = frozenset({"text"})
    minimum_context_tokens: int | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.required_capabilities, frozenset)
            or not isinstance(self.admitted_capabilities, frozenset)
            or not self.required_capabilities
            or "text" not in self.required_capabilities
            or not self.required_capabilities <= _CAPABILITIES
            or not self.admitted_capabilities <= _CAPABILITIES
            or not self.required_capabilities <= self.admitted_capabilities
        ):
            raise ValueError("invalid_provider_capabilities")
        if (
            self.minimum_context_tokens is not None
            and (
                isinstance(self.minimum_context_tokens, bool)
                or not 1 <= self.minimum_context_tokens <= 16_777_216
            )
        ):
            raise ValueError("invalid_provider_context_requirement")


class OpenAICompatibleProvider:
    """Describe one stable alias without making a generation request.

    ``admitted_capabilities`` are an operator-owned qualification ceiling. If a
    server publishes a ``capabilities`` list or boolean mapping on the matching
    model entry, the effective set is its intersection with that ceiling. A
    deployment-owned proxy may also publish ``radhouse_model_id`` so the task
    records a physical backing identity while requests keep using the alias.
    """

    def __init__(
        self,
        binding: str,
        endpoint: str,
        requested_model: str,
        requirements: ProviderRequirements,
        *,
        bearer_token: str | None = None,
        allow_plaintext_private_network: bool = False,
        transport: httpx.BaseTransport | None = None,
        connect_timeout: float = 5.0,
        read_timeout: float = 10.0,
        request_deadline: float = 15.0,
    ):
        if _IDENTIFIER.fullmatch(binding) is None:
            raise ValueError("invalid_provider_binding")
        if _MODEL_ID.fullmatch(requested_model) is None:
            raise ValueError("invalid_provider_model")
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/", "/v1", "/v1/"}
        ):
            raise ValueError("invalid_provider_endpoint")
        if parsed.scheme == "http":
            try:
                address = ipaddress.ip_address(parsed.hostname)
                allowed = address.is_loopback or (
                    allow_plaintext_private_network
                    and any(address in network for network in _PRIVATE_NETWORKS)
                )
                if not allowed:
                    raise ValueError("invalid_provider_endpoint")
            except ValueError:
                raise ValueError("invalid_provider_endpoint") from None
        if bearer_token is not None and (
            not bearer_token
            or len(bearer_token) > 4096
            or any(ord(character) <= 0x20 or ord(character) > 0x7e for character in bearer_token)
        ):
            raise ValueError("invalid_provider_bearer")
        if connect_timeout <= 0 or read_timeout <= 0 or request_deadline <= 0:
            raise ValueError("invalid_provider_timeout")

        headers = {"Authorization": f"Bearer {bearer_token}"} if bearer_token else {}
        self.binding = binding
        self.requested_model = requested_model
        self.requirements = requirements
        self._client = httpx.Client(
            base_url=endpoint.rstrip("/") + "/",
            headers=headers,
            timeout=httpx.Timeout(
                connect=connect_timeout,
                read=read_timeout,
                write=read_timeout,
                pool=connect_timeout,
            ),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self._request_deadline = request_deadline

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OpenAICompatibleProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def describe(self, binding: str) -> ProviderDescription:
        if binding != self.binding:
            return ProviderDescription(self.binding, self.requested_model, False, False)
        model = self._matching_model()
        if model is None:
            return ProviderDescription(self.binding, self.requested_model, False, False)

        model_id = model.get("radhouse_model_id", self.requested_model)
        if not isinstance(model_id, str) or _MODEL_ID.fullmatch(model_id) is None:
            return ProviderDescription(self.binding, self.requested_model, True, False)

        effective = self.requirements.admitted_capabilities
        advertised = model.get("capabilities")
        if advertised is not None:
            parsed = _advertised_capabilities(advertised)
            if parsed is None:
                return ProviderDescription(self.binding, model_id, True, False)
            effective = effective & parsed

        compatible = self.requirements.required_capabilities <= effective
        minimum = self.requirements.minimum_context_tokens
        if minimum is not None:
            context = model.get("max_model_len")
            compatible = compatible and (
                not isinstance(context, bool) and isinstance(context, int) and context >= minimum
            )
        return ProviderDescription(self.binding, model_id, True, compatible)

    def _matching_model(self) -> dict | None:
        deadline = time.monotonic() + self._request_deadline
        try:
            with self._client.stream("GET", "models") as response:
                data = bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic() >= deadline:
                        return None
                    data.extend(chunk)
                    if len(data) > MAX_CATALOG_BYTES:
                        return None
                if response.status_code != 200:
                    return None
        except (httpx.TimeoutException, httpx.RequestError):
            return None
        try:
            payload = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            return None
        matches = [
            item for item in payload["data"]
            if isinstance(item, dict) and item.get("id") == self.requested_model
        ]
        return matches[0] if len(matches) == 1 else None


def _advertised_capabilities(value: object) -> frozenset[str] | None:
    if isinstance(value, list):
        if any(not isinstance(item, str) for item in value):
            return None
        capabilities = frozenset(value)
    elif isinstance(value, dict):
        if any(not isinstance(key, str) or not isinstance(enabled, bool)
               for key, enabled in value.items()):
            return None
        if not frozenset(value) <= _CAPABILITIES:
            return None
        capabilities = frozenset(key for key, enabled in value.items() if enabled)
    else:
        return None
    return capabilities if capabilities <= _CAPABILITIES else None


class RoutingProvider:
    """Route provider observation only by the task's stable binding."""

    def __init__(self, providers: dict[str, ProviderPort]):
        if (
            not providers
            or any(_IDENTIFIER.fullmatch(binding) is None for binding in providers)
        ):
            raise ValueError("invalid_provider_routes")
        self.providers = dict(providers)

    def describe(self, binding: str) -> ProviderDescription:
        provider = self.providers.get(binding)
        if provider is None:
            return ProviderDescription(binding, binding, False, False)
        return provider.describe(binding)
