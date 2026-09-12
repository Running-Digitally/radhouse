"""Strict public configuration with private overlay and secret-file references."""
from __future__ import annotations

import ipaddress
from pathlib import Path
import re
from typing import Any, Literal
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


class RadhouseConfig(StrictModel):
    schema_version: Literal[1]
    database: DatabaseConfig
    coordinator: CoordinatorConfig
    web: WebConfig
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
