"""Exercise candidate orchestration with synthetic executions and exact Git source."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest

SPEC = importlib.util.spec_from_file_location("release_candidate", Path(__file__).parents[1] / "scripts/release_candidate.py")
candidate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(candidate)
release = candidate.release


def write(path, raw, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw if isinstance(raw, bytes) else release.encoded(raw))
    path.chmod(mode)
    return path


def git(repo, *arguments):
    return subprocess.run(["git", "-C", str(repo), *arguments], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "--quiet")
    git(root, "config", "user.name", "Example")
    git(root, "config", "user.email", "example@example.invalid")
    write(root / ".gitignore", b".release-private/\n.releases/\n", 0o644)
    for name in (*candidate.PYTHON_TESTS, *candidate.CLIENT_TESTS, *candidate.BROWSER_TESTS, "scripts/public_privacy.py"):
        write(root / name, b"# Synthetic fixed gate fixture\n", 0o644)
    for path in (Path(candidate.__file__), Path(release.__file__)):
        write(root / "scripts" / path.name, path.read_bytes(), 0o644)
    write(root / "src/radhouse/chat/static/chat.css", b"body {color:black}", 0o644)
    write(root / "src/radhouse/chat/static/chat.js", b"// Frozen first-party JS\n", 0o644)
    git(root, "add", ".")
    git(root, "commit", "--quiet", "-m", "baseline")
    baseline = git(root, "rev-parse", "HEAD")
    write(root / "src/radhouse/chat/static/chat.css", b"body {color:navy}", 0o644)
    git(root, "commit", "--quiet", "-am", "static correction")
    return root, baseline, git(root, "rev-parse", "HEAD")


@pytest.fixture
def execution(monkeypatch):
    calls = []
    monkeypatch.setattr(candidate, "preflight", lambda *_: {"python": "existing-python", "node": "existing-node", "environment": {},
                                                           "versions": {"python": "3.14.4", "node": "v22.0.0", "playwright": "1.60.0"}})

    def execute(argv, root, env, log):
        calls.append(list(argv))
        if "--junitxml" in argv:
            write(Path(argv[argv.index("--junitxml") + 1]), b'<testsuites><testsuite><testcase name="fixture"/></testsuite></testsuites>')
        text = b"fixed gate passed\n"
        if "--test-reporter=tap" in argv:
            text = b"# tests 2\n# pass 2\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n"
        write(log, text)
        return 0

    monkeypatch.setattr(candidate, "execute", execute)
    return calls


def test_plan_only_requires_no_dependencies_and_writes_nothing(source, monkeypatch):
    root, baseline, _ = source
    monkeypatch.setattr(candidate, "preflight", lambda *_: pytest.fail("plan must not preflight dependencies"))
    result = candidate.run_candidate(root, baseline, plan_only=True)
    assert result["state"] == "plan"
    assert result["apply_supported"]
    assert len(result["gates"]) == 13
    assert not (root / ".release-private").exists()
    assert result["target_contact"] is False and result["automatic_approval"] is False


def test_unsupported_native_change_routes_separately_without_execution(source, monkeypatch):
    root, baseline, _ = source
    write(root / "runtime/hermes/bridge.py", b"# new native source\n", 0o644)
    git(root, "add", ".")
    git(root, "commit", "--quiet", "-m", "native change")
    monkeypatch.setattr(candidate, "preflight", lambda *_: pytest.fail("unsupported lane must not execute gates"))
    result = candidate.run_candidate(root, baseline)
    assert result["state"] == "separate-qualification-required"
    assert not result["gates"] and not (root / ".release-private").exists()


def test_candidate_freezes_executed_checks_with_timings_and_pins(source, execution):
    root, baseline, revision = source
    result = candidate.run_candidate(root, baseline)
    assert result["state"] == "candidate-ready" and result["checked"]
    assert result["duration_seconds"] >= result["gate_duration_seconds"]
    output = root / ".release-private" / ("candidate-" + revision)
    evidence = json.loads((output / "qualification.json").read_bytes())
    assert evidence["state"] == "qualified" and evidence["ci_authenticated"] is False
    assert evidence["source_revision"] == revision and evidence["baseline_revision"] == baseline
    assert {c["name"] for c in evidence["checks"]} == {g["name"] for g in candidate.gate_plan(root, revision, baseline)["gates"]}
    assert all(c["duration_seconds"] >= 0 and c["commands"] and c["executed_checks"] > 0 for c in evidence["checks"])
    assert evidence["runner_sha256"] == release.sha(Path(candidate.__file__).read_bytes())
    assert evidence["helper_sha256"] == release.sha(Path(release.__file__).read_bytes())
    assert result["qualification_sha256"] == release.sha((output / "qualification.json").read_bytes())
    manifest, _ = release.load_packet(output / "packet", result["manifest_sha256"])
    assert manifest["qualification_sha256"] == result["qualification_sha256"]
    assert len(execution) == 13
    assert not git(root, "status", "--porcelain")
    assert output.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in output.iterdir() if p.is_file())
    assert str(root) not in json.dumps(result)


def test_any_failed_gate_prevents_packet_and_qualified_receipt(source, execution, monkeypatch):
    root, baseline, revision = source
    monkeypatch.setattr(candidate, "execute", lambda argv, root, env, log: (write(log, b"synthetic failure"), 1)[1])
    result = candidate.run_candidate(root, baseline)
    output = root / ".release-private" / ("candidate-" + revision)
    assert result["state"] == "failed"
    assert result["reason"] == "required_gate_failed_public-source-privacy"
    evidence = json.loads((output / "qualification.json").read_bytes())
    assert evidence["state"] == "failed"
    assert evidence["checks"][-1]["passed"] is False
    assert evidence["checks"][-1]["duration_seconds"] >= 0
    assert not (output / "packet").exists()


@pytest.mark.parametrize("kind", ["pytest", "node"])
def test_success_exit_with_skipped_checks_cannot_qualify(source, execution, monkeypatch, kind):
    root, baseline, revision = source
    original = candidate.execute

    def skipped(argv, root, env, log):
        code = original(argv, root, env, log)
        if kind == "pytest" and "--junitxml" in argv:
            write(Path(argv[argv.index("--junitxml") + 1]), b'<testsuites><testsuite><testcase name="fixture"><skipped/></testcase></testsuite></testsuites>')
        if kind == "node" and "--test-reporter=tap" in argv:
            write(log, b"# tests 2\n# pass 1\n# fail 0\n# cancelled 0\n# skipped 1\n# todo 0\n")
        return code

    monkeypatch.setattr(candidate, "execute", skipped)
    result = candidate.run_candidate(root, baseline)
    assert result["state"] == "failed" and "skipped" in result["reason"]
    assert not (root / ".release-private" / ("candidate-" + revision) / "packet").exists()


def test_source_changes_during_checks_invalidate_evidence(source, execution, monkeypatch):
    root, baseline, revision = source
    original = candidate.execute

    def mutating(argv, root, env, log):
        code = original(argv, root, env, log)
        write(root / "src/radhouse/chat/static/chat.css", b"unreviewed edit", 0o644)
        return code

    monkeypatch.setattr(candidate, "execute", mutating)
    result = candidate.run_candidate(root, baseline)
    assert result["state"] == "failed" and result["reason"] == "source_checkout_must_be_clean"
    evidence = root / ".release-private" / ("candidate-" + revision) / "qualification.json"
    assert json.loads(evidence.read_bytes())["state"] == "failed"
    assert not evidence.with_name("packet").exists()


def test_missing_required_gate_is_explicit(source, execution):
    root, baseline, _ = source
    (root / candidate.BROWSER_TESTS[-1]).unlink()
    git(root, "commit", "--quiet", "-am", "remove required journey")
    with pytest.raises(release.Refusal):
        candidate.run_candidate(root, baseline)
    assert not execution


def test_production_environment_is_not_inherited(source, monkeypatch):
    root, _, _ = source
    for key in ("RADHOUSE_CHAT_CONFIG", "RADHOUSE_VS0_DSN", "HTTPS_PROXY", "OPENAI_API_KEY", "NODE_OPTIONS", "PYTEST_ADDOPTS", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(key, "synthetic-sensitive-value")
    env = candidate.safe_environment(root, "/example/python", "/example/node", "/example/playwright/index.mjs", "/example/chromium")
    assert not any(key in env for key in ("RADHOUSE_CHAT_CONFIG", "RADHOUSE_VS0_DSN", "HTTPS_PROXY", "OPENAI_API_KEY", "NODE_OPTIONS", "PYTEST_ADDOPTS", "AWS_SECRET_ACCESS_KEY"))
    assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert env["RADHOUSE_PLAYWRIGHT_MODULE"] == "/example/playwright/index.mjs"


def test_evidence_must_be_private_and_never_overwritten(source, execution):
    root, baseline, _ = source
    with pytest.raises(release.Refusal, match="ignored_or_external"):
        candidate.run_candidate(root, baseline, output=root / "public-output")
    candidate.run_candidate(root, baseline)
    with pytest.raises(release.Refusal, match="exclusive"):
        candidate.run_candidate(root, baseline)


def test_cli_refusal_is_sanitized(source, capsys, monkeypatch):
    root, baseline, _ = source
    private_location = str(root / "private-python")
    monkeypatch.setattr(candidate, "preflight", lambda *_: (_ for _ in ()).throw(OSError(private_location)))
    assert candidate.main(["--source", str(root), "--baseline", baseline]) == 2
    output = capsys.readouterr().out
    assert private_location not in output and str(root) not in output


def test_preflight_missing_browser_is_explicit(source, monkeypatch, tmp_path):
    root, _, _ = source
    module = write(tmp_path / "playwright/index.mjs", b"// existing fixture module", 0o644)
    write(module.with_name("package.json"), {"name": "@playwright/test", "version": "1.60.0"}, 0o644)
    write(root / "web/package.json", {"devDependencies": {"@playwright/test": "1.60.0"}}, 0o644)
    monkeypatch.setattr(candidate, "executable", lambda value, fallback: Path("/example/executable"))

    def probe(argv, root, env):
        if "--version" in argv:
            return b"v22.0.0\n"
        if "-c" in argv:
            return release.encoded({"version": [3, 14, 4], "missing": []})
        return release.encoded({"chromiumPresent": False})

    monkeypatch.setattr(candidate, "probe", probe)
    with pytest.raises(release.Refusal, match="existing_chromium_required"):
        candidate.preflight(root, playwright_arg=module)


def test_late_source_drift_invalidates_an_already_produced_packet(source, execution, monkeypatch):
    root, baseline, revision = source
    original = release.load_packet

    def drift_after_packet(packet, pin):
        result = original(packet, pin)
        write(root / "src/radhouse/chat/static/chat.css", b"late unreviewed edit", 0o644)
        return result

    monkeypatch.setattr(release, "load_packet", drift_after_packet)
    result = candidate.run_candidate(root, baseline)
    assert result["state"] == "failed"
    output = root / ".release-private" / ("candidate-" + revision)
    manifest = json.loads((output / "packet/manifest.json").read_bytes())
    assert manifest["apply_supported"] is False
    assert manifest["candidate_state"] == "invalidated"
    with pytest.raises(release.Refusal, match="separate_qualification"):
        release.require_supported(manifest)


def test_execute_preserves_normal_file_custody_test_semantics(tmp_path):
    import sys
    log = tmp_path / "execution.log"
    report = tmp_path / "report.xml"
    created = tmp_path / "deliberately-public.txt"
    code = 'import pathlib,sys;pathlib.Path(sys.argv[1]).touch(mode=0o644);pathlib.Path(sys.argv[3]).write_text("<testsuites/>")'
    assert candidate.execute([sys.executable, "-c", code, str(created), "--junitxml", str(report)], tmp_path, {}, log) == 0
    assert created.stat().st_mode & 0o777 == 0o644
    assert report.stat().st_mode & 0o777 == 0o600
    assert log.stat().st_mode & 0o777 == 0o600


def test_privacy_executes_frozen_policy_even_if_original_changes(source, execution, monkeypatch, tmp_path):
    root, baseline, revision = source
    original_policy = write(tmp_path / "owner-policy.json", {"deny_literals": ["first-private-fixture"]})
    original_raw = original_policy.read_bytes()
    identifiers = write(tmp_path / "identifiers.txt", b"fixture-identity-never-in-source\n")
    original = candidate.execute
    observed = []

    def mutate_original(argv, root, env, log):
        if "--private-policy" in argv:
            snapshot = Path(argv[argv.index("--private-policy") + 1])
            assert snapshot != original_policy
            assert snapshot.stat().st_mode & 0o777 == 0o600
            write(original_policy, {"deny_literals": ["changed-private-fixture"]})
            observed.append(snapshot.read_bytes())
        return original(argv, root, env, log)

    monkeypatch.setattr(candidate, "execute", mutate_original)
    result = candidate.run_candidate(root, baseline, private_policy=original_policy, private_identifiers=identifiers)
    assert result["state"] == "candidate-ready"
    assert observed == [original_raw]
    output = root / ".release-private" / ("candidate-" + revision)
    evidence = json.loads((output / "qualification.json").read_bytes())
    assert evidence["private_policy_sha256"] == release.sha(original_raw)
    assert evidence["private_identifiers_sha256"] == release.sha(identifiers.read_bytes())
    assert "first-private-fixture" not in json.dumps(result)
    assert "first-private-fixture" not in (output / "packet/manifest.json").read_text()


def test_mutating_frozen_policy_refuses_qualification(source, execution, monkeypatch, tmp_path):
    root, baseline, revision = source
    policy = write(tmp_path / "policy.json", {"deny_literals": []})
    original = candidate.execute

    def mutate_snapshot(argv, root, env, log):
        if "--private-policy" in argv:
            write(Path(argv[argv.index("--private-policy") + 1]), {"deny_literals": ["unreviewed-private-fixture"]})
        return original(argv, root, env, log)

    monkeypatch.setattr(candidate, "execute", mutate_snapshot)
    result = candidate.run_candidate(root, baseline, private_policy=policy)
    assert result["state"] == "failed" and result["reason"] == "frozen_private_policy_changed"
    assert not (root / ".release-private" / ("candidate-" + revision) / "packet").exists()


def test_preflight_missing_import_is_actionable_without_raw_probe_data(source, monkeypatch, tmp_path):
    root, _, _ = source
    module = write(tmp_path / "playwright/index.mjs", b"// existing fixture module", 0o644)
    monkeypatch.setattr(candidate, "executable", lambda value, fallback: Path("/example/executable"))
    monkeypatch.setattr(candidate, "probe", lambda *_: release.encoded({"version": [3, 14, 4], "missing": ["pypdf", "private-unrecognized-string"]}))
    with pytest.raises(release.Refusal) as error:
        candidate.preflight(root, playwright_arg=module)
    assert str(error.value) == "existing_python_test_dependencies_required_pypdf"
