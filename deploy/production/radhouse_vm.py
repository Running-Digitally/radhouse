#!/usr/bin/env python3
"""Install and update Radhouse on one operator-supplied Linux control VM.

The manager intentionally owns only the application release lifecycle. Network,
TLS, database credentials, firewall policy, and Hermes/Buzz admission remain
operator configuration.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import sys
from typing import Sequence


CONTROL_UNITS = (
    "radhouse-api.service",
    "radhouse-coordinator.service",
    "radhouse-coordinator.timer",
    "radhouse-hermes-tunnel.service",
)
OPTIONAL_UNITS = ("radhouse-hermes-tunnel@.service",)
WRITER_UNITS = (
    "radhouse-coordinator.timer",
    "radhouse-coordinator.service",
    "radhouse-api.service",
)
START_UNITS = ("radhouse-api.service", "radhouse-coordinator.timer")
RELEASE_ID = re.compile(r"[0-9a-f]{40}")


class DeploymentError(RuntimeError):
    """A bounded deployment refusal safe to return to the operator."""


@dataclass(frozen=True)
class Paths:
    application: Path = Path("/opt/radhouse")
    configuration: Path = Path("/etc/radhouse")
    state: Path = Path("/srv/radhouse")
    systemd: Path = Path("/etc/systemd/system")

    @property
    def releases(self) -> Path:
        return self.application / "releases"

    @property
    def current(self) -> Path:
        return self.application / "current"


class Runner:
    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        capture: bool = False,
    ) -> str:
        completed = subprocess.run(
            list(command), cwd=cwd, check=True, text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
        return completed.stdout.strip() if capture else ""

    def which(self, command: str) -> str | None:
        return shutil.which(command)


class DeploymentManager:
    def __init__(self, paths: Paths = Paths(), runner: Runner | None = None):
        self.paths = paths
        self.runner = runner or Runner()

    def preflight(self, source: Path, release_id: str) -> dict:
        source = source.resolve()
        if not RELEASE_ID.fullmatch(release_id):
            raise DeploymentError("invalid_release_id")
        required_files = (
            "pyproject.toml", "uv.lock", "web/package-lock.json",
            "deploy/production/compose.postgres.yaml",
            "deploy/production/radhouse-api.service",
            "deploy/production/radhouse-coordinator.service",
            "deploy/production/radhouse-coordinator.timer",
            "deploy/production/radhouse-hermes-tunnel.service",
            "deploy/production/radhouse-hermes-tunnel@.service",
        )
        if any(not (source / name).is_file() for name in required_files):
            raise DeploymentError("incomplete_source_tree")
        for command in (
            "cc", "docker", "git", "node", "npm", "pkg-config", "uv", "python3.14",
            "systemctl", "useradd",
        ):
            if self.runner.which(command) is None:
                raise DeploymentError(f"missing_command:{command}")
        node = self.runner.run(("node", "--version"), capture=True)
        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", node)
        if match is None or tuple(map(int, match.groups())) < (20, 19, 0):
            raise DeploymentError("unsupported_node_version")
        if self.runner.run(("python3.14", "--version"), capture=True) != "Python 3.14.4":
            raise DeploymentError("unsupported_python_version")
        head = self._git(source, "rev-parse", "HEAD")
        if head != release_id:
            raise DeploymentError("release_identity_mismatch")
        if self._git(source, "status", "--porcelain", "--untracked-files=no"):
            raise DeploymentError("source_tree_dirty")
        return {"result": "ready", "release_id": release_id, "source": str(source)}

    def install(self, source: Path, release_id: str) -> dict:
        self._require_root()
        self.preflight(source, release_id)
        if self.paths.current.exists() or self.paths.current.is_symlink():
            raise DeploymentError("installation_exists")
        self._ensure_system_users()
        self._ensure_layout()
        release = self._stage_release(source.resolve(), release_id)
        self._install_configuration_example(release)
        self._install_units(release)
        self.runner.run(("systemctl", "daemon-reload"))
        self._switch_current(release)
        return {
            "result": "installed",
            "release_id": release_id,
            "services_started": False,
            "next": "configure_database_tls_and_private_overlay",
        }

    def upgrade(
        self,
        source: Path,
        release_id: str,
        *,
        backup_file: Path,
        backup_sha256: str,
        config: Path,
        overlay: Path | None,
        owner_dsn_file: Path,
        runtime_role: str,
    ) -> dict:
        self._require_root()
        self.preflight(source, release_id)
        old_release = self._current_release()
        if old_release.name == release_id:
            raise DeploymentError("release_already_current")
        self._verify_backup(backup_file, backup_sha256)
        new_release = self._stage_release(source.resolve(), release_id)
        command = [str(new_release / ".venv/bin/radhouse"), "preflight", "--config", str(config)]
        if overlay:
            command.extend(("--overlay", str(overlay)))
        self.runner.run(command)

        old_schema = self._manifest(old_release)["storage_schema_version"]
        new_schema = self._manifest(new_release)["storage_schema_version"]
        stopped = False
        switched = False
        migrated = False
        try:
            stopped = True
            self.runner.run(("systemctl", "stop", *WRITER_UNITS))
            migrate = [
                str(new_release / ".venv/bin/radhouse"), "migrate",
                "--config", str(config), "--owner-dsn-file", str(owner_dsn_file),
                "--runtime-role", runtime_role, "--apply",
            ]
            if overlay:
                migrate[4:4] = ("--overlay", str(overlay))
            self.runner.run(migrate)
            migrated = True
            self._install_units(new_release)
            self._switch_current(new_release)
            switched = True
            self.runner.run(("systemctl", "daemon-reload"))
            self.runner.run(("systemctl", "start", *START_UNITS))
            self._verify_active()
        except (DeploymentError, OSError, subprocess.CalledProcessError) as error:
            if stopped and (not migrated or old_schema == new_schema):
                if switched:
                    self._switch_current(old_release)
                self._install_units(old_release)
                self.runner.run(("systemctl", "daemon-reload"))
                self.runner.run(("systemctl", "start", *START_UNITS))
                raise DeploymentError("upgrade_failed_rolled_back") from error
            if stopped:
                # A changed database schema fences the old release. Keep the new
                # release selected so the operator can diagnose or forward-fix it.
                if not switched:
                    self._switch_current(new_release)
                raise DeploymentError("upgrade_failed_forward_fix_required") from error
            raise DeploymentError("upgrade_failed_before_stop") from error
        return {
            "result": "upgraded", "release_id": release_id,
            "previous_release_id": old_release.name,
            "backup_sha256": backup_sha256,
            "storage_schema_version": new_schema,
        }

    def rollback(self, release_id: str) -> dict:
        self._require_root()
        if not RELEASE_ID.fullmatch(release_id):
            raise DeploymentError("invalid_release_id")
        current = self._current_release()
        if current.name == release_id:
            raise DeploymentError("release_already_current")
        target = self.paths.releases / release_id
        if not target.is_dir():
            raise DeploymentError("release_not_found")
        if self._manifest(current)["storage_schema_version"] != self._manifest(target)["storage_schema_version"]:
            raise DeploymentError("rollback_schema_incompatible")
        try:
            self.runner.run(("systemctl", "stop", *WRITER_UNITS))
        except subprocess.CalledProcessError as error:
            self.runner.run(("systemctl", "start", *START_UNITS))
            raise DeploymentError("rollback_stop_failed_current_restarted") from error
        try:
            self._install_units(target)
            self._switch_current(target)
            self.runner.run(("systemctl", "daemon-reload"))
            self.runner.run(("systemctl", "start", *START_UNITS))
            self._verify_active()
        except (OSError, subprocess.CalledProcessError) as error:
            self._switch_current(current)
            self._install_units(current)
            self.runner.run(("systemctl", "daemon-reload"))
            self.runner.run(("systemctl", "start", *START_UNITS))
            raise DeploymentError("rollback_failed_current_restored") from error
        return {"result": "rolled_back", "release_id": release_id, "replaced_release_id": current.name}

    def status(self) -> dict:
        current = self._current_release()
        services = {}
        for unit in CONTROL_UNITS:
            try:
                value = self.runner.run(("systemctl", "is-active", unit), capture=True)
            except subprocess.CalledProcessError as error:
                value = (error.stdout or "inactive").strip() or "inactive"
            services[unit] = value
        return {"result": "installed", "release": self._manifest(current), "services": services}

    def _stage_release(self, source: Path, release_id: str) -> Path:
        destination = self.paths.releases / release_id
        if destination.exists():
            manifest = self._manifest(destination)
            if manifest.get("release_id") != release_id:
                raise DeploymentError("release_manifest_mismatch")
            return destination
        # Virtual-environment entry points contain their absolute installation
        # path. Build at the final versioned path and select it only after the
        # manifest is complete; renaming a built venv would break its shebangs.
        destination.mkdir(mode=0o750)
        try:
            listing = self._git(source, "ls-files", "-z")
            tracked = [name for name in listing.split("\0") if name]
            if not tracked:
                raise DeploymentError("empty_source_tree")
            digest = hashlib.sha256()
            for name in sorted(tracked):
                origin = source / name
                if origin.is_symlink() or not origin.is_file():
                    raise DeploymentError("unsupported_source_entry")
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origin, target)
                digest.update(name.encode("utf-8") + b"\0")
                digest.update(hashlib.sha256(origin.read_bytes()).digest())
            self.runner.run(("npm", "--prefix", "web", "ci"), cwd=destination)
            self.runner.run(("npm", "--prefix", "web", "run", "build"), cwd=destination)
            python = self.runner.which("python3.14")
            if python is None:
                raise DeploymentError("missing_command:python3.14")
            self.runner.run((
                "uv", "sync", "--frozen", "--no-dev", "--no-editable",
                "--python", python,
            ), cwd=destination)
            self.runner.run((str(destination / ".venv/bin/radhouse"), "--help"), cwd=destination)
            schema = int(self.runner.run(
                (str(destination / ".venv/bin/python"), "-I", "-c",
                 "from radhouse.storage.postgres import SCHEMA_VERSION; print(SCHEMA_VERSION)"),
                cwd=destination, capture=True,
            ))
            manifest = {
                "release_id": release_id,
                "source_sha256": digest.hexdigest(),
                "storage_schema_version": schema,
                "installed_at": datetime.now(timezone.utc).isoformat(),
            }
            (destination / "radhouse-release.json").write_text(
                json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8",
            )
            self._protect_release(destination)
        except Exception:
            if destination.exists():
                shutil.rmtree(destination)
            raise
        return destination

    def _git(self, source: Path, *arguments: str) -> str:
        # The installer normally runs through sudo against the invoking
        # operator's checkout. Scope Git's ownership exception to this one
        # already validated source path instead of changing global Git config.
        return self.runner.run(
            ("git", "-c", f"safe.directory={source}", *arguments),
            cwd=source, capture=True,
        )

    def _ensure_system_users(self) -> None:
        for user in ("radhouse", "radhouse-tunnel"):
            try:
                pwd.getpwnam(user)
            except KeyError:
                self.runner.run((
                    "useradd", "--system", "--user-group", "--no-create-home",
                    "--home-dir", "/nonexistent", "--shell", "/usr/sbin/nologin", user,
                ))

    def _ensure_layout(self) -> None:
        for path, mode in (
            (self.paths.application, 0o755), (self.paths.releases, 0o755),
            (self.paths.configuration, 0o755), (self.paths.configuration / "secrets", 0o750),
            (self.paths.configuration / "tls", 0o750), (self.paths.configuration / "tunnel", 0o750),
            (self.paths.state, 0o750), (self.paths.state / "postgres", 0o750),
            (self.paths.state / "postgres/data", 0o700),
            (self.paths.state / "postgres/init", 0o750),
        ):
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(mode)
        for path in (
            self.paths.configuration / "secrets",
            self.paths.configuration / "tls",
        ):
            shutil.chown(path, user="root", group="radhouse")
        # The digest-pinned PostgreSQL image runs database and initialization
        # work as its postgres account (UID/GID 999). Bind mounts created as
        # root:root 0700 fail before the database can initialize.
        for path in (
            self.paths.state / "postgres/data",
            self.paths.state / "postgres/init",
        ):
            shutil.chown(path, user=999, group=999)
        shutil.chown(
            self.paths.configuration / "tunnel",
            user="root", group="radhouse-tunnel",
        )

    def _install_configuration_example(self, release: Path) -> None:
        target = self.paths.configuration / "config.yaml.example"
        if not target.exists():
            shutil.copy2(release / "deploy/production/config.example.yaml", target)
            target.chmod(0o640)
            shutil.chown(target, user="root", group="radhouse")

    def _install_units(self, release: Path) -> None:
        for unit in CONTROL_UNITS:
            source = release / "deploy/production" / unit
            target = self.paths.systemd / unit
            shutil.copy2(source, target)
            target.chmod(0o644)
        for unit in OPTIONAL_UNITS:
            source = release / "deploy/production" / unit
            if source.is_file():
                target = self.paths.systemd / unit
                shutil.copy2(source, target)
                target.chmod(0o644)

    def _switch_current(self, release: Path) -> None:
        temporary = self.paths.application / ".current.new"
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(release)
        os.replace(temporary, self.paths.current)

    def _current_release(self) -> Path:
        if not self.paths.current.is_symlink():
            raise DeploymentError("installation_not_found")
        release = self.paths.current.resolve()
        if release.parent != self.paths.releases.resolve() or not release.is_dir():
            raise DeploymentError("current_release_invalid")
        return release

    @staticmethod
    def _manifest(release: Path) -> dict:
        try:
            value = json.loads((release / "radhouse-release.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise DeploymentError("release_manifest_invalid") from error
        if value.get("release_id") != release.name or not isinstance(value.get("storage_schema_version"), int):
            raise DeploymentError("release_manifest_invalid")
        return value

    @staticmethod
    def _verify_backup(path: Path, expected_sha256: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise DeploymentError("invalid_backup_sha256")
        try:
            metadata = path.lstat()
        except OSError as error:
            raise DeploymentError("backup_unreadable") from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_size == 0:
            raise DeploymentError("backup_invalid")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha256:
            raise DeploymentError("backup_digest_mismatch")

    def _verify_active(self) -> None:
        for unit in START_UNITS:
            self.runner.run(("systemctl", "is-active", "--quiet", unit))

    @staticmethod
    def _protect_release(release: Path) -> None:
        for path in (release, *release.rglob("*")):
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                os.chown(
                    path, 0, pwd.getpwnam("radhouse").pw_gid,
                    follow_symlinks=False,
                )
                continue
            if path.is_dir():
                path.chmod(0o750)
            elif mode & stat.S_IXUSR:
                path.chmod(0o750)
            else:
                path.chmod(0o640)
            shutil.chown(path, user="root", group="radhouse")

    @staticmethod
    def _require_root() -> None:
        if os.geteuid() != 0:
            raise DeploymentError("root_required")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="radhouse-vm")
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("preflight", "install"):
        command = commands.add_parser(name)
        command.add_argument("--source", type=Path, required=True)
        command.add_argument("--release-id", required=True)
    upgrade = commands.add_parser("upgrade")
    upgrade.add_argument("--source", type=Path, required=True)
    upgrade.add_argument("--release-id", required=True)
    upgrade.add_argument("--backup-file", type=Path, required=True)
    upgrade.add_argument("--backup-sha256", required=True)
    upgrade.add_argument("--config", type=Path, default=Path("/etc/radhouse/config.yaml"))
    upgrade.add_argument("--overlay", type=Path)
    upgrade.add_argument("--owner-dsn-file", type=Path, required=True)
    upgrade.add_argument("--runtime-role", default="radhouse_runtime")
    rollback = commands.add_parser("rollback")
    rollback.add_argument("--release-id", required=True)
    commands.add_parser("status")
    return result


def main(arguments: list[str] | None = None) -> int:
    args = parser().parse_args(arguments)
    manager = DeploymentManager()
    try:
        if args.command == "preflight":
            output = manager.preflight(args.source, args.release_id)
        elif args.command == "install":
            output = manager.install(args.source, args.release_id)
        elif args.command == "upgrade":
            output = manager.upgrade(
                args.source, args.release_id, backup_file=args.backup_file,
                backup_sha256=args.backup_sha256, config=args.config,
                overlay=args.overlay, owner_dsn_file=args.owner_dsn_file,
                runtime_role=args.runtime_role,
            )
        elif args.command == "rollback":
            output = manager.rollback(args.release_id)
        else:
            output = manager.status()
    except (DeploymentError, OSError, subprocess.CalledProcessError, ValueError) as error:
        code = str(error) if isinstance(error, DeploymentError) else "deployment_command_failed"
        print(json.dumps({"result": "refused", "code": code}, sort_keys=True))
        return 2
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
