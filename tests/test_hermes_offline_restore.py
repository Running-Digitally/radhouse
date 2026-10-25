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
            "ReadWritePaths=/var/lib/synthetic-restore/home"} <= properties
    assert args[-3:] == ["import", "/var/lib/synthetic-restore/native.zip", "--force"]
    assert "--setenv=HERMES_HOME=/var/lib/synthetic-restore/home" in args


def test_import_never_runs_as_root():
    with pytest.raises(ValueError, match="unprivileged_import_account_required"):
        offline.command(python="/python", source="/source", account=SimpleNamespace(pw_uid=0),
                        workspace="/restore", unit="restore")
