#!/usr/bin/env python3
"""Run native Hermes import in an offline, supervisor-contained fresh home.

The pinned import command may install/start a gateway when it cannot discover an
installation in the platform-default home. HERMES_HOME alone is not an offline
restore switch. Enforce isolation outside Hermes; retain its import semantics.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import subprocess
import threading
from uuid import uuid4


def command(*, python, source, account, workspace, unit):
    if account.pw_uid == 0:
        raise ValueError("unprivileged_import_account_required")
    workspace = Path(workspace)
    # The main process and any children are contained in one transient cgroup.
    # User service installation, user-bus control and outbound calls are denied.
    return ["systemd-run", "--quiet", "--wait", "--pipe", "--collect", "--unit=" + unit,
        "-p", "Type=exec", "-p", "ExitType=main", "-p", "KillMode=control-group", "-p", "TasksAccounting=yes",
        "-p", "TimeoutStopSec=5", "-p", "RuntimeMaxSec=300",
        "-p", "JobRunningTimeoutSec=30", "-p", "TimeoutStartSec=30",
        "-p", "User=" + account.pw_name, "-p", "Group=" + str(account.pw_gid),
        "-p", "UMask=0077", "-p", "NoNewPrivileges=yes", "-p", "PrivateNetwork=yes",
        "-p", "PrivateTmp=yes", "-p", "PrivateDevices=yes", "-p", "ProtectSystem=strict",
        "-p", "ProtectHome=read-only", "-p", "ProtectControlGroups=yes",
        "-p", "InaccessiblePaths=-/run/user -/run/dbus -/run/systemd/private",
        "-p", "ReadWritePaths=" + str(workspace / "home") + " " + str(workspace / "account-home"),
        "-p", "WorkingDirectory=" + str(workspace / "home"),
        "--setenv=HERMES_HOME=" + str(workspace / "home"),
        "--setenv=HOME=" + str(workspace / "account-home"),
        "--setenv=DBUS_SESSION_BUS_ADDRESS=unix:path=/nonexistent",
        "--setenv=PYTHONDONTWRITEBYTECODE=1",
        str(python), "-I", "-B", "-c",
        "import sys; sys.path.insert(0, " + repr(str(source)) + "); from hermes_cli.main import main; main()",
        "import", str(workspace / "native.zip"), "--force"]


def stop_import(unit, log):
    """Cancel even a queued start and prove PID 1 no longer owns running work."""
    subprocess.run(["systemctl", "stop", unit], stdout=log, stderr=subprocess.STDOUT, timeout=15)
    result = subprocess.run(["systemctl", "show", unit, "--property=LoadState,ActiveState,MainPID,Job,TasksCurrent"],
                            capture_output=True, text=True, timeout=15)
    status = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    # Collected transient units are reported as not-found (and may return 4).
    if (result.returncode not in {0, 4} or status.get("LoadState") not in {"loaded", "not-found"}
            or status.get("ActiveState") not in {"inactive", "failed"}
            or status.get("MainPID") != "0" or status.get("Job") not in {"", "0"}
            or (status["LoadState"] == "loaded" and status.get("TasksCurrent") != "0")):
        raise RuntimeError("offline_import_cleanup_unverified:" + unit)


def run_import(args, log, unit):
    handlers = {}
    def interrupted(_signum, _frame):
        raise InterruptedError("offline_import_interrupted")
    try:
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                handlers[sig] = signal.signal(sig, interrupted)
        try:
            result = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, timeout=360)
            if result.returncode:
                raise ValueError("offline_import_failed_see_private_log")
            return result
        except BaseException:
            # Killing the systemd-run client alone leaves its service owned by
            # PID 1. Complete cleanup before returning any failed attempt.
            stop_import(unit, log)
            raise
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def restore(*, python, source, user, archive, workspace):
    if os.geteuid() != 0:
        raise ValueError("operator_root_required")
    account = pwd.getpwnam(user)
    paths = [Path(value) for value in (python, source, archive, workspace)]
    if (any(not p.is_absolute() for p in paths) or any(p.is_symlink() for p in paths[1:])
            or account.pw_uid == 0):
        raise ValueError("invalid_restore_plan")
    python, source, archive, workspace = paths
    # Virtualenv interpreters are normally symlinks; retain the venv invocation
    # while requiring an operator-owned, non-writable interpreter target.
    interpreter = python.resolve(strict=True).stat()
    if interpreter.st_uid != 0 or interpreter.st_mode & 0o022:
        raise ValueError("trusted_interpreter_required")
    if workspace.exists() or not archive.is_file() or not (source / "hermes_cli/backup.py").is_file():
        raise ValueError("fresh_target_and_native_archive_required")
    workspace.mkdir(mode=0o700, parents=False)
    os.chown(workspace, 0, account.pw_gid)
    os.chmod(workspace, 0o710)
    # Native _external/ entries use Path.home(), separately from HERMES_HOME.
    for name in ("home", "account-home"):
        target = workspace / name
        target.mkdir(mode=0o700)
        os.chown(target, account.pw_uid, account.pw_gid)
    shutil.copyfile(archive, workspace / "native.zip")
    os.chmod(workspace / "native.zip", 0o400)
    os.chown(workspace / "native.zip", account.pw_uid, account.pw_gid)
    unit = "radhouse-offline-restore-" + uuid4().hex + ".service"
    args = command(python=python, source=source, account=account, workspace=workspace, unit=unit)
    with (workspace / "import.log").open("xb") as log:
        os.chmod(workspace / "import.log", 0o600)
        result = run_import(args, log, unit)
    receipt = {"state": "imported_offline", "unit": unit, "native_import_exit": result.returncode,
               "network": "private", "writable_scope": ["home", "account-home"],
               "service_control": "inaccessible", "content_verification_required": True}
    with (workspace / "receipt.json").open("x") as stream:
        os.chmod(workspace / "receipt.json", 0o600)
        json.dump(receipt, stream, indent=2)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("python", "source", "archive", "workspace", "user"):
        parser.add_argument("--" + name, required=True)
    os.umask(0o077)
    print(json.dumps(restore(**vars(parser.parse_args()))))


if __name__ == "__main__":
    main()
