"""Recovery exports are complete, private and verified before fresh extraction."""
import json
from pathlib import Path
import importlib.util

import pytest

spec = importlib.util.spec_from_file_location("recovery_set", Path(__file__).parents[1] / "scripts/recovery_set.py")
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


def plan(tmp_path):
    sources = {}
    for role in recovery.ROLES:
        source = tmp_path / role
        source.mkdir()
        (source / "synthetic.txt").write_text(role)
        sources[role] = str(source)
    return {"schema": recovery.SCHEMA, "sources": sources, "writers_stopped": True,
            "native_export_complete": True, "hermes_commit": "a" * 40, "web_commit": "b" * 40,
            "exclusions": ["temporary browser profiles", "runtime caches"]}


def extract(directory, target, **kwargs):
    return recovery.extract(directory, target, expected_manifest=recovery.digest(directory / "manifest.json"),
        expected_hermes=kwargs.get("hermes", "a" * 40), expected_web="b" * 40)


def test_complete_recovery_set_round_trip_and_refuses_existing_destination(tmp_path):
    output, restored = tmp_path / "sealed", tmp_path / "restored"
    manifest = recovery.seal(plan(tmp_path), output)
    assert set(manifest["components"]) == recovery.ROLES
    extract(output, restored)
    for role in recovery.ROLES:
        assert (restored / role / "synthetic.txt").read_text() == role
    with pytest.raises(FileExistsError):
        extract(output, restored)


@pytest.mark.parametrize("change", ["missing", "tampered", "link", "unexpected", "public"])
def test_invalid_payload_never_extracts(tmp_path, change):
    output = tmp_path / "sealed"
    recovery.seal(plan(tmp_path), output)
    target = output / "chat.tar.gz"
    if change == "missing": target.unlink()
    if change == "tampered": target.write_bytes(b"broken")
    if change == "link":
        target.unlink()
        target.symlink_to(tmp_path / "chat/synthetic.txt")
    if change == "unexpected": (output / "extra").write_text("unexpected")
    if change == "public": target.chmod(0o644)
    with pytest.raises((ValueError, FileNotFoundError)):
        extract(output, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_incomplete_native_export_and_links_are_not_sealed(tmp_path):
    proposal = plan(tmp_path)
    proposal["native_export_complete"] = False
    with pytest.raises(ValueError, match="incomplete_recovery_plan"):
        recovery.seal(proposal, tmp_path / "sealed")
    proposal["native_export_complete"] = True
    (tmp_path / "hermes/link").symlink_to(tmp_path / "chat")
    with pytest.raises(ValueError, match="source_link_or_special_file"):
        recovery.seal(proposal, tmp_path / "sealed")
    assert not (tmp_path / "sealed/manifest.json").exists()


def test_restore_requires_trusted_manifest_and_compatible_source(tmp_path):
    directory = tmp_path / "sealed"
    recovery.seal(plan(tmp_path), directory)
    with pytest.raises(ValueError, match="recovery_source_incompatible"):
        extract(directory, tmp_path / "restored", hermes="c" * 40)
    with pytest.raises(ValueError, match="recovery_manifest_identity_mismatch"):
        recovery.verify(directory, expected_manifest="0" * 64)
    with pytest.raises(ValueError, match="trusted_restore_identity_required"):
        recovery.extract(directory, tmp_path / "restored", expected_manifest=None,
                         expected_hermes="a" * 40, expected_web="b" * 40)
    assert not (tmp_path / "restored").exists()


def test_workspace_executable_survives_private_round_trip(tmp_path):
    import subprocess
    proposal = plan(tmp_path)
    tool = tmp_path / "workspace/run.sh"
    tool.write_text("#!/bin/sh\nprintf 'recovered tool works\\n'\n")
    tool.chmod(0o7755)
    output, restored = tmp_path / "sealed", tmp_path / "restored"
    recovery.seal(proposal, output)
    extract(output, restored)
    executable = restored / "workspace/run.sh"
    assert executable.stat().st_mode & 0o7777 == 0o700
    assert (restored / "workspace/synthetic.txt").stat().st_mode & 0o7777 == 0o600
    assert subprocess.check_output([str(executable)], text=True) == "recovered tool works\n"


@pytest.mark.parametrize("member_type", ["traversal", "absolute", "foreign", "symlink", "fifo", "duplicate"])
def test_rehashed_unsafe_archive_is_refused_before_any_extraction(tmp_path, member_type):
    import tarfile
    proposal = plan(tmp_path)
    output = tmp_path / "sealed"
    manifest = recovery.seal(proposal, output)
    target = output / "workspace.tar.gz"
    name = {"traversal": "workspace/../outside", "absolute": "/outside", "foreign": "other/file"}.get(
        member_type, "workspace/file")
    with tarfile.open(target, "w:gz") as archive:
        member = tarfile.TarInfo(name)
        if member_type == "symlink":
            member.type = tarfile.SYMTYPE
            member.linkname = "../../outside"
        if member_type == "fifo": member.type = tarfile.FIFOTYPE
        archive.addfile(member)
        if member_type == "duplicate": archive.addfile(member)
    manifest["components"]["workspace"].update(size=target.stat().st_size, sha256=recovery.digest(target))
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="unsafe_component_member"):
        extract(output, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


@pytest.mark.parametrize("field,value,error", [
    ("schema", "unknown", "invalid_recovery_manifest"),
    ("kind", "unknown", "invalid_component_kind"),
    ("file", "../outside", "invalid_component_name"),
])
def test_manifest_contract_cannot_be_relaxed(tmp_path, field, value, error):
    output = tmp_path / "sealed"
    manifest = recovery.seal(plan(tmp_path), output)
    if field == "schema": manifest[field] = value
    else: manifest["components"]["chat"][field] = value
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match=error): extract(output, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_file_payload_and_operator_cli_round_trip(tmp_path, monkeypatch, capsys):
    import sys
    proposal = plan(tmp_path)
    proposal["sources"]["hermes"] = str(tmp_path / "native.zip")
    (tmp_path / "native.zip").write_bytes(b"native-export-fixture")
    specification = tmp_path / "plan.json"
    specification.write_text(json.dumps(proposal)); specification.chmod(0o600)
    output = tmp_path / "sealed"
    def cli(*args):
        monkeypatch.setattr(sys, "argv", ["recovery_set", *map(str, args)])
        previous = recovery.os.umask(0o077)
        try: recovery.main()
        finally: recovery.os.umask(previous)
        return json.loads(capsys.readouterr().out)
    sealed = cli("seal", specification, "--output", output)
    assert cli("verify", output) == sealed
    cli("extract", output, "--output", tmp_path / "restored", "--expected-manifest", sealed["manifest_sha256"],
        "--expected-hermes", "a" * 40, "--expected-web", "b" * 40)
    payload = tmp_path / "restored/hermes.payload"
    assert payload.read_bytes() == b"native-export-fixture"
    assert payload.stat().st_mode & 0o777 == 0o600
    with pytest.raises(SystemExit): cli("seal", specification)


@pytest.mark.parametrize("source_type", ["relative", "link", "fifo"])
def test_seal_refuses_untrusted_sources_without_manifest(tmp_path, source_type):
    import os
    proposal = plan(tmp_path)
    source = tmp_path / "bad"
    if source_type == "link": source.symlink_to(tmp_path / "chat/synthetic.txt")
    if source_type == "fifo": os.mkfifo(source)
    proposal["sources"]["hermes"] = "relative" if source_type == "relative" else str(source)
    with pytest.raises(ValueError): recovery.seal(proposal, tmp_path / "sealed")
    assert not (tmp_path / "sealed/manifest.json").exists()
