import httpx
import pytest

from radhouse.integrations.openai_compatible import (
    MAX_CATALOG_BYTES,
    OpenAICompatibleProvider,
    ProviderRequirements,
    RoutingProvider,
)


def provider(handler, **overrides):
    arguments = {
        "binding": "local-chat",
        "endpoint": "http://127.0.0.1:8000/v1",
        "requested_model": "local-chat",
        "requirements": ProviderRequirements(
            required_capabilities=frozenset({"text", "tools"}),
            admitted_capabilities=frozenset({"text", "tools", "structured_output"}),
            minimum_context_tokens=8192,
        ),
        "model_identity": "radhouse_extension",
        "bearer_token": "provider-secret",
        "transport": httpx.MockTransport(handler),
    }
    arguments.update(overrides)
    return OpenAICompatibleProvider(**arguments)


def test_catalog_probe_is_read_only_bounded_and_uses_the_stable_alias():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{
            "id": "local-chat",
            "max_model_len": 32768,
            "capabilities": ["text", "tools", "structured_output"],
            "radhouse_model_id": "model-revision-a",
        }]})

    with provider(handler) as adapter:
        description = adapter.describe("local-chat")

    assert description.binding == "local-chat"
    assert description.model_id == "model-revision-a"
    assert description.available is True
    assert description.compatible is True
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url == httpx.URL("http://127.0.0.1:8000/v1/models")
    assert requests[0].headers["authorization"] == "Bearer provider-secret"
    assert requests[0].content == b""


def test_physical_identity_can_change_behind_the_same_alias():
    identities = iter(("model-revision-a", "model-revision-b"))

    def handler(_request):
        return httpx.Response(200, json={"data": [{
            "id": "local-chat",
            "max_model_len": 32768,
            "capabilities": {"text": True, "tools": True, "vision": False},
            "radhouse_model_id": next(identities),
        }]})

    with provider(handler) as adapter:
        first = adapter.describe("local-chat")
        second = adapter.describe("local-chat")

    assert first.model_id == "model-revision-a"
    assert second.model_id == "model-revision-b"
    assert first.binding == second.binding == "local-chat"
    assert first.compatible is second.compatible is True


def test_explicit_catalog_sibling_mode_tracks_a_single_physical_model():
    response = {"data": [
        {"id": "local-chat", "max_model_len": 32768},
        {"id": "physical-model-b", "max_model_len": 32768,
         "capabilities": ["text", "tools"]},
    ]}
    with provider(
        lambda _request: httpx.Response(200, json=response),
        model_identity="catalog_sibling",
    ) as adapter:
        description = adapter.describe("local-chat")

    assert description.model_id == "physical-model-b"
    assert description.available is True
    assert description.compatible is True


def test_catalog_sibling_mode_fails_closed_on_ambiguous_physical_identity():
    response = {"data": [
        {"id": "local-chat", "max_model_len": 32768},
        {"id": "physical-a"},
        {"id": "physical-b"},
    ]}
    with provider(
        lambda _request: httpx.Response(200, json=response),
        model_identity="catalog_sibling",
    ) as adapter:
        description = adapter.describe("local-chat")

    assert description.model_id == "local-chat"
    assert description.available is True
    assert description.compatible is False


@pytest.mark.parametrize("payload", [
    {"data": []},
    {"data": [{"id": "other-model"}]},
    {"data": [{"id": "local-chat"}, {"id": "local-chat"}]},
    {"data": "not-a-list"},
])
def test_missing_ambiguous_or_malformed_catalog_is_unavailable(payload):
    with provider(lambda _request: httpx.Response(200, json=payload)) as adapter:
        description = adapter.describe("local-chat")
    assert description.available is False
    assert description.compatible is False


@pytest.mark.parametrize("model", [
    {"id": "local-chat", "max_model_len": 4096,
     "capabilities": ["text", "tools"]},
    {"id": "local-chat", "max_model_len": 32768,
     "capabilities": ["text"]},
    {"id": "local-chat", "max_model_len": 32768,
     "capabilities": ["text", "tools", "invented"]},
    {"id": "local-chat", "max_model_len": 32768,
     "capabilities": ["text", "tools"], "radhouse_model_id": "bad identity space"},
])
def test_missing_required_capability_or_attribution_is_incompatible(model):
    with provider(lambda _request: httpx.Response(200, json={"data": [model]})) as adapter:
        description = adapter.describe("local-chat")
    assert description.available is True
    assert description.compatible is False


@pytest.mark.parametrize("response", [
    httpx.Response(307, headers={"location": "https://other.invalid/v1/models"}),
    httpx.Response(401, text="provider-secret vendor detail"),
    httpx.Response(200, content=b"not-json"),
    httpx.Response(200, content=b"x" * (MAX_CATALOG_BYTES + 1)),
])
def test_transport_and_response_failures_become_bounded_unavailability(response):
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return response

    with provider(handler) as adapter:
        description = adapter.describe("local-chat")
    assert description.available is False
    assert description.compatible is False
    assert calls == 1


def test_network_failure_does_not_expose_vendor_or_credential_text():
    def handler(request):
        raise httpx.ConnectError("provider-secret internal route", request=request)

    with provider(handler) as adapter:
        description = adapter.describe("local-chat")
    assert description.available is False
    assert "provider-secret" not in repr(description)


@pytest.mark.parametrize("endpoint", [
    "ftp://127.0.0.1:8000/v1",
    "http://provider.example/v1",
    "http://user:secret@127.0.0.1:8000/v1",
    "https://provider.example/v1?token=secret",
    "https://provider.example/other",
])
def test_endpoint_defaults_to_tls_or_literal_loopback(endpoint):
    with pytest.raises(ValueError, match="invalid_provider_endpoint"):
        provider(lambda _request: None, endpoint=endpoint)


def test_plaintext_private_network_requires_an_explicit_deployment_choice():
    adapter = provider(
        lambda _request: httpx.Response(200, json={"data": []}),
        endpoint="http://192.168.50.9:8000/v1",
        allow_plaintext_private_network=True,
    )
    adapter.close()


def test_routing_is_exact_and_missing_binding_stays_unavailable():
    adapter = provider(lambda _request: httpx.Response(200, json={"data": [{
        "id": "local-chat", "max_model_len": 32768,
        "capabilities": ["text", "tools"],
    }]}))
    router = RoutingProvider({"local-chat": adapter})
    assert router.describe("local-chat").available is True
    missing = router.describe("other-chat")
    assert missing.binding == "other-chat"
    assert missing.available is False
    adapter.close()
