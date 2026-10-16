#!/usr/bin/env python3
"""Test and analyze a fresh copy of origin/main locally, after merge."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
KEYCHAIN_SERVICE = "radhouse-sonarqube"
KEYCHAIN_ACCOUNT = "local-analysis"
HERMES_SOURCE = "https://github.com/NousResearch/hermes-agent.git"


class ScanError(Exception):
    """A prerequisite or merged-source check failed before analysis."""


def git(root: Path, *args: str, env=None) -> str:
    result = subprocess.run(["git", *args], cwd=root, env=env, capture_output=True, text=True)
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


def local_only():
    if any(os.environ.get(name, "").lower() not in {"", "0", "false"}
           for name in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL")):
        raise ScanError("this command is for local analysis, not a hosted CI runner")
    if os.environ.get("SONAR_SCANNER_JSON_PARAMS"):
        raise ScanError("unset SONAR_SCANNER_JSON_PARAMS; branch/PR overrides are not supported")


def remote_main(root):
    return git(root, "ls-remote", "--exit-code", "origin", "refs/heads/main").split()[0]


def unchanged_main(root, checkout, revision):
    if git(checkout, "branch", "--show-current") != "main" or git(checkout, "rev-parse", "HEAD") != revision:
        raise ScanError("origin/main moved during preparation; rerun to scan the new merged commit")
    if git(checkout, "status", "--porcelain"):
        raise ScanError("analysis requires a clean clone of the merged main branch")
    if remote_main(root) != revision:
        raise ScanError("origin/main moved during preparation; rerun to scan the new merged commit")


def prerequisites(scanner, host, credential):
    executable = shutil.which(scanner)
    if not executable:
        raise ScanError("install SonarScanner CLI or provide its executable with --scanner")
    if not credential or not host:
        raise ScanError("a project analysis token and SONAR_HOST_URL are required")
    if not host.startswith("https://"):
        raise ScanError("use HTTPS for SONAR_HOST_URL")
    return executable


def verified_coverage(checkout: Path, revision: str, manifest_path: Path):
    """Admit only successful reports produced inside this exact source clone."""
    fixture = checkout / ".vs0"
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_relative_to(fixture.resolve()):
        raise ScanError("coverage manifest must belong to this clone's owned fixture")
    manifest = json.loads(manifest_path.read_text())
    tests = manifest.get("tests", {})
    if manifest.get("source_commit") != revision or manifest.get("result") != "passed" or manifest.get("cleanup") != "complete":
        raise ScanError("coverage requires this merged commit, passing verification and completed fixture cleanup")
    if not tests.get("tests") or any(tests.get(name, 1) for name in ("failures", "errors", "skipped")):
        raise ScanError("coverage requires executed tests with no failures, errors or skips")
    return manifest, _verified_reports(checkout, fixture, manifest_path, manifest)


def _verified_reports(checkout, fixture, manifest_path, manifest):
    reports = {}
    for name, filename in (("python", "python.xml"), ("javascript", "lcov.info")):
        evidence = manifest.get("coverage", {}).get(name, {})
        expected = manifest_path.parent / "coverage" / filename
        path = (checkout / evidence.get("path", "")).resolve()
        if path != expected.resolve() or not path.is_relative_to(fixture.resolve()):
            raise ScanError("coverage report must belong to the verified fixture run")
        if not path.is_file() or not path.stat().st_size or hashlib.sha256(path.read_bytes()).hexdigest() != evidence.get("sha256"):
            raise ScanError("coverage report is missing or differs from its verified digest")
        reports[name] = path
    return reports


@contextmanager
def native_fixture(checkout, environment, *, remote=HERMES_SOURCE):
    """Supply exact upstream test source outside analysis; never use an owner profile."""
    pin = json.loads((checkout / "runtime/hermes/source-lock.json").read_text())["upstream_commit"]
    if not isinstance(pin, str) or len(pin) != 40 or any(c not in "0123456789abcdef" for c in pin):
        raise ScanError("native qualification requires a full pinned Hermes commit")
    env = environment.copy()
    env.pop("SONAR_TOKEN", None)
    with tempfile.TemporaryDirectory(prefix="radhouse-native-qualification-") as temporary:
        root = Path(temporary)
        source = root / "source"
        commands = (["git", "init", "--quiet", str(source)],
                    ["git", "-C", str(source), "remote", "add", "origin", remote],
                    ["git", "-C", str(source), "fetch", "--quiet", "--depth=1", "origin", pin],
                    ["git", "-C", str(source), "checkout", "--quiet", "--detach", "FETCH_HEAD"])
        for args in commands:
            result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=300)
            if result.returncode:
                raise ScanError("pinned Hermes qualification source preparation failed")
        if git(source, "rev-parse", "HEAD", env=env) != pin or git(source, "status", "--porcelain", env=env):
            raise ScanError("native qualification source must be clean at the pinned commit")
        home = root / "synthetic-home"
        home.mkdir(mode=0o700)
        env.update(RADHOUSE_TEST_HERMES_SOURCE=str(source), HERMES_HOME=str(home),
                   PYTHONPATH=os.pathsep.join((str(checkout / "src"), str(checkout), str(source))))
        yield env, {"repository": remote, "source_commit": pin, "profile": "disposable_synthetic"}
        if git(source, "rev-parse", "HEAD", env=env) != pin or git(source, "status", "--porcelain", env=env):
            raise ScanError("native qualification source changed during verification")



def _failed_test_names(path):
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("oversized_test_report")
    suites = ET.fromstring(path.read_bytes())
    names = set()
    for case in suites.iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            # Parametrization and tracebacks can carry values; retain identifiers only.
            module = case.get("classname", "")
            name = case.get("name", "").split("[", 1)[0]
            if re.fullmatch(r"[\w.]{1,256}", module, flags=re.ASCII) and re.fullmatch(r"\w{1,256}", name, flags=re.ASCII):
                names.add(module + "." + name)
    return sorted(names)


def retain_failed_verification(checkout, output, stdout):
    """Retain bounded typed diagnostics before the disposable clone is removed."""
    checkout = checkout.resolve()
    details = {"state": "unavailable", "parameters_and_output_retained": False}
    try:
        locators = re.findall(r"^Sanitized run manifest: (\.vs0/[a-zA-Z0-9_-]+/manifest\.json)$", stdout, re.MULTILINE)
        if len(locators) != 1:
            raise ValueError("missing_owned_manifest")
        expected = checkout / locators[0]
        manifest_path = expected.resolve()
        if manifest_path != expected.absolute() or not manifest_path.is_relative_to(checkout.resolve()):
            raise ValueError("foreign_fixture")
        if manifest_path.stat().st_size > 1024 * 1024:
            raise ValueError("oversized_manifest")
        manifest = json.loads(manifest_path.read_text())
        tests = manifest.get("tests", {})
        details["tests"] = {key: value for key in ("tests", "failures", "errors", "skipped")
                            if type(value := tests.get(key)) is int and value >= 0}
        details["cleanup_complete"] = manifest.get("cleanup") == "complete"
        report = manifest_path.parent / "pytest.xml"
        if report.resolve() != report.absolute():
            raise ValueError("foreign_test_report")
        details["failed_tests"] = _failed_test_names(report)
        details["state"] = "retained"
    except (OSError, ValueError, TypeError, AttributeError, ET.ParseError):
        # Diagnostics are best effort; they never replace the failed release gate.
        pass
    (output / "failed-verification.json").write_text(json.dumps(details, indent=2) + "\n")


def qualify(checkout, revision, output):
    env = os.environ.copy()
    env.pop("SONAR_TOKEN", None)
    commands = [(["uv", "sync", "--frozen"], "Python dependencies"),
                (["npm", "--prefix", "web", "ci"], "web dependencies")]
    result = None
    for args, label in commands:
        print(f"Preparing {label} from merged source", flush=True)
        result = subprocess.run(args, cwd=checkout, env=env, text=True, capture_output=True, timeout=1200)
        if result.returncode:
            raise ScanError(f"{label} failed (exit {result.returncode}); no analysis submitted")
    print("Preparing pinned Hermes source and disposable synthetic profile", flush=True)
    with native_fixture(checkout, env) as (fixture_env, fixture_evidence):
        print("Preparing owned test and coverage verification from merged source", flush=True)
        result = subprocess.run(
            ["uv", "run", "--frozen", "python", "scripts/vs0.py", "verify", "--coverage"],
            cwd=checkout, env=fixture_env, text=True, capture_output=True, timeout=1200,
        )
        if result.returncode:
            retain_failed_verification(checkout, output, result.stdout)
            raise ScanError(f"owned test and coverage verification failed (exit {result.returncode}); no analysis submitted")
    locators = [line.removeprefix("Sanitized run manifest: ") for line in result.stdout.splitlines()
                if line.startswith("Sanitized run manifest: ")]
    if len(locators) != 1:
        raise ScanError("test verification did not identify exactly one owned fixture manifest")
    manifest, reports = verified_coverage(checkout, revision, checkout / locators[0])
    manifest["native_fixture"] = fixture_evidence
    for name, path in reports.items():
        destination = output / path.name
        shutil.copyfile(path, destination)
        reports[name] = destination
    (output / "verification.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return reports, {"tests": manifest["tests"], "reports": manifest["coverage"],
                     "native_fixture": fixture_evidence}


def scan_process(args, checkout, env, credential, output):
    with (output / "scan.log").open("w") as log:
        with subprocess.Popen(args, cwd=checkout, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True) as process:
            if process.stdout is None:
                raise ScanError("scanner output pipe unavailable")
            for line in process.stdout:
                sanitized = line.replace(credential, "[REDACTED]")
                log.write(sanitized)
                print(sanitized, end="", flush=True)
            return process.wait()


def analyze(root: Path, scanner: str, host: str, credential: str, *, dry_run: bool = False, coverage: bool = True) -> int:
    local_only()
    remote = git(root, "remote", "get-url", "origin")
    revision = remote_main(root)
    print(f"Merged main commit: {revision}", flush=True)
    if dry_run:
        print("Dry run: only origin/main would be tested and scanned; no analysis submitted.")
        return 0
    executable = prerequisites(scanner, host, credential)
    with tempfile.TemporaryDirectory(prefix="radhouse-sonarqube-") as temporary:
        checkout = Path(temporary) / "source"
        git(root, "clone", "--quiet", "--single-branch", "--branch", "main", "--", remote, str(checkout))
        unchanged_main(root, checkout, revision)
        settings = checkout / "sonar-project.properties"
        if not settings.is_file():
            raise ScanError("sonar-project.properties must be committed on merged main")
        version = tomllib.loads((checkout / "pyproject.toml").read_text())["project"]["version"]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        output = root / ".sonarqube" / f"{stamp}-{revision[:12]}"
        output.mkdir(parents=True)
        receipt = {"source_commit": revision, "branch": "main", "project_key": "Running-Digitally_radhouse",
                   "project_version": version, "started_at": stamp, "report_submitted": False,
                   "test_coverage_submitted": False, "test_coverage_imported": False}
        args = [executable, f"-Dsonar.projectBaseDir={checkout}",
                f"-Dsonar.scm.revision={revision}", f"-Dsonar.projectVersion={version}",
                f"-Dsonar.scanner.metadataFilePath={output / 'report-task.txt'}"]
        print(f"Local scan evidence: {output}", flush=True)
        try:
            if coverage:
                reports, receipt["verification"] = qualify(checkout, revision, output)
                args.extend([f"-Dsonar.python.coverage.reportPaths={reports['python']}",
                             f"-Dsonar.javascript.lcov.reportPaths={reports['javascript']}"])
            else:
                print("Static analysis only: no coverage imported", flush=True)
            unchanged_main(root, checkout, revision)
            env = os.environ.copy()
            env.update(SONAR_TOKEN=credential, SONAR_HOST_URL=host)
            result = scan_process(args, checkout, env, credential, output)
            submitted = (output / "report-task.txt").is_file()
            receipt.update(scanner_exit_code=result, report_submitted=submitted,
                           test_coverage_submitted=coverage and submitted,
                           test_coverage_imported=coverage and submitted and result == 0)
            return result
        finally:
            (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scanner", default="sonar-scanner", help="SonarScanner CLI executable")
    parser.add_argument("--dry-run", action="store_true", help="show origin/main without submitting analysis")
    parser.add_argument("--static-only", action="store_true", help="explicitly omit tests and coverage")
    args = parser.parse_args()
    try:
        return analyze(ROOT, args.scanner, os.environ.get("SONAR_HOST_URL", ""),
                       "" if args.dry_run else token(), dry_run=args.dry_run, coverage=not args.static_only)
    except (ScanError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"SonarQube: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
