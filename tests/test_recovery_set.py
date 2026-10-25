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


def test_complete_recovery_set_round_trip_and_refuses_existing_destination(tmp_path):
    output, restored = tmp_path / "sealed", tmp_path / "restored"
    manifest = recovery.seal(plan(tmp_path), output)
    assert set(manifest["components"]) == recovery.ROLES
    recovery.extract(output, restored)
    for role in recovery.ROLES:
        assert (restored / role / "synthetic.txt").read_text() == role
    with pytest.raises(FileExistsError):
        recovery.extract(output, restored)


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
        recovery.extract(output, tmp_path / "restored")
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
