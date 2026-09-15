from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from deploy.production.radhouse_vm import (
    CONTROL_UNITS,
    DeploymentError,
    DeploymentManager,
    Paths,
)


OLD = "1" * 40
NEW = "2" * 40


class FakeRunner:
    def __init__(self, *, head: str = NEW, fail_first_start: bool = False):
        self.head = head
        self.fail_first_start = fail_first_start
        self.commands: list[tuple[str, ...]] = []
        self.tracked: tuple[str, ...] = ()

    def which(self, command: str) -> str | None:
        return f"/usr/bin/{command}"

    def run(self, command, *, cwd=None, capture=False):
        command = tuple(str(value) for value in command)
        self.commands.append(command)
        if command == ("python3.14", "--version"):
            return "Python 3.14.4"
        if command[0] == "git" and "rev-parse" in command:
            return self.head
        if command[0] == "git" and "status" in command:
            return ""
        if command[0] == "git" and "ls-files" in command:
            return "\0".join(self.tracked) + "\0"
        if command[:4] == ("uv", "sync", "--frozen", "--no-dev"):
            executable = Path(cwd) / ".venv/bin"
            executable.mkdir(parents=True)
            (executable / "radhouse").write_text("#!/bin/sh\n", encoding="utf-8")
            (executable / "radhouse").chmod(0o750)
            (executable / "python").write_text("", encoding="utf-8")
            return ""
        if command and command[0].endswith("/.venv/bin/python"):
            return "4"
        if command[:2] == ("npm", "--prefix") and command[-1] == "build":
            output = Path(cwd) / "web/dist"
            output.mkdir(parents=True)
            (output / "main.js").write_text("export {};\n", encoding="utf-8")
            return ""
        if command[:2] == ("systemctl", "start") and self.fail_first_start:
            self.fail_first_start = False
            raise subprocess.CalledProcessError(1, command)
        if command[:3] == ("systemctl", "is-active", "--quiet"):
            return ""
        if command[:2] == ("systemctl", "is-active"):
            return "active"
        return ""


def source_tree(tmp_path: Path, runner: FakeRunner) -> Path:
    source = tmp_path / "source"
    files = {
        "pyproject.toml": "[project]\nname='radhouse'\n",
        "uv.lock": "version = 1\n",
        "web/package-lock.json": "{}\n",
        "deploy/production/compose.postgres.yaml": "services: {}\n",
        "deploy/production/config.example.yaml": "schema_version: 1\n",
        "deploy/production/radhouse-api.service": "[Service]\n",
        "deploy/production/radhouse-coordinator.service": "[Service]\n",
        "deploy/production/radhouse-coordinator.timer": "[Timer]\n",
        "deploy/production/radhouse-hermes-tunnel.service": "[Service]\n",
    }
    for name, contents in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    runner.tracked = tuple(files)
    return source


def manager(tmp_path: Path, runner: FakeRunner, monkeypatch) -> DeploymentManager:
    paths = Paths(
        application=tmp_path / "opt/radhouse",
        configuration=tmp_path / "etc/radhouse",
        state=tmp_path / "srv/radhouse",
        systemd=tmp_path / "systemd",
    )
    paths.systemd.mkdir()
    result = DeploymentManager(paths, runner)
    monkeypatch.setattr(result, "_require_root", lambda: None)
    monkeypatch.setattr(result, "_ensure_system_users", lambda: None)
    monkeypatch.setattr(result, "_protect_release", lambda _release: None)
    monkeypatch.setattr("deploy.production.radhouse_vm.shutil.chown", lambda *_args, **_kwargs: None)
    return result


def existing_release(deployment: DeploymentManager, release_id: str, schema: int) -> Path:
    release = deployment.paths.releases / release_id
    release.mkdir(parents=True)
    (release / "radhouse-release.json").write_text(json.dumps({
        "release_id": release_id,
        "source_sha256": "a" * 64,
        "storage_schema_version": schema,
        "installed_at": "2026-09-15T00:00:00+00:00",
    }), encoding="utf-8")
    executable = release / ".venv/bin"
    executable.mkdir(parents=True)
    (executable / "radhouse").write_text("", encoding="utf-8")
    units = release / "deploy/production"
    units.mkdir(parents=True)
    for unit in CONTROL_UNITS:
        (units / unit).write_text(f"release={release_id}\n", encoding="utf-8")
    return release


def select(deployment: DeploymentManager, release: Path) -> None:
    deployment.paths.application.mkdir(parents=True, exist_ok=True)
    deployment.paths.current.symlink_to(release)


def test_preflight_requires_exact_clean_revision_and_pinned_python(tmp_path: Path):
    runner = FakeRunner()
    source = source_tree(tmp_path, runner)
    deployment = DeploymentManager(runner=runner)

    assert deployment.preflight(source, NEW)["result"] == "ready"
    assert any(
        command[:3] == ("git", "-c", f"safe.directory={source.resolve()}")
        for command in runner.commands
    )
    with pytest.raises(DeploymentError, match="release_identity_mismatch"):
        deployment.preflight(source, OLD)


def test_install_creates_immutable_release_pointer_and_leaves_services_stopped(
    tmp_path: Path, monkeypatch,
):
    runner = FakeRunner()
    source = source_tree(tmp_path, runner)
    deployment = manager(tmp_path, runner, monkeypatch)

    receipt = deployment.install(source, NEW)

    assert receipt == {
        "result": "installed", "release_id": NEW,
        "services_started": False,
        "next": "configure_database_tls_and_private_overlay",
    }
    assert deployment.paths.current.resolve().name == NEW
    manifest = json.loads((deployment.paths.current / "radhouse-release.json").read_text())
    assert manifest["release_id"] == NEW
    assert manifest["storage_schema_version"] == 4
    assert (deployment.paths.configuration / "config.yaml.example").is_file()
    assert all((deployment.paths.systemd / unit).is_file() for unit in CONTROL_UNITS)
    assert ("systemctl", "daemon-reload") in runner.commands
    assert not any(command[:2] == ("systemctl", "start") for command in runner.commands)


def test_upgrade_refuses_unverified_backup_before_stopping_writers(tmp_path: Path, monkeypatch):
    runner = FakeRunner()
    source = source_tree(tmp_path, runner)
    deployment = manager(tmp_path, runner, monkeypatch)
    select(deployment, existing_release(deployment, OLD, 4))
    backup = tmp_path / "backup.dump"
    backup.write_bytes(b"verified database export")

    with pytest.raises(DeploymentError, match="backup_digest_mismatch"):
        deployment.upgrade(
            source, NEW, backup_file=backup, backup_sha256="0" * 64,
            config=tmp_path / "config", overlay=None,
            owner_dsn_file=tmp_path / "owner", runtime_role="radhouse_runtime",
        )

    assert not any(command[:2] == ("systemctl", "stop") for command in runner.commands)


def test_failed_same_schema_upgrade_restores_previous_release(tmp_path: Path, monkeypatch):
    runner = FakeRunner(fail_first_start=True)
    source = source_tree(tmp_path, runner)
    deployment = manager(tmp_path, runner, monkeypatch)
    select(deployment, existing_release(deployment, OLD, 4))
    backup = tmp_path / "backup.dump"
    backup.write_bytes(b"verified database export")
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()

    with pytest.raises(DeploymentError, match="upgrade_failed_rolled_back"):
        deployment.upgrade(
            source, NEW, backup_file=backup, backup_sha256=digest,
            config=tmp_path / "config", overlay=None,
            owner_dsn_file=tmp_path / "owner", runtime_role="radhouse_runtime",
        )

    assert deployment.paths.current.resolve().name == OLD
    assert (deployment.paths.systemd / "radhouse-api.service").read_text() == f"release={OLD}\n"
    assert sum(command[:2] == ("systemctl", "start") for command in runner.commands) == 2


def test_successful_upgrade_preflights_then_stops_migrates_and_selects_release(
    tmp_path: Path, monkeypatch,
):
    runner = FakeRunner()
    source = source_tree(tmp_path, runner)
    deployment = manager(tmp_path, runner, monkeypatch)
    select(deployment, existing_release(deployment, OLD, 4))
    backup = tmp_path / "backup.dump"
    backup.write_bytes(b"verified database export")
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()

    receipt = deployment.upgrade(
        source, NEW, backup_file=backup, backup_sha256=digest,
        config=tmp_path / "config", overlay=tmp_path / "overlay",
        owner_dsn_file=tmp_path / "owner", runtime_role="radhouse_runtime",
    )

    assert receipt["result"] == "upgraded"
    assert receipt["previous_release_id"] == OLD
    assert deployment.paths.current.resolve().name == NEW
    preflight = next(i for i, command in enumerate(runner.commands) if "preflight" in command)
    stop = next(i for i, command in enumerate(runner.commands) if command[:2] == ("systemctl", "stop"))
    migrate = next(i for i, command in enumerate(runner.commands) if "migrate" in command)
    assert preflight < stop < migrate
    assert "--overlay" in runner.commands[migrate]


def test_schema_changing_start_failure_keeps_new_release_for_forward_fix(
    tmp_path: Path, monkeypatch,
):
    runner = FakeRunner(fail_first_start=True)
    source = source_tree(tmp_path, runner)
    deployment = manager(tmp_path, runner, monkeypatch)
    select(deployment, existing_release(deployment, OLD, 4))
    changed = existing_release(deployment, NEW, 5)
    monkeypatch.setattr(deployment, "_stage_release", lambda *_args: changed)
    backup = tmp_path / "backup.dump"
    backup.write_bytes(b"verified database export")
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()

    with pytest.raises(DeploymentError, match="upgrade_failed_forward_fix_required"):
        deployment.upgrade(
            source, NEW, backup_file=backup, backup_sha256=digest,
            config=tmp_path / "config", overlay=None,
            owner_dsn_file=tmp_path / "owner", runtime_role="radhouse_runtime",
        )

    assert deployment.paths.current.resolve().name == NEW


def test_rollback_refuses_release_with_incompatible_schema_before_stop(tmp_path: Path, monkeypatch):
    runner = FakeRunner()
    deployment = manager(tmp_path, runner, monkeypatch)
    select(deployment, existing_release(deployment, NEW, 4))
    existing_release(deployment, OLD, 3)

    with pytest.raises(DeploymentError, match="rollback_schema_incompatible"):
        deployment.rollback(OLD)

    assert not any(command[:2] == ("systemctl", "stop") for command in runner.commands)


def test_rollback_selects_compatible_release_and_its_units(tmp_path: Path, monkeypatch):
    runner = FakeRunner()
    deployment = manager(tmp_path, runner, monkeypatch)
    select(deployment, existing_release(deployment, NEW, 4))
    existing_release(deployment, OLD, 4)

    receipt = deployment.rollback(OLD)

    assert receipt["result"] == "rolled_back"
    assert deployment.paths.current.resolve().name == OLD
    assert (deployment.paths.systemd / "radhouse-api.service").read_text() == f"release={OLD}\n"


def test_status_reports_exact_release_and_each_unit(tmp_path: Path, monkeypatch):
    runner = FakeRunner()
    deployment = manager(tmp_path, runner, monkeypatch)
    select(deployment, existing_release(deployment, NEW, 4))

    receipt = deployment.status()

    assert receipt["release"]["release_id"] == NEW
    assert receipt["services"] == {unit: "active" for unit in CONTROL_UNITS}
