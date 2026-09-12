"""Offline-safe composition of the implemented controller components.

Construction reads protected local secret files and creates clients, but it
does not open a database connection, contact Hermes, or start an HTTP listener.
Authentication and provider adapters remain explicit trusted inputs.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from radhouse.application.coordinator import Coordinator
from radhouse.application.ports import ProviderPort
from radhouse.application.service import Service
from radhouse.config import RadhouseConfig
from radhouse.integrations.hermes import (
    HermesAgentWorkAdapter,
    HermesRunsClient,
    RoutingAgentWork,
)
from radhouse.integrations.openai_compatible import (
    OpenAICompatibleProvider,
    ProviderRequirements,
    RoutingProvider,
)
from radhouse.secrets import read_secret_file
from radhouse.storage.postgres import ApplicationPostgresStore


@dataclass
class ControllerComposition:
    """The owned components and resources for one controller process."""

    config: RadhouseConfig
    store: ApplicationPostgresStore
    work: RoutingAgentWork
    provider: ProviderPort
    service: Service
    coordinator: Coordinator
    web_root: Path
    _clients: tuple[object, ...]
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        for client in reversed(self._clients):
            client.close()
        self._closed = True

    def __enter__(self) -> "ControllerComposition":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def compose_controller(
    config: RadhouseConfig,
    provider: ProviderPort | None = None,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    client_factory: Callable[..., HermesRunsClient] = HermesRunsClient,
    provider_factory: Callable[..., OpenAICompatibleProvider] = OpenAICompatibleProvider,
) -> ControllerComposition:
    """Build one controller from validated config without contacting a service."""

    database_dsn = read_secret_file(config.database.dsn.path)
    store = ApplicationPostgresStore(
        database_dsn,
        expected_database=config.database.name,
        deployment_id=config.database.deployment_id,
    )
    clients: list[object] = []
    adapters = {}
    try:
        if provider is None:
            providers = {}
            for configured in config.providers:
                token = (
                    read_secret_file(configured.token.path)
                    if configured.token is not None
                    else None
                )
                adapter = provider_factory(
                    configured.binding,
                    configured.endpoint,
                    configured.model,
                    ProviderRequirements(
                        required_capabilities=frozenset(configured.requirements.required),
                        admitted_capabilities=frozenset(configured.requirements.admitted),
                        minimum_context_tokens=configured.requirements.minimum_context_tokens,
                    ),
                    bearer_token=token,
                    allow_plaintext_private_network=(
                        configured.allow_plaintext_private_network
                    ),
                )
                clients.append(adapter)
                providers[configured.binding] = adapter
            provider = RoutingProvider(providers)
        for bot in config.bots:
            token = read_secret_file(bot.token.path)
            client = client_factory(bot.endpoint, token)
            clients.append(client)
            adapters[bot.bot_id] = HermesAgentWorkAdapter(
                client,
                runtime_revision=bot.runtime_revision,
                clock=clock,
            )
        work = RoutingAgentWork(adapters)
        service = Service(store, work, provider, clock)
        coordinator = Coordinator(
            service,
            config.coordinator.worker_id,
            max_tasks_per_cycle=config.coordinator.max_tasks_per_cycle,
        )
        return ControllerComposition(
            config,
            store,
            work,
            provider,
            service,
            coordinator,
            Path(config.web.root),
            tuple(clients),
        )
    except Exception:
        for client in reversed(clients):
            client.close()
        raise
