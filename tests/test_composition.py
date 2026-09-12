from datetime import datetime, timezone
from pathlib import Path

import pytest

from radhouse.composition import compose_controller
from radhouse.config import load_config
from radhouse.domain.tasks import ProviderDescription
from radhouse.secrets import SecretFileError


class Provider:
    def describe(self, binding: str) -> ProviderDescription:
        return ProviderDescription(binding, "synthetic-model")


class Client:
    created = []

    def __init__(self, endpoint: str, token: str):
        self.endpoint = endpoint
        self.token = token
        self.closed = False
        self.created.append(self)

    def close(self):
        self.closed = True


class ProviderClient:
    created = []

    def __init__(
        self, binding, endpoint, requested_model, requirements, *, bearer_token,
        allow_plaintext_private_network,
    ):
        self.binding = binding
        self.endpoint = endpoint
        self.requested_model = requested_model
        self.requirements = requirements
        self.bearer_token = bearer_token
        self.allow_plaintext_private_network = allow_plaintext_private_network
        self.closed = False
        self.created.append(self)

    def describe(self, binding):
        return ProviderDescription(binding, self.requested_model)

    def close(self):
        self.closed = True


def secret(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def configuration(tmp_path: Path, *, second_token: Path | None = None):
    database = secret(
        tmp_path / "database",
        "host=127.0.0.1 dbname=radhouse user=radhouse_runtime",
    )
    first = secret(tmp_path / "first", "first-token")
    second = second_token or secret(tmp_path / "second", "second-token")
    config = tmp_path / "radhouse.yaml"
    config.write_text(f"""\
schema_version: 1
database:
  dsn: {{path: {database}}}
  name: radhouse
  deployment_id: composition-test
coordinator:
  worker_id: coordinator-01
  max_tasks_per_cycle: 7
web:
  root: {tmp_path}/web
providers:
  - binding: local-chat
    endpoint: https://inference.example.invalid/v1
    model: local-chat
    requirements:
      required: [text, tools]
      admitted: [text, tools, structured_output]
      minimum_context_tokens: 8192
bots:
  - bot_id: researcher-001
    endpoint: https://researcher.example.invalid
    token: {{path: {first}}}
    profile: researcher
    runtime_revision: hermes-0.21.1
    provider_binding: local-chat
  - bot_id: reviewer-001
    endpoint: https://reviewer.example.invalid
    token: {{path: {second}}}
    profile: reviewer
    runtime_revision: hermes-0.21.1
    provider_binding: local-chat
""", encoding="utf-8")
    return load_config(config)


def test_composition_builds_routes_without_contacting_external_services(tmp_path: Path):
    Client.created = []
    provider = Provider()
    clock = lambda: datetime(2026, 9, 12, tzinfo=timezone.utc)

    composition = compose_controller(
        configuration(tmp_path),
        provider,
        clock=clock,
        client_factory=Client,
    )

    assert list(composition.work.adapters) == ["researcher-001", "reviewer-001"]
    assert [(item.endpoint, item.token) for item in Client.created] == [
        ("https://researcher.example.invalid", "first-token"),
        ("https://reviewer.example.invalid", "second-token"),
    ]
    assert composition.provider is provider
    assert composition.service.provider is provider
    assert composition.coordinator.worker_id == "coordinator-01"
    assert composition.coordinator.max_tasks_per_cycle == 7
    assert composition.web_root == tmp_path / "web"
    assert all(not item.closed for item in Client.created)

    composition.close()
    composition.close()
    assert all(item.closed for item in Client.created)


def test_partial_composition_closes_created_clients_on_secret_refusal(tmp_path: Path):
    Client.created = []
    missing = tmp_path / "missing-second-token"
    config = configuration(tmp_path, second_token=missing)

    with pytest.raises(SecretFileError, match="secret_file_unreadable"):
        compose_controller(config, Provider(), client_factory=Client)

    assert len(Client.created) == 1
    assert Client.created[0].closed is True


def test_composition_can_build_and_own_configured_provider_routes(tmp_path: Path):
    Client.created = []
    ProviderClient.created = []

    composition = compose_controller(
        configuration(tmp_path),
        client_factory=Client,
        provider_factory=ProviderClient,
    )

    assert len(ProviderClient.created) == 1
    provider = ProviderClient.created[0]
    assert provider.binding == "local-chat"
    assert provider.endpoint == "https://inference.example.invalid/v1"
    assert provider.requested_model == "local-chat"
    assert provider.bearer_token is None
    assert provider.requirements.required_capabilities == frozenset({"text", "tools"})
    assert provider.requirements.minimum_context_tokens == 8192
    assert composition.provider.describe("local-chat").available is True

    composition.close()
    assert provider.closed is True
    assert all(client.closed for client in Client.created)
