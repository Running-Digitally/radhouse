from pathlib import Path

import pytest

from radhouse.config import ConfigurationError, load_config


BASE = """\
schema_version: 1
database:
  dsn: {path: /run/secrets/database-dsn}
  deployment_id: example-home
coordinator:
  worker_id: controller-01
web:
  root: /opt/radhouse/web
bots:
  - bot_id: researcher-001
    endpoint: https://agent.example.invalid
    token: {path: /run/secrets/hermes-token}
    profile: researcher
    provider_binding: local-chat
"""


def write(path: Path, content: str = BASE) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_public_base_and_private_overlay_produce_one_validated_config(tmp_path: Path):
    base = write(tmp_path / "base.yaml")
    overlay = write(tmp_path / "private.yaml", """\
coordinator:
  interval_seconds: 12
bots:
  - bot_id: researcher-001
    endpoint: https://researcher.private.example
    token: {path: /run/secrets/private-hermes-token}
    profile: researcher
    provider_binding: nemo-chat
""")

    config = load_config(base, overlay)

    assert config.coordinator.worker_id == "controller-01"
    assert config.coordinator.interval_seconds == 12
    assert config.bots[0].provider_binding == "nemo-chat"
    assert config.bots[0].token.path == "/run/secrets/private-hermes-token"


@pytest.mark.parametrize("endpoint", [
    "http://agent.example.invalid",
    "http://localhost:8080",
    "https://user:password@agent.example.invalid",
    "https://agent.example.invalid?token=secret",
])
def test_runtime_endpoint_rejects_plaintext_remote_or_embedded_secrets(
    tmp_path: Path, endpoint: str,
):
    config = BASE.replace("https://agent.example.invalid", endpoint)
    with pytest.raises(ConfigurationError, match="configuration_invalid"):
        load_config(write(tmp_path / "config.yaml", config))


def test_literal_loopback_http_is_allowed_for_a_managed_local_tunnel(tmp_path: Path):
    config = load_config(write(
        tmp_path / "config.yaml",
        BASE.replace("https://agent.example.invalid", "http://127.0.0.1:8080"),
    ))
    assert config.bots[0].endpoint == "http://127.0.0.1:8080"


@pytest.mark.parametrize("change", [
    "inline-password: forbidden",
    "unknown-setting: true",
])
def test_unknown_or_inline_secret_fields_fail_closed(tmp_path: Path, change: str):
    config = BASE.replace("  deployment_id: example-home", f"  deployment_id: example-home\n  {change}")
    with pytest.raises(ConfigurationError, match="configuration_invalid"):
        load_config(write(tmp_path / "config.yaml", config))


def test_unsafe_yaml_tags_are_never_constructed(tmp_path: Path):
    with pytest.raises(ConfigurationError, match="configuration_unreadable"):
        load_config(write(
            tmp_path / "config.yaml",
            "!!python/object/apply:os.system ['echo forbidden']\n",
        ))


def test_configuration_size_is_bounded_before_yaml_parsing(tmp_path: Path):
    path = write(tmp_path / "config.yaml", "x" * (1024 * 1024 + 1))
    with pytest.raises(ConfigurationError, match="configuration_too_large"):
        load_config(path)


def test_duplicate_bot_identity_or_hermes_home_is_rejected(tmp_path: Path):
    duplicate = BASE + """\
  - bot_id: reviewer-001
    endpoint: https://agent.example.invalid
    token: {path: /run/secrets/reviewer-token}
    profile: reviewer
    provider_binding: local-chat
"""
    with pytest.raises(ConfigurationError, match="configuration_invalid"):
        load_config(write(tmp_path / "config.yaml", duplicate))
