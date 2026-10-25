"""Native import must not activate a second gateway or reach external services."""
from pathlib import Path
from types import SimpleNamespace
import importlib.util

import pytest

spec = importlib.util.spec_from_file_location("offline", Path(__file__).parents[1] / "scripts/hermes_offline_restore.py")
offline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(offline)


def test_offline_boundary_surrounds_unmodified_native_import():
    account = SimpleNamespace(pw_uid=1001, pw_gid=1001, pw_name="synthetic-worker")
    args = offline.command(python="/opt/synthetic/bin/python", source="/opt/synthetic/source",
                           account=account, workspace="/var/lib/synthetic-restore", unit="synthetic-restore")
    properties = {args[i + 1] for i, value in enumerate(args) if value == "-p"}
    assert {"PrivateNetwork=yes", "ProtectSystem=strict", "ProtectHome=read-only",
            "KillMode=control-group", "ExitType=main", "NoNewPrivileges=yes",
            "InaccessiblePaths=-/run/user -/run/dbus -/run/systemd/private",
            "ReadWritePaths=/var/lib/synthetic-restore/home /var/lib/synthetic-restore/account-home",
            "JobRunningTimeoutSec=30", "TimeoutStartSec=30", "TasksAccounting=yes"} <= properties
    assert args[-3:] == ["import", "/var/lib/synthetic-restore/native.zip", "--force"]
    assert "--setenv=HERMES_HOME=/var/lib/synthetic-restore/home" in args


def test_import_never_runs_as_root():
    with pytest.raises(ValueError, match="unprivileged_import_account_required"):
        offline.command(python="/python", source="/source", account=SimpleNamespace(pw_uid=0),
                        workspace="/restore", unit="restore")


@pytest.fixture
def restore_plan(tmp_path, monkeypatch):
    import os
    account = SimpleNamespace(pw_uid=1001, pw_gid=1001, pw_name="synthetic-worker")
    monkeypatch.setattr(offline.os, "geteuid", lambda: 0)
    monkeypatch.setattr(offline.pwd, "getpwnam", lambda user: account)
    monkeypatch.setattr(offline.os, "chown", lambda *args: None)
    source = tmp_path / "source"
    (source / "hermes_cli").mkdir(parents=True)
    (source / "hermes_cli/backup.py").write_text("# synthetic importer")
    archive = tmp_path / "native.zip"
    archive.write_bytes(b"synthetic archive")
    # The system interpreter is operator-owned on both Linux and macOS.
    return dict(python="/usr/bin/python3", source=str(source), user=account.pw_name,
                archive=str(archive), workspace=str(tmp_path / "restore"))


def test_restore_redirects_both_homes_and_records_private_result(restore_plan, monkeypatch):
    def importer(args, **kwargs):
        environment = dict(arg.removeprefix("--setenv=").split("=", 1) for arg in args if arg.startswith("--setenv="))
        native = Path(environment["HERMES_HOME"])
        account = Path(environment["HOME"])
        (native / "memories").mkdir()
        (native / "memories/MEMORY.md").write_text("synthetic memory")
        (account / ".honcho").mkdir()
        (account / ".honcho/config.json").write_text('{"synthetic":true}')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(offline.subprocess, "run", importer)
    receipt = offline.restore(**restore_plan)
    workspace = Path(restore_plan["workspace"])
    assert (workspace / "home/memories/MEMORY.md").read_text() == "synthetic memory"
    assert (workspace / "account-home/.honcho/config.json").read_text() == '{"synthetic":true}'
    assert receipt["writable_scope"] == ["home", "account-home"]
    assert receipt["content_verification_required"] is True
    for name, mode in [("home", 0o700), ("account-home", 0o700), ("native.zip", 0o400),
                       ("receipt.json", 0o600), ("import.log", 0o600)]:
        assert (workspace / name).stat().st_mode & 0o777 == mode
    with pytest.raises(ValueError, match="fresh_target"): offline.restore(**restore_plan)


@pytest.mark.parametrize("failure", ["timeout", "interrupt", "signal", "exit"])
def test_failed_launcher_stops_exact_unit_before_returning_without_receipt(restore_plan, monkeypatch, failure):
    import signal
    import subprocess
    events = []
    def run(args, **kwargs):
        events.append(args)
        if args[0] == "systemd-run":
            if failure == "timeout": raise subprocess.TimeoutExpired(args, 360)
            if failure == "interrupt": raise KeyboardInterrupt()
            if failure == "signal": signal.raise_signal(signal.SIGTERM)
            return SimpleNamespace(returncode=1)
        if args[1] == "stop": return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=0, stdout="LoadState=loaded\nActiveState=inactive\nMainPID=0\nJob=\nTasksCurrent=0\n")
    monkeypatch.setattr(offline.subprocess, "run", run)
    expected = {"timeout": subprocess.TimeoutExpired, "interrupt": KeyboardInterrupt,
                "signal": InterruptedError, "exit": ValueError}[failure]
    original_handler = signal.getsignal(signal.SIGTERM)
    with pytest.raises(expected): offline.restore(**restore_plan)
    unit = next(arg.split("=", 1)[1] for arg in events[0] if arg.startswith("--unit="))
    assert events[1] == ["systemctl", "stop", unit]
    assert events[2][1:3] == ["show", unit]
    assert signal.getsignal(signal.SIGTERM) == original_handler
    assert not (Path(restore_plan["workspace"]) / "receipt.json").exists()


@pytest.mark.parametrize("status,code,passes", [
    ("LoadState=not-found\nActiveState=inactive\nMainPID=0\nJob=\n", 4, True),
    ("LoadState=loaded\nActiveState=activating\nMainPID=0\nJob=19\n", 0, False),
    ("LoadState=loaded\nActiveState=inactive\nMainPID=42\nJob=\n", 0, False),
    ("LoadState=loaded\nActiveState=inactive\nMainPID=0\nJob=19\n", 0, False),
    ("LoadState=loaded\nActiveState=failed\nMainPID=0\nJob=\nTasksCurrent=1\n", 0, False),
    ("LoadState=loaded\nActiveState=inactive\nMainPID=0\nJob=\nTasksCurrent=[not set]\n", 0, False),
    ("LoadState=loaded\nActiveState=inactive\nMainPID=0\nJob=\nTasksCurrent=0\n", 0, True),
    ("", 1, False),
])
def test_cleanup_requires_proven_inactive_unit_without_queued_job(monkeypatch, status, code, passes):
    monkeypatch.setattr(offline.subprocess, "run", lambda args, **kwargs:
                       SimpleNamespace(returncode=code, stdout=status))
    if passes: offline.stop_import("synthetic.service", None)
    else:
        with pytest.raises(RuntimeError, match="cleanup_unverified"):
            offline.stop_import("synthetic.service", None)


@pytest.mark.parametrize("invalid", ["nonroot", "root_account", "relative", "link", "missing_archive", "writable_python"])
def test_invalid_restore_never_launches_import(restore_plan, monkeypatch, tmp_path, invalid):
    monkeypatch.setattr(offline.subprocess, "run", lambda *args, **kwargs: pytest.fail("import launched"))
    if invalid == "nonroot": monkeypatch.setattr(offline.os, "geteuid", lambda: 1001)
    if invalid == "root_account": monkeypatch.setattr(offline.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=0))
    if invalid == "relative": restore_plan["workspace"] = "relative"
    if invalid == "link":
        linked = tmp_path / "linked"; linked.symlink_to(restore_plan["archive"])
        restore_plan["archive"] = str(linked)
    if invalid == "missing_archive": Path(restore_plan["archive"]).unlink()
    if invalid == "writable_python":
        executable = tmp_path / "untrusted-python"; executable.touch(); executable.chmod(0o777)
        restore_plan["python"] = str(executable)
    with pytest.raises(ValueError): offline.restore(**restore_plan)
    assert not Path(restore_plan["workspace"]).exists()


def test_operator_cli_uses_private_umask_and_reports_result(monkeypatch, capsys):
    import json
    import os
    import sys
    expected = {key: "synthetic-" + key for key in ("python", "source", "archive", "workspace", "user")}
    monkeypatch.setattr(sys, "argv", ["offline", *sum((["--" + k, v] for k, v in expected.items()), [])])
    def restore(**kwargs):
        assert kwargs == expected
        old = os.umask(0o077)
        assert old == 0o077
        return {"state": "synthetic-pass"}
    monkeypatch.setattr(offline, "restore", restore)
    previous = os.umask(0o022)
    try: offline.main()
    finally: os.umask(previous)
    assert json.loads(capsys.readouterr().out) == {"state": "synthetic-pass"}
