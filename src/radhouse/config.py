"""Strict public configuration with private overlay and secret-file references."""
from __future__ import annotations

import ipaddress
from pathlib import Path
import re
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import yaml


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")
_MAX_CONFIG_BYTES = 1024 * 1024
_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(cidr) for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


class ConfigurationError(ValueError):
    """A bounded configuration failure that does not echo file contents."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def _absolute_path(value: str) -> str:
    if not value or not Path(value).is_absolute():
        raise ValueError("path must be absolute")
    return value


def _identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError("invalid identifier")
    return value


class SecretFile(StrictModel):
    path: str

    _path = field_validator("path")(_absolute_path)


class DatabaseConfig(StrictModel):
    dsn: SecretFile
    name: str
    deployment_id: str

    _deployment_id = field_validator("deployment_id")(_identifier)

    @field_validator("name")
    @classmethod
    def database_name(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
            raise ValueError("invalid database name")
        return value


class CoordinatorConfig(StrictModel):
    worker_id: str
    interval_seconds: int = Field(default=5, ge=1, le=300)
    max_tasks_per_cycle: int = Field(default=16, ge=1, le=100)

    _worker_id = field_validator("worker_id")(_identifier)


class WebConfig(StrictModel):
    root: str

    _root = field_validator("root")(_absolute_path)


class LocalAuthConfig(StrictModel):
    type: Literal["local"]
    encryption_key: SecretFile
    expected_origin: str
    cookie_name: str = "radhouse_session"
    secure_cookie: bool = True

    @field_validator("expected_origin")
    @classmethod
    def origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("invalid authentication origin")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("plaintext authentication origin must be loopback")
        return value.rstrip("/")

    @field_validator("cookie_name")
    @classmethod
    def cookie(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
            raise ValueError("invalid cookie name")
        return value


Capability = Literal["text", "tools", "structured_output", "vision"]


class ProviderRequirementsConfig(StrictModel):
    required: tuple[Capability, ...] = ("text",)
    admitted: tuple[Capability, ...] = ("text",)
    minimum_context_tokens: int | None = Field(default=None, ge=1, le=16_777_216)

    @field_validator("required", "admitted", mode="before")
    @classmethod
    def yaml_capabilities(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def valid_capabilities(self) -> "ProviderRequirementsConfig":
        if (
            not self.required
            or "text" not in self.required
            or len(set(self.required)) != len(self.required)
            or len(set(self.admitted)) != len(self.admitted)
            or not set(self.required) <= set(self.admitted)
        ):
            raise ValueError("invalid provider capabilities")
        return self


class ProviderConfig(StrictModel):
    binding: str
    endpoint: str
    model: str
    model_identity: Literal["alias", "catalog_sibling", "radhouse_extension"] = "alias"
    token: SecretFile | None = None
    allow_plaintext_private_network: bool = False
    requirements: ProviderRequirementsConfig = ProviderRequirementsConfig()

    _binding = field_validator("binding")(_identifier)

    @field_validator("model")
    @classmethod
    def model_id(cls, value: str) -> str:
        if _MODEL_ID.fullmatch(value) is None:
            raise ValueError("invalid model identifier")
        return value

    @model_validator(mode="after")
    def secure_endpoint(self) -> "ProviderConfig":
        parsed = urlsplit(self.endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/", "/v1", "/v1/"}
        ):
            raise ValueError("invalid provider endpoint")
        if parsed.scheme == "http":
            try:
                address = ipaddress.ip_address(parsed.hostname)
            except ValueError:
                raise ValueError("plaintext provider endpoint must be an IP address") from None
            if not (
                address.is_loopback
                or self.allow_plaintext_private_network
                and any(address in network for network in _PRIVATE_NETWORKS)
            ):
                raise ValueError("plaintext provider endpoint is not admitted")
        return self


class BotRuntimeConfig(StrictModel):
    bot_id: str
    endpoint: str
    token: SecretFile
    profile: str
    runtime_revision: str
    provider_binding: str
    approval_commands: tuple[str, ...] = ()

    @field_validator("approval_commands", mode="before")
    @classmethod
    def command_list(cls, value):
        return tuple(value) if isinstance(value, list) else value

    @field_validator("approval_commands")
    @classmethod
    def exact_commands(cls, value):
        if len(value) > 32 or any(not item or len(item) > 8192 or "redact" in item.lower() or "***" in item for item in value):
            raise ValueError("invalid approved runtime command")
        return value

    _bot_id = field_validator("bot_id")(_identifier)
    _profile = field_validator("profile")(_identifier)
    _runtime_revision = field_validator("runtime_revision")(_identifier)
    _provider_binding = field_validator("provider_binding")(_identifier)

    @field_validator("endpoint")
    @classmethod
    def secure_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("invalid runtime endpoint")
        if parsed.scheme == "http":
            try:
                if not ipaddress.ip_address(parsed.hostname).is_loopback:
                    raise ValueError("plaintext runtime endpoint must be loopback")
            except ValueError as error:
                raise ValueError("plaintext runtime endpoint must be loopback") from error
        return value.rstrip("/")


class BuzzConversationConfig(StrictModel):
    channel_id: str
    conversation_id: str

    _channel = field_validator("channel_id")(_identifier)
    _conversation = field_validator("conversation_id")(_identifier)


class BuzzConfig(StrictModel):
    relay_origin: str
    relay_pubkey: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    conversations: tuple[BuzzConversationConfig, ...] = Field(min_length=1, max_length=20)
    agents: tuple["BuzzAgentConfig", ...] = Field(default=(), max_length=20)

    _origin = field_validator("relay_origin")(LocalAuthConfig.origin.__func__)

    @field_validator("conversations", "agents", mode="before")
    @classmethod
    def sequences(cls, value):
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def unique(self):
        if len({item.channel_id for item in self.conversations}) != len(self.conversations):
            raise ValueError("duplicate Buzz channel")
        if len({item.link_id for item in self.agents}) != len(self.agents):
            raise ValueError("duplicate Buzz agent link")
        if len(
            {(item.channel_id, item.agent_pubkey) for item in self.agents}
        ) != len(self.agents):
            raise ValueError("duplicate Buzz agent identity in channel")
        for agent in self.agents:
            if agent.owner_pubkey == agent.agent_pubkey:
                raise ValueError("Buzz agent cannot use its owner's identity")
            if not any((agent.channel_id is None or c.channel_id==agent.channel_id)
                       and c.conversation_id==agent.conversation_id for c in self.conversations):
                raise ValueError("Buzz agent needs its exact admitted conversation")
        groups = {}
        for agent in self.agents:
            if agent.channel_id is not None:
                groups.setdefault(agent.channel_id, []).append(agent)
        for group in groups.values():
            if len(group) == 1:
                continue
            scope = {
                (item.conversation_id, item.principal_id, item.owner_pubkey, item.project_id)
                for item in group
            }
            if len(scope) != 1:
                raise ValueError("shared Buzz channel must have one project authority")
            if sum(item.default_in_channel for item in group) != 1:
                raise ValueError("shared Buzz channel needs one default agent")
        return self


class BuzzAgentConfig(StrictModel):
    link_id: str
    channel_id: str | None = None
    conversation_id: str
    principal_id: str
    owner_pubkey: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    agent_pubkey: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    bot_id: str
    project_id: str
    activated_at: int | None = Field(default=None,ge=1)
    binding_revision: int = Field(default=1,ge=1)
    active: bool = True
    default_in_channel: bool = False
    signing_key: SecretFile

    _ids=field_validator("link_id","conversation_id","principal_id","bot_id","project_id")(_identifier)

    @field_validator("channel_id")
    @classmethod
    def optional_channel(cls, value):
        return _identifier(value) if value is not None else None

    def link(self):
        from radhouse.domain.conversations import ConversationLink
        if self.channel_id is None or self.activated_at is None:
            raise ValueError("Buzz agent has not been enrolled")
        values = self.model_dump(exclude={"signing_key", "default_in_channel"})
        return ConversationLink(
            **values,
            member_pubkeys=(),
            default_agent=True,
        )


BuzzConfig.model_rebuild()


class RadhouseConfig(StrictModel):
    schema_version: Literal[1]
    database: DatabaseConfig
    coordinator: CoordinatorConfig
    web: WebConfig
    authentication: LocalAuthConfig | None = None
    buzz: BuzzConfig | None = None
    providers: tuple[ProviderConfig, ...] = Field(min_length=1, max_length=20)
    bots: tuple[BotRuntimeConfig, ...] = Field(min_length=1, max_length=100)

    @field_validator("bots", "providers", mode="before")
    @classmethod
    def yaml_sequence(cls, value: Any) -> Any:
        # Safe YAML represents sequences as lists. Convert that one container
        # deliberately while retaining strict validation for every item.
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def unique_bot_homes(self) -> "RadhouseConfig":
        if self.buzz is not None and (self.authentication is None or not self.authentication.secure_cookie
                or self.authentication.cookie_name != "radhouse_session"
                or not self.authentication.expected_origin.startswith("https://")):
            raise ValueError("Buzz integration requires HTTPS and the bounded native cookie contract")
        bot_ids = [bot.bot_id for bot in self.bots]
        endpoints = [bot.endpoint for bot in self.bots]
        provider_bindings = [provider.binding for provider in self.providers]
        if len(set(bot_ids)) != len(bot_ids):
            raise ValueError("bot IDs must be unique")
        if len(set(endpoints)) != len(endpoints):
            raise ValueError("each bot requires a distinct Hermes home endpoint")
        if len(set(provider_bindings)) != len(provider_bindings):
            raise ValueError("provider bindings must be unique")
        if any(bot.provider_binding not in set(provider_bindings) for bot in self.bots):
            raise ValueError("every bot provider binding must be configured")
        if self.buzz and any(agent.bot_id not in bot_ids for agent in self.buzz.agents):
            raise ValueError("Buzz agent requires its configured bot runtime")
        return self


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as source:
            raw = source.read(_MAX_CONFIG_BYTES + 1)
        if len(raw) > _MAX_CONFIG_BYTES:
            raise ConfigurationError("configuration_too_large")
        value = yaml.safe_load(raw.decode("utf-8"))
    except ConfigurationError:
        raise
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ConfigurationError("configuration_unreadable") from None
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ConfigurationError("configuration_invalid")
    return value


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        merged[key] = (
            _merge(current, value)
            if isinstance(current, dict) and isinstance(value, dict)
            else value
        )
    return merged


def load_config(base_path: str | Path, overlay_path: str | Path | None = None) -> RadhouseConfig:
    value = _read_yaml(Path(base_path))
    if overlay_path is not None:
        value = _merge(value, _read_yaml(Path(overlay_path)))
    try:
        return RadhouseConfig.model_validate(value)
    except (TypeError, ValueError):
        raise ConfigurationError("configuration_invalid") from None
