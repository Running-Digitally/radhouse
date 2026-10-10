#!/usr/bin/env python3
"""Run a fixed offline static-web qualification plan and freeze its source packet."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

# Import the adjacent reviewed helper, never a similarly named installed module.
_SPEC = importlib.util.spec_from_file_location("candidate_release", Path(__file__).with_name("release.py"))
release = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(release)

PYTHON_TESTS = (
    "tests/test_minimal_chat.py", "tests/test_chat_attachments.py",
    "tests/test_chat_agent_profile.py", "tests/test_chat_library.py",
    "tests/test_chat_browser.py", "tests/test_owner_terminal.py",
    "tests/test_chat_about_you.py", "tests/test_chat_inference.py",
    "tests/test_repeatable_release.py", "tests/test_public_privacy.py",
    "tests/test_release_candidate.py",
)
CLIENT_TESTS = ("tests/chat-client.test.mjs", "tests/chat-format.test.mjs")
BROWSER_TESTS = (
    "tests/interface-browser.mjs", "tests/navigation-browser.mjs",
    "tests/agent-profile-browser.mjs", "tests/appearance-readability-browser.mjs",
    "tests/library-browser.mjs", "tests/owner-terminal-browser.mjs",
    "tests/inference-controls-browser.mjs", "tests/about-you-browser.mjs",
    "tests/browser-session-browser.mjs",
)
MAX_LOG = 8 * 1024 * 1024
REQUIRED_IMPORTS = ("pytest", "fastapi", "httpx", "psycopg", "argon2", "pyotp", "cryptography", "yaml", "pypdf")
PROBE = "import importlib.util,json,sys;print(json.dumps({'version':list(sys.version_info[:3]),'missing':[n for n in sys.argv[1:] if importlib.util.find_spec(n) is None]}))"
BROWSER_PROBE = """import{pathToFileURL}from'node:url';import{existsSync}from'node:fs';
const{chromium}=await import(pathToFileURL(process.argv[1]).href);
const executable=process.argv[2]||chromium.executablePath();
console.log(JSON.stringify({chromiumPresent:existsSync(executable)}));"""


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def tool_custody(source, revision):
    for name, actual in (("scripts/release.py", Path(release.__file__)),
                         ("scripts/release_candidate.py", Path(__file__))):
        if release.git(source, "show", revision + ":" + name) != actual.read_bytes():
            raise release.Refusal("running_tool_must_match_frozen_source")
    return {"runner_sha256": release.sha(Path(__file__).read_bytes()),
            "helper_sha256": release.sha(Path(release.__file__).read_bytes())}


def gate_plan(source, revision, baseline):
    result = release.plan(source, revision, baseline)
    names = release.git(source, "ls-tree", "-rz", "--name-only", revision, "--", release.STATIC).decode().split("\0")
    syntax = sorted(name for name in names if name.endswith(".js") and not name.startswith(release.STATIC + "vendor/"))
    gates = [{"name": "public-source-privacy", "kind": "privacy", "files": ["scripts/public_privacy.py"]},
             {"name": "portable-python-api", "kind": "pytest", "files": list(PYTHON_TESTS)},
             {"name": "first-party-js-syntax", "kind": "syntax", "files": syntax},
             {"name": "chat-client-unit", "kind": "node-tests", "files": list(CLIENT_TESTS)}]
    gates.extend({"name": Path(name).stem, "kind": "browser", "files": [name]} for name in BROWSER_TESTS)
    return {**result, "gates": gates if result["apply_supported"] else [],
            "qualification_policy": "conservative-static-web-v1", "provider_calls": 0,
            "target_contact": False, "automatic_approval": False}


def verify_gate_files(source, revision, plan):
    for gate in plan["gates"]:
        if not gate["files"]:
            raise release.Refusal("required_gate_has_no_files")
        for name in gate["files"]:
            if not (source / name).is_file() or (source / name).is_symlink():
                raise release.Refusal("required_gate_file_missing_" + gate["name"])
            release.git(source, "cat-file", "-e", revision + ":" + name)


def safe_environment(source, python, node, playwright_module=None, chromium=None, browsers_path=None):
    """An explicit allowlist. No production config, grants, proxy or provider variables."""
    env = {"PATH": os.pathsep.join(dict.fromkeys((str(Path(python).parent), str(Path(node).parent), "/usr/bin", "/bin"))),
           "LANG": "C", "PYTHONPATH": str(source / "src") + os.pathsep + str(source),
           "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    # Browser caches and temporary subprocess files need the ordinary user locations.
    for key in ("HOME", "TMPDIR", "SYSTEMROOT", "USERPROFILE"):
        if key in os.environ:
            env[key] = os.environ[key]
    if playwright_module:
        env["RADHOUSE_PLAYWRIGHT_MODULE"] = str(playwright_module)
    if chromium:
        env["RADHOUSE_CHROMIUM_EXECUTABLE_PATH"] = str(chromium)
    if browsers_path:
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_path)
    return env


def executable(value, fallback):
    name = value or fallback
    found = shutil.which(str(name))
    if not found:
        raise release.Refusal("required_executable_missing")
    path = Path(found).absolute()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise release.Refusal("required_executable_missing")
    return path


def probe(argv, source, env):
    result = subprocess.run([str(v) for v in argv], cwd=source, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=30, shell=False)
    if result.returncode or len(result.stdout) > 64 * 1024:
        raise release.Refusal("dependency_probe_failed")
    return result.stdout


def preflight(source, python_arg=None, node_arg=None, playwright_arg=None, chromium_arg=None, browsers_arg=None):
    python = executable(python_arg, sys.executable)
    node = executable(node_arg, "node")
    module = Path(playwright_arg).absolute() if playwright_arg else source / "web/node_modules/@playwright/test/index.mjs"
    if not module.is_file():
        raise release.Refusal("existing_playwright_module_required")
    chromium = executable(chromium_arg, str(chromium_arg)) if chromium_arg else None
    browser_cache = Path(browsers_arg).absolute() if browsers_arg else None
    if browser_cache and not browser_cache.is_dir():
        raise release.Refusal("existing_browser_cache_required")
    env = safe_environment(source, python, node, module, chromium, browser_cache)
    data = json.loads(probe([python, "-I", "-c", PROBE, *REQUIRED_IMPORTS], source, env))
    if tuple(data.get("version", [])[:2]) != (3, 14):
        raise release.Refusal("existing_python_3_14_required")
    if data.get("missing"):
        missing = sorted(name for name in REQUIRED_IMPORTS if name in data["missing"])
        raise release.Refusal("existing_python_test_dependencies_required_" + "_".join(missing))
    node_version = probe([node, "--version"], source, env).decode().strip()
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", node_version)
    if not match or tuple(map(int, match.groups())) < (20, 19, 0):
        raise release.Refusal("existing_node_20_19_or_newer_required")
    package = json.loads(release.read_file(module.with_name("package.json")))
    expected = json.loads((source / "web/package.json").read_bytes())["devDependencies"]["@playwright/test"]
    if package.get("name") != "@playwright/test" or package.get("version") != expected:
        raise release.Refusal("existing_lock_pinned_playwright_required")
    browser = json.loads(probe([node, "--input-type=module", "-e", BROWSER_PROBE, module, str(chromium or "")], source, env))
    if browser.get("chromiumPresent") is not True:
        raise release.Refusal("existing_chromium_required")
    return {"python": str(python), "node": str(node), "environment": env,
            "versions": {"python": ".".join(map(str, data["version"])), "node": node_version, "playwright": expected}}


def private_output(source, output):
    output = Path(os.path.abspath(output))
    if output.is_relative_to(source):
        result = subprocess.run(["git", "-C", str(source), "check-ignore", "--quiet", "--no-index", "--", str(output.relative_to(source))],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        if result.returncode:
            raise release.Refusal("candidate_evidence_must_be_ignored_or_external")
    if output.exists() or output.is_symlink():
        raise release.Refusal("candidate_output_must_be_exclusive")
    missing = []
    parent = output.parent
    while not parent.exists() and not parent.is_symlink():
        missing.append(parent)
        parent = parent.parent
    release.ancestors(parent / "placeholder")
    for p in reversed(missing):
        p.mkdir(mode=0o700)
    release.ancestors(output)
    output.mkdir(mode=0o700)
    return release.private_directory(output)


def execute(argv, source, env, log):
    # Preserve ordinary test semantics: custody tests deliberately create 0644 files.
    # Precreate the private report so pytest's normal open/truncate retains 0600.
    if "--junitxml" in argv:
        report = Path(argv[argv.index("--junitxml") + 1])
        release.ancestors(report)
        fd = os.open(report, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        try:
            result = subprocess.run([str(v) for v in argv], cwd=source, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=300, shell=False, umask=0o022)
        except subprocess.TimeoutExpired:
            raise release.Refusal("required_gate_timeout") from None
    if log.stat().st_size > MAX_LOG:
        raise release.Refusal("required_gate_output_limit_exceeded")
    return result.returncode


def gate_commands(gate, tools, output, private_policy):
    python, node = tools["python"], tools["node"]
    if gate["kind"] == "privacy":
        command = [python, gate["files"][0], "--source", "."]
        return [command + (["--private-policy", str(private_policy)] if private_policy else [])]
    if gate["kind"] == "pytest":
        return [[python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=", *gate["files"], "--junitxml", str(output / "portable-python-api.xml")]]
    if gate["kind"] == "syntax":
        return [[node, "--check", name] for name in gate["files"]]
    if gate["kind"] == "node-tests":
        return [[node, "--test", "--test-reporter=tap", *gate["files"]]]
    if gate["kind"] == "browser":
        return [[node, gate["files"][0]]]
    raise release.Refusal("unknown_required_gate")


def complete_gate(gate, output, logs):
    if gate["kind"] == "pytest":
        raw = release.read_file(output / "portable-python-api.xml", private=True, owner=os.getuid())
        cases = list(ET.fromstring(raw).iter("testcase"))
        if not cases or any(any(case.find(name) is not None for name in ("skipped", "failure", "error")) for case in cases):
            raise release.Refusal("required_python_checks_failed_skipped_or_empty")
        return len(cases)
    if gate["kind"] == "node-tests":
        text = release.read_file(logs[0], private=True, owner=os.getuid(), maximum=MAX_LOG).decode(errors="replace")
        metrics = {name: int(number) for name, number in re.findall(r"^# (tests|pass|fail|cancelled|skipped|todo) (\d+)\s*$", text, re.MULTILINE)}
        if (set(metrics) != {"tests", "pass", "fail", "cancelled", "skipped", "todo"} or not metrics["tests"]
                or metrics["pass"] != metrics["tests"] or any(metrics[name] for name in ("fail", "cancelled", "skipped", "todo"))):
            raise release.Refusal("required_node_checks_failed_skipped_or_empty")
        return metrics["tests"]
    return len(logs)


def run_candidate(source, baseline, *, output=None, plan_only=False, python=None, node=None,
                  playwright=None, chromium=None, browsers_path=None, private_policy=None,
                  private_identifiers=None, profile=None, progress=None):
    candidate_started = time.monotonic()
    source = Path(source).resolve()
    revision = release.git(source, "rev-parse", "HEAD").decode().strip()
    plan = gate_plan(source, revision, baseline)
    custody = tool_custody(source, revision)
    if plan_only or not plan["apply_supported"]:
        return {"state": "plan" if plan_only else "separate-qualification-required", **plan, **custody}
    verify_gate_files(source, revision, plan)
    profile_pin = None
    if profile:
        private_profile, profile_pin = release.load_profile(profile)
        if private_profile["RADHOUSE_BASELINE_REVISION"] != baseline:
            raise release.Refusal("profile_baseline_mismatch")
    policy_raw = release.read_file(private_policy, private=True, owner=os.getuid()) if private_policy else None
    policy_pin = release.sha(policy_raw) if policy_raw is not None else None
    identifiers_raw = release.read_file(private_identifiers, private=True, owner=os.getuid()) if private_identifiers else None
    identifiers = identifiers_raw.decode().splitlines() if identifiers_raw is not None else ()
    tools = preflight(source, python, node, playwright, chromium, browsers_path)
    output = private_output(source, output or source / ".release-private" / ("candidate-" + revision))
    policy_snapshot = output / "privacy-policy.json" if policy_raw is not None else None
    if policy_snapshot:
        release.atomic(policy_snapshot, policy_raw)
    evidence = {"schema": "radhouse.executed-qualification.v1", "state": "running", "lane": plan["lane"],
                "source_revision": revision, "baseline_revision": baseline,
                "source_tree": release.git(source, "rev-parse", revision + "^{tree}").decode().strip(),
                "plan_sha256": release.sha(release.encoded(plan)), "qualification_policy": plan["qualification_policy"],
                **custody, "private_policy_sha256": policy_pin,
                "private_identifiers_sha256": release.sha(identifiers_raw) if identifiers_raw is not None else None,
                "versions": tools["versions"],
                "started_at": timestamp(), "checks": [], "network_scope": "synthetic-loopback-fixtures-only",
                "provider_calls": 0, "target_contact": False, "automatic_approval": False, "ci_authenticated": False}
    qualification = output / "qualification.json"
    release.atomic(qualification, release.encoded(evidence))
    def policy_custody():
        if policy_snapshot and release.sha(release.read_file(policy_snapshot, private=True, owner=os.getuid())) != policy_pin:
            raise release.Refusal("frozen_private_policy_changed")

    active_gate, gate_started, records = None, None, []
    try:
        for gate in plan["gates"]:
            release.exact_source(source, revision, baseline)
            tool_custody(source, revision)
            policy_custody()
            if progress:
                progress({"state": "running", "gate": gate["name"]})
            started, commands, records, logs = time.monotonic(), gate_commands(gate, tools, output, policy_snapshot), [], []
            active_gate, gate_started = gate["name"], started
            for index, command in enumerate(commands):
                log = output / (gate["name"] + "-" + str(index) + ".log")
                code = execute(command, source, tools["environment"], log)
                logs.append(log)
                records.append({"argv": command, "returncode": code, "log": log.name, "log_sha256": release.sha(release.read_file(log, private=True, owner=os.getuid(), maximum=MAX_LOG))})
                if code:
                    raise release.Refusal("required_gate_failed_" + gate["name"])
            count = complete_gate(gate, output, logs)
            policy_custody()
            release.exact_source(source, revision, baseline)
            tool_custody(source, revision)
            evidence["checks"].append({"name": gate["name"], "passed": True, "duration_seconds": round(time.monotonic() - started, 3),
                                       "executed_checks": count, "commands": records})
            release.atomic(qualification, release.encoded(evidence))
            active_gate = None
            if progress:
                progress({"state": "passed", "gate": gate["name"], "duration_seconds": evidence["checks"][-1]["duration_seconds"]})
        if {c["name"] for c in evidence["checks"]} != {g["name"] for g in plan["gates"]}:
            raise release.Refusal("required_gate_evidence_missing")
        release.exact_source(source, revision, baseline)
        tool_custody(source, revision)
        policy_custody()
        evidence.update(state="qualified", completed_at=timestamp())
        release.atomic(qualification, release.encoded(evidence))
        qualification_pin = release.sha(release.read_file(qualification, private=True, owner=os.getuid()))
        result = release.prepare(source, revision, baseline, qualification, qualification_pin, output / "packet", identifiers)
        manifest, _ = release.load_packet(output / "packet", result["manifest_sha256"])
        if profile:
            _, checked_profile_pin = release.load_profile(profile)
            if checked_profile_pin != profile_pin:
                raise release.Refusal("private_profile_changed_during_qualification")
        release.exact_source(source, revision, baseline)
        tool_custody(source, revision)
        policy_custody()
        result.update(state="candidate-ready", baseline_revision=baseline, qualification_sha256=qualification_pin,
                      plan_sha256=evidence["plan_sha256"], **custody, checks=len(evidence["checks"]),
                      duration_seconds=round(time.monotonic() - candidate_started, 3),
                      gate_duration_seconds=round(sum(c["duration_seconds"] for c in evidence["checks"]), 3),
                      packet="packet", qualification="qualification.json", checked=True, private_settings="redacted",
                      ci_authenticated=False, target_contact=False, automatic_approval=False)
        release.atomic(output / "candidate.json", release.encoded(result))
        return result
    except Exception as error:
        label = str(error) if isinstance(error, release.Refusal) else "candidate_failure_check_private_evidence"
        if active_gate is not None:
            evidence["checks"].append({"name": active_gate, "passed": False, "duration_seconds": round(time.monotonic() - gate_started, 3),
                                       "reason": label, "commands": records})
        evidence.update(state="failed", reason=label, completed_at=timestamp())
        release.atomic(qualification, release.encoded(evidence))
        # A late source/profile drift must also fence any already-produced packet.
        manifest_path = output / "packet/manifest.json"
        if manifest_path.exists():
            stale = json.loads(release.read_file(manifest_path, private=True, owner=os.getuid()))
            stale.update(apply_supported=False, candidate_state="invalidated", qualification_state="failed")
            release.atomic(manifest_path, release.encoded(stale))
        # Completed packet bytes stay private; failed evidence is never ready.
        result = {"state": "failed", "reason": label, "source_revision": revision, "private_settings": "redacted",
                  "target_contact": False, "automatic_approval": False}
        release.atomic(output / "candidate.json", release.encoded(result))
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path.cwd())
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--python", type=Path, help="Existing Python 3.14 with project/test dependencies")
    parser.add_argument("--node", type=Path, help="Existing Node.js executable")
    parser.add_argument("--playwright-module", type=Path, help="Existing lock-pinned @playwright/test index.mjs")
    parser.add_argument("--chromium", type=Path, help="Existing Chromium executable; otherwise use Playwright cache")
    parser.add_argument("--browsers-path", type=Path, help="Existing Playwright browser cache")
    parser.add_argument("--private-policy", type=Path)
    parser.add_argument("--private-identifiers-file", type=Path)
    parser.add_argument("--profile", type=Path, help="Optional private release profile, validated offline")
    args = parser.parse_args(argv)
    try:
        result = run_candidate(args.source, args.baseline, output=args.output, plan_only=args.plan_only,
                               python=args.python, node=args.node, playwright=args.playwright_module,
                               chromium=args.chromium, browsers_path=args.browsers_path,
                               private_policy=args.private_policy, private_identifiers=args.private_identifiers_file,
                               profile=args.profile, progress=lambda value: print(json.dumps(value, sort_keys=True), flush=True))
        print(json.dumps(result, sort_keys=True))
        return 0 if result["state"] in {"candidate-ready", "plan"} else 1
    except Exception as error:
        label = str(error) if isinstance(error, release.Refusal) else "candidate_refused_check_inputs"
        print(json.dumps({"state": "refused", "reason": label, "private_settings": "redacted"}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
