#!/usr/bin/env python3
"""Analyze a fresh copy of origin/main locally, after changes have been merged."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
KEYCHAIN_SERVICE = "radhouse-sonarqube"
KEYCHAIN_ACCOUNT = "local-analysis"


class ScanError(Exception):
    """A prerequisite or merged-source check failed before analysis."""


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if result.returncode:
        raise ScanError(f"git {args[0]} failed; check origin access and main branch availability")
    return result.stdout.strip()


def token() -> str:
    value = os.environ.get("SONAR_TOKEN", "").strip()
    if not value and sys.platform == "darwin":
        result = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
             "-a", KEYCHAIN_ACCOUNT, "-w"], capture_output=True, text=True,
        )
        if result.returncode == 0:
            value = result.stdout.strip()
    if not value:
        raise ScanError("set SONAR_TOKEN or save the project analysis token in macOS Keychain")
    return value


def analyze(root: Path, scanner: str, host: str, credential: str, *, dry_run: bool = False) -> int:
    if any(os.environ.get(name, "").lower() not in {"", "0", "false"}
           for name in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL")):
        raise ScanError("this command is for local analysis, not a hosted CI runner")
    if os.environ.get("SONAR_SCANNER_JSON_PARAMS"):
        raise ScanError("unset SONAR_SCANNER_JSON_PARAMS; branch/PR overrides are not supported")
    remote = git(root, "remote", "get-url", "origin")
    revision = git(root, "ls-remote", "--exit-code", "origin", "refs/heads/main").split()[0]
    print(f"Merged main commit: {revision}", flush=True)
    if dry_run:
        print("Dry run: only origin/main would be cloned and scanned; no analysis submitted.")
        return 0
    executable = shutil.which(scanner)
    if not executable:
        raise ScanError("install SonarScanner CLI or provide its executable with --scanner")
    if not credential or not host:
        raise ScanError("a project analysis token and SONAR_HOST_URL are required")
    if not host.startswith("https://") and not host.startswith("http://localhost:"):
        raise ScanError("use HTTPS for SONAR_HOST_URL (HTTP is allowed only for localhost)")
    settings = root / "sonar-project.properties"
    if not settings.is_file():
        raise ScanError("sonar-project.properties is missing beside the launcher")

    with tempfile.TemporaryDirectory(prefix="radhouse-sonarqube-") as temporary:
        checkout = Path(temporary) / "source"
        git(root, "clone", "--quiet", "--single-branch", "--branch", "main", "--", remote, str(checkout))
        if git(checkout, "branch", "--show-current") != "main" or git(checkout, "rev-parse", "HEAD") != revision:
            raise ScanError("origin/main moved during preparation; rerun to scan the new merged commit")
        if git(checkout, "status", "--porcelain"):
            raise ScanError("analysis requires a clean clone of the merged main branch")
        if git(root, "ls-remote", "--exit-code", "origin", "refs/heads/main").split()[0] != revision:
            raise ScanError("origin/main moved during preparation; rerun to scan the new merged commit")
        version = tomllib.loads((checkout / "pyproject.toml").read_text())["project"]["version"]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        output = root / ".sonarqube" / f"{stamp}-{revision[:12]}"
        output.mkdir(parents=True)
        receipt = {"source_commit": revision, "branch": "main", "project_key": "Running-Digitally_radhouse",
                   "project_version": version, "started_at": stamp, "test_coverage_imported": False}
        env = os.environ.copy()
        env.update(SONAR_TOKEN=credential, SONAR_HOST_URL=host)
        args = [executable, f"-Dproject.settings={settings}", f"-Dsonar.projectBaseDir={checkout}",
                f"-Dsonar.scm.revision={revision}", f"-Dsonar.projectVersion={version}",
                f"-Dsonar.scanner.metadataFilePath={output / 'report-task.txt'}"]
        print("Static analysis only: no test execution or coverage report is being imported.", flush=True)
        print(f"Local scan evidence: {output}", flush=True)
        try:
            with (output / "scan.log").open("w") as log:
                with subprocess.Popen(args, cwd=checkout, env=env, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True) as process:
                    assert process.stdout is not None
                    for line in process.stdout:
                        sanitized = line.replace(credential, "[REDACTED]")
                        log.write(sanitized)
                        print(sanitized, end="", flush=True)
                    result = process.wait()
            receipt["scanner_exit_code"] = result
            receipt["report_submitted"] = (output / "report-task.txt").is_file()
        finally:
            (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scanner", default="sonar-scanner", help="SonarScanner CLI executable")
    parser.add_argument("--dry-run", action="store_true", help="show origin/main without submitting analysis")
    args = parser.parse_args()
    try:
        return analyze(ROOT, args.scanner, os.environ.get("SONAR_HOST_URL", ""),
                       "" if args.dry_run else token(), dry_run=args.dry_run)
    except (ScanError, OSError) as exc:
        print(f"SonarQube: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
