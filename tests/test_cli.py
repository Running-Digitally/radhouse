import json
from pathlib import Path

import pytest

from radhouse.cli import SecretFileError, main, read_secret_file
from tests.test_config import BASE, write


def test_config_check_reads_no_secret_and_emits_bounded_summary(tmp_path: Path, capsys):
    config = write(tmp_path / "config.yaml", BASE)
    assert main(["config-check", "--config", str(config)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "bot_count": 1,
        "database": "radhouse",
        "deployment_id": "example-home",
        "provider_count": 1,
        "result": "valid",
        "schema_version": 1,
    }


def test_migrate_without_apply_does_not_read_owner_secret(tmp_path: Path, capsys):
    config = write(tmp_path / "config.yaml", BASE)
    assert main([
        "migrate", "--config", str(config),
        "--owner-dsn-file", "/does/not/exist", "--runtime-role", "radhouse_runtime",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "apply_required"


def test_preflight_reads_protected_secrets_without_contacting_services(
    tmp_path: Path, capsys,
):
    database = tmp_path / "database-dsn"
    database.write_text(
        "host=unreachable.example dbname=radhouse user=radhouse_runtime",
        encoding="utf-8",
    )
    database.chmod(0o600)
    token = tmp_path / "hermes-token"
    token.write_text("synthetic-control-token", encoding="utf-8")
    token.chmod(0o600)
    contents = BASE.replace(
        "/run/secrets/database-dsn", str(database),
    ).replace("/run/secrets/hermes-token", str(token))
    config = write(tmp_path / "config.yaml", contents)

    assert main(["preflight", "--config", str(config)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "bot_count": 1,
        "database": "radhouse",
        "deployment_id": "example-home",
        "provider_count": 1,
        "result": "offline_ready",
        "schema_version": 1,
    }


def test_secret_reader_accepts_private_regular_single_line(tmp_path: Path):
    secret = tmp_path / "secret"
    secret.write_text("host=database dbname=radhouse\n", encoding="utf-8")
    secret.chmod(0o640)
    assert read_secret_file(secret) == "host=database dbname=radhouse"


@pytest.mark.parametrize("mode", [0o644, 0o666])
def test_secret_reader_rejects_world_read_or_group_world_write(tmp_path: Path, mode: int):
    secret = tmp_path / "secret"
    secret.write_text("sensitive", encoding="utf-8")
    secret.chmod(mode)
    with pytest.raises(SecretFileError, match="secret_file_permissions_too_broad"):
        read_secret_file(secret)


def test_cli_refusal_does_not_echo_invalid_config_content(tmp_path: Path, capsys):
    config = write(tmp_path / "config.yaml", "inline-password: extremely-sensitive-value\n")
    assert main(["config-check", "--config", str(config)]) == 2
    output = capsys.readouterr().out
    assert json.loads(output) == {"code": "configuration_invalid", "result": "refused"}
    assert "extremely-sensitive-value" not in output


def test_secret_reader_does_not_follow_symlinks(tmp_path: Path):
    target = tmp_path / "target"
    target.write_text("sensitive", encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(SecretFileError, match="secret_file_unreadable"):
        read_secret_file(link)
