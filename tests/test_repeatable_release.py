"""Offline custody, privacy and lifecycle proofs; no real service or network calls."""
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tarfile
from datetime import timedelta

import pytest

SPEC = importlib.util.spec_from_file_location("release_tool", Path(__file__).parents[1] / "scripts/release.py")
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def write(path, value, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else release.encoded(value))
    path.chmod(mode)
    return path


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "config", "user.name", "Example")
    git(repo, "config", "user.email", "example@example.invalid")
    write(repo / "src/radhouse/chat/static/chat.css", b"body { color: black; }", 0o644)
    write(repo / "src/radhouse/chat/store.py", b"# Frozen schema implementation\n", 0o644)
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "-m", "baseline")
    base = git(repo, "rev-parse", "HEAD")
    write(repo / "src/radhouse/chat/static/chat.css", b"body { color: navy; }", 0o644)
    git(repo, "commit", "--quiet", "-am", "static correction")
    return repo, base, git(repo, "rev-parse", "HEAD")


def packet(tmp_path, repository):
    repo, base, head = repository
    proof = write(tmp_path / "qualification.json", {"source_revision": head, "lane": "static-web", "state": "qualified",
                                                  "checks": [{"name": "appearance-browser", "passed": True}]})
    output = tmp_path / "packet"
    result = release.prepare(repo, head, base, proof, release.sha(proof.read_bytes()), output)
    manifest, files = release.load_packet(output, result["manifest_sha256"])
    return output, result["manifest_sha256"], manifest, files


def schema_digest(db):
    with sqlite3.connect(db) as connection:
        objects = [list(row) for row in connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    return release.sha(release.encoded({"version": version, "objects": objects}))


@pytest.fixture
def target(tmp_path, repository, monkeypatch):
    output, pin, manifest, files = packet(tmp_path, repository)
    root, evidence, data = (tmp_path / name for name in ("releases", "evidence", "data"))
    for p in (root, evidence, data):
        p.mkdir(mode=0o700)
    base = root / manifest["baseline_revision"]
    for name, raw in release.source_files(repository[0], repository[1]).items():
        write(base / name, raw, 0o644)
    db = data / "chat.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.executescript("CREATE TABLE turns (status TEXT,run_id TEXT,first_dispatch_at REAL,retry_until REAL,error TEXT);"
                                 "INSERT INTO turns VALUES('awaiting_dispatch',NULL,NULL,0,NULL); PRAGMA user_version=3;")
    db.chmod(0o600)
    originals = data / "originals"
    originals.mkdir(mode=0o700)
    write(originals / "original.txt", b"owner original")
    unit = write(tmp_path / "radhouse-api.service",
                 ("[Service]\nWorkingDirectory=" + str(base) + "\nEnvironment=RADHOUSE_RELEASE_COMMIT=" + repository[1] + "\n").encode(), 0o644)
    ca = write(tmp_path / "ca.crt", b"synthetic CA", 0o644)
    machine = write(tmp_path / "machine-id", b"synthetic target\n", 0o644)
    controls = write(tmp_path / "controls.json", [{"path": str(ca), "sha256": release.sha(ca.read_bytes()), "uid": os.getuid(), "mode": "0644"}])
    profile = {"RADHOUSE_RELEASE_ROOT": str(root), "RADHOUSE_EVIDENCE_ROOT": str(evidence), "RADHOUSE_API_UNIT_FILE": str(unit),
               "RADHOUSE_BASELINE_REVISION": repository[1], "RADHOUSE_API_UNIT_SHA256": release.sha(unit.read_bytes()),
               "RADHOUSE_MACHINE_ID_FILE": str(machine), "RADHOUSE_MACHINE_ID_SHA256": release.sha(machine.read_bytes()),
               "RADHOUSE_SERVICE_USER": "example_app", "RADHOUSE_SERVICE_GROUP": "example_app", "RADHOUSE_SERVICE_UID": str(os.getuid() or 1000),
               "RADHOUSE_SQLITE_FILE": str(db), "RADHOUSE_SQLITE_SCHEMA_SHA256": schema_digest(db), "RADHOUSE_ORIGINALS_DIR": str(originals),
               "RADHOUSE_HTTPS_ORIGIN": "https://app.example.invalid", "RADHOUSE_TLS_CA_FILE": str(ca), "RADHOUSE_CONTROLS_FILE": str(controls), "RADHOUSE_CONTROLS_SHA256": release.sha(controls.read_bytes())}
    # Synthetic fixtures belong to this process. On root CI the inventory owner check is overridden narrowly.
    actual_inventory = release.inventory
    if os.getuid() == 0:
        def root_fixture_inventory(value):
            return actual_inventory({**value, "RADHOUSE_SERVICE_UID": "0"})
        monkeypatch.setattr(release, "inventory", root_fixture_inventory)
    profile_path = write(tmp_path / ".env", "\n".join(k + "=" + v for k, v in profile.items()).encode())
    approval = release.authority_template(manifest, pin, release.sha(profile_path.read_bytes()))
    approval.update(state="explicit-owner-go", decision_locator="private-owner-decision",
                    approved_at=(release.utcnow() - timedelta(minutes=1)).isoformat(), expires_at=(release.utcnow() + timedelta(minutes=30)).isoformat())
    approval_path = write(tmp_path / "authority.json", approval)

    class FakeHost(release.Host):
        events = []
        failures = 0
        drift = False
        active = True

        def identity(self):
            if self.drift:
                raise release.Refusal("target_machine_mismatch")

        def service(self, expected=None):
            self.events.append("service")
            return "active" if self.active else "inactive"

        def stop(self):
            self.events.append("stop-api")
            type(self).active = False

        def start(self):
            self.events.append("start-api")
            type(self).active = True

        def verify(self, value):
            self.events.append("verify-https-auth-assets")
            if self.failures:
                type(self).failures -= 1
                raise release.Retryable("api_service_not_active")
            return {"provider_calls": 0}

    return dict(output=output, pin=pin, manifest=manifest, files=files, profile=profile, profile_path=profile_path,
                approval=approval, approval_path=approval_path, host=FakeHost, db=db, evidence=evidence, unit=unit, originals=originals)


def apply(target, **kwargs):
    return release.operate("apply", target["output"], target["pin"], target["profile_path"], target["approval_path"],
                           release.sha(target["approval_path"].read_bytes()), host_type=target["host"], **kwargs)


def test_packet_is_deterministic_and_source_bound(tmp_path, repository):
    output, pin, manifest, files = packet(tmp_path, repository)
    assert manifest["source_revision"] == repository[2]
    assert release.tar_bytes(files) == (output / "source.tar").read_bytes()
    assert manifest["baseline_files_sha256"] != manifest["files_sha256"]
    write(repository[0] / "untracked-private.txt", b"local work")
    with pytest.raises(release.Refusal, match="clean"):
        release.plan(*[repository[i] for i in (0, 2, 1)])


def test_unsupported_lane_produces_actionable_offline_plan(repository):
    repo, base, _ = repository
    write(repo / "runtime/hermes/bridge.py", b"# new native capability\n", 0o644)
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "-m", "native change")
    result = release.plan(repo, git(repo, "rev-parse", "HEAD"), base)
    assert not result["apply_supported"]
    assert result["network_calls"] == 0
    assert "separately" in result["next"]


@pytest.mark.parametrize("raw", [b"https://192." + b"168.42.12", b"/Users/" + b"example_person/Developer/", b"https://private-box." + b"lan/", b"-----BEGIN OPENSSH " + b"PRIVATE KEY-----"])
def test_packaging_rejects_private_source_without_echoing_it(raw):
    with pytest.raises(release.Refusal) as result:
        release.privacy_check(raw)
    assert raw.decode() not in str(result.value)


def test_private_denylist_and_standard_network_policy():
    with pytest.raises(release.Refusal):
        release.privacy_check(b"device-private-name", ["device-private-name"])
    release.privacy_check(b'"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.1"')


def test_manifest_and_archive_tampering_stop(tmp_path, repository):
    output, pin, _, _ = packet(tmp_path, repository)
    write(output / "source.tar", b"invalid archive")
    with pytest.raises(release.Refusal, match="archive_digest"):
        release.load_packet(output, pin)


def test_tar_traversal_is_refused(tmp_path, repository):
    output, _, manifest, _ = packet(tmp_path, repository)
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as archive:
        info = tarfile.TarInfo("../escape")
        info.size, info.mode = 1, 0o644
        archive.addfile(info, io.BytesIO(b"x"))
    raw = payload.getvalue()
    write(output / "source.tar", raw)
    manifest["archive_sha256"] = release.sha(raw)
    raw_manifest = release.encoded(manifest)
    write(output / "manifest.json", raw_manifest)
    with pytest.raises(release.Refusal, match="archive_member"):
        release.load_packet(output, release.sha(raw_manifest))


def test_profile_is_private_and_redacted(target, capsys):
    args = ["check", "--packet", str(target["output"]), "--manifest-sha256", target["pin"], "--profile", str(target["profile_path"])]
    assert release.main(args) == 0
    output = capsys.readouterr().out
    assert str(target["db"]) not in output
    target["profile_path"].chmod(0o644)
    assert release.main(args) == 2
    assert str(target["db"]) not in capsys.readouterr().out


def test_authority_expiry_and_scope_stop_before_mutation(target):
    target["approval"]["expires_at"] = (release.utcnow() - timedelta(minutes=2)).isoformat()
    write(target["approval_path"], target["approval"])
    with pytest.raises(release.Refusal, match="authority_expired"):
        apply(target)
    assert not target["host"].events


def test_target_and_control_drift_stop_before_mutation(target):
    target["host"].drift = True
    with pytest.raises(release.Refusal, match="machine"):
        apply(target)
    assert not target["host"].events
    target["host"].drift = False
    write(Path(target["profile"]["RADHOUSE_TLS_CA_FILE"]), b"changed trust", 0o644)
    with pytest.raises(release.Refusal, match="control_drift"):
        apply(target)
    assert "stop-api" not in target["host"].events


def test_busy_owner_and_upload_refuse_without_stop(target):
    with sqlite3.connect(target["db"]) as connection:
        connection.execute("UPDATE turns SET status='running',run_id='synthetic-run'")
    result = apply(target)
    assert result["state"] == "failed"
    assert "owner_work" in result["reason"]
    assert "stop-api" not in target["host"].events
    assert result["retryable"]
    with sqlite3.connect(target["db"]) as connection:
        connection.execute("UPDATE turns SET status='awaiting_dispatch',run_id=NULL")
    assert apply(target, retry_reason="owner-work-quiesced")["state"] == "verified"


def test_upload_refuses_without_stop(target):
    write(target["originals"] / "upload-synthetic", b"partial")
    result = apply(target)
    assert result["reason"] == "active_upload_requires_quiescence"
    assert "stop-api" not in target["host"].events


def test_apply_preserves_pending_work_originals_and_emits_private_receipt(target):
    before = release.inventory(target["profile"])
    result = apply(target)
    assert result["state"] == "verified"
    assert target["host"].events == ["stop-api", "start-api", "verify-https-auth-assets"]
    assert release.inventory(target["profile"]) == before
    evidence = target["evidence"] / target["pin"]
    snapshots = list(evidence.glob("snapshot-*.sqlite3"))
    assert len(snapshots) == 1
    assert snapshots[0].stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(snapshots[0]) as connection:
        assert connection.execute("SELECT status FROM turns").fetchone() == ("awaiting_dispatch",)
    journal = json.loads((evidence / "journal.json").read_bytes())
    assert journal["phase"] == "verified"
    assert apply(target)["state"] == "verified"
    assert target["host"].events.count("stop-api") == 1


def test_diagnosed_failure_requires_explicit_bounded_retry_never_restore(target):
    before = release.inventory(target["profile"])
    target["host"].failures = 2
    result = apply(target)
    assert result["state"] == "failed" and result["retryable"]
    assert target["manifest"]["source_revision"].encode() in target["unit"].read_bytes()
    assert release.inventory(target["profile"]) == before
    with pytest.raises(release.Refusal, match="explicit_retry"):
        apply(target)
    result = apply(target, retry_reason="resolved-api-startup")
    assert result["state"] == "failed"
    with pytest.raises(release.Refusal, match="attempt_limit"):
        apply(target, retry_reason="resolved-api-startup")
    assert release.inventory(target["profile"]) == before
    receipts = [json.loads(p.read_bytes()) for p in (target["evidence"] / target["pin"]).glob("*-apply.json")]
    assert all(r["database_restore"] is False and r["automatic_rollback"] is False for r in receipts)


def test_retry_cannot_hide_data_loss(target):
    target["host"].failures = 1
    apply(target)
    with sqlite3.connect(target["db"]) as connection:
        connection.execute("DELETE FROM turns")
    result = apply(target, retry_reason="resolved-api-startup")
    assert result["reason"] == "owner_retention_changed_no_restore"
    assert not result["retryable"]
    with pytest.raises(release.Refusal, match="reconciliation"):
        apply(target, retry_reason="try-again")
    with sqlite3.connect(target["db"]) as connection:
        assert connection.execute("SELECT count(*) FROM turns").fetchone() == (0,)


def test_explicit_retained_vendor_is_unchanged_and_qualified(target):
    name = "vendor/example_adapter/__init__.py"
    root = Path(target["profile"]["RADHOUSE_RELEASE_ROOT"])
    original = write(root / target["manifest"]["baseline_revision"] / name, b"# qualified dependency\n", 0o644)
    retained = write(target["profile_path"].parent / "retained.json", {name: release.sha(original.read_bytes())})
    target["profile"].update(RADHOUSE_RETAINED_FILES_FILE=str(retained), RADHOUSE_RETAINED_FILES_SHA256=release.sha(retained.read_bytes()))
    write(target["profile_path"], "\n".join(k + "=" + v for k, v in target["profile"].items()).encode())
    target["approval"]["profile_sha256"] = release.sha(target["profile_path"].read_bytes())
    write(target["approval_path"], target["approval"])
    assert apply(target)["state"] == "verified"
    assert (root / target["manifest"]["source_revision"] / name).read_bytes() == original.read_bytes()


def test_unit_baseline_drift_fences_apply_and_writes_failure_receipt(target):
    write(target["unit"], b"[Service]\nUnexpected=true\n", 0o644)
    result = apply(target)
    assert result["state"] == "failed" and not result["retryable"]
    assert "stop-api" not in target["host"].events
    assert list((target["evidence"] / target["pin"]).glob("*-apply.json"))


def test_unsupported_unserved_static_asset_is_not_applyable(repository):
    repo, base, _ = repository
    write(repo / "src/radhouse/chat/static/unserved.js", b"// unserved asset\n", 0o644)
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "-m", "unserved asset")
    assert not release.plan(repo, git(repo, "rev-parse", "HEAD"), base)["apply_supported"]


def test_baseline_local_interpreter_is_refused(target):
    baseline = str(Path(target["profile"]["RADHOUSE_RELEASE_ROOT"]) / target["manifest"]["baseline_revision"])
    raw = target["unit"].read_bytes() + ("ExecStart=" + baseline + "/.venv/bin/python\n").encode()
    write(target["unit"], raw, 0o644)
    target["profile"]["RADHOUSE_API_UNIT_SHA256"] = release.sha(raw)
    with pytest.raises(release.Refusal, match="interpreter"):
        release.candidate_unit(raw, target["manifest"], target["profile"])


def test_https_verification_checks_exact_assets_and_authentication():
    raw = b"served asset"
    manifest = {"files_sha256": {release.STATIC + "chat.css": release.sha(raw)}}

    class ReadOnlyHost(release.Host):
        calls = []
        bad_asset = False
        bad_auth = False

        def service(self, expected=None):
            return "active"

        def get(self, path):
            self.calls.append(path)
            if path == "/healthz":
                return 200, release.encoded({"status": "ready", "scope": "web"})
            if path == "/chat.css":
                return 200, b"incorrect bytes" if self.bad_asset else raw
            return (200 if self.bad_auth else 401), b""

    host = ReadOnlyHost({})
    result = host.verify(manifest)
    assert result["trusted_https"] and result["authentication_denied"]
    assert host.calls == ["/healthz", "/settings", "/chat/history", "/chat/agent-profile", "/chat.css"]
    host.bad_asset = True
    with pytest.raises(release.Refusal, match="asset_integrity"):
        host.verify(manifest)
    host.bad_auth = True
    with pytest.raises(release.Refusal, match="unauthenticated"):
        host.verify(manifest)


def test_private_control_manifest_cannot_rebaseline_drift(target):
    controls = Path(target["profile"]["RADHOUSE_CONTROLS_FILE"])
    values = json.loads(controls.read_bytes())
    values[0]["sha256"] = "a" * 64
    write(controls, values)
    with pytest.raises(release.Refusal, match="control_manifest_drift"):
        apply(target)
    assert not target["host"].events


def test_source_tree_link_and_unknown_member_are_refused(target):
    root = Path(target["profile"]["RADHOUSE_RELEASE_ROOT"]) / target["manifest"]["baseline_revision"]
    write(root / "private-note.txt", b"unexpected local record", 0o644)
    with pytest.raises(release.Refusal, match="unknown_member"):
        release.tree(root, target["manifest"]["baseline_files_sha256"])
    (root / "private-note.txt").unlink()
    source = root / "src/radhouse/chat/store.py"
    source.unlink()
    source.symlink_to(target["db"])
    with pytest.raises(OSError):
        release.tree(root, target["manifest"]["baseline_files_sha256"])


def test_status_is_read_only_and_never_uses_https(target):
    result = release.operate("status", target["output"], target["pin"], target["profile_path"], host_type=target["host"])
    assert result["phase"] == "not-applied"
    assert result["network_calls"] == 0
    assert not list(target["evidence"].iterdir())
    assert target["host"].events == ["service"]
    assert str(target["db"]) not in json.dumps(result)


def test_expiry_after_snapshot_stops_without_selecting_or_restoring(target, monkeypatch):
    real_now = release.utcnow
    original_stop = target["host"].stop
    original_unit = target["unit"].read_bytes()
    before = release.inventory(target["profile"])

    def stop_and_expire(self):
        original_stop(self)
        monkeypatch.setattr(release, "utcnow", lambda: real_now() + timedelta(hours=2))

    monkeypatch.setattr(target["host"], "stop", stop_and_expire)
    result = apply(target)
    assert result["state"] == "failed" and result["reason"] == "authority_expired_or_invalid"
    assert "start-api" not in target["host"].events
    assert target["unit"].read_bytes() == original_unit
    assert release.inventory(target["profile"]) == before
    evidence = target["evidence"] / target["pin"]
    assert len(list(evidence.glob("snapshot-*.sqlite3"))) == 1
    receipt = json.loads(next(evidence.glob("*-apply.json")).read_bytes())
    assert receipt["phase"] == "snapshot-verified"
    assert receipt["database_restore"] is False


def test_verified_journal_cannot_hide_later_source_drift(target):
    assert apply(target)["state"] == "verified"
    root = Path(target["profile"]["RADHOUSE_RELEASE_ROOT"])
    candidate = root / target["manifest"]["source_revision"] / "src/radhouse/chat/static/chat.css"
    write(candidate, b"unreviewed edit", 0o644)
    result = apply(target)
    assert result["state"] == "failed" and result["reason"] == "release_source_drift"
    assert target["host"].events.count("stop-api") == 1
