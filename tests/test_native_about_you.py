"""Run with the qualified Hermes source on PYTHONPATH; never owner profiles."""
import asyncio
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("tools.memory_tool_store", reason="Requires the actual qualified Hermes memory parser.")
RUNTIME = Path(__file__).resolve().parents[1] / "runtime/hermes"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, RUNTIME / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


memory = load("radhouse_about_you_test", "about_you.py")
load("radhouse_hermes_bridge", "bridge.py")
NOW = datetime(2026, 10, 8, 17, tzinfo=timezone.utc)


def read(home, **kwargs):
    return memory.read_saved_memory(home, scrub=lambda text: text, now=NOW, **kwargs)


def test_missing_profile_and_missing_memory_directory_create_nothing(tmp_path):
    home = tmp_path / "never-created"
    value = read(home)
    assert [source["state"] for source in value["sources"]] == ["missing", "missing"]
    assert not home.exists()
    home.mkdir()
    assert all(source["entries"] == [] for source in read(home)["sources"])
    assert list(home.iterdir()) == []


def test_actual_native_parser_preserves_full_entries_bom_and_bare_section_sign(tmp_path):
    directory = tmp_path / "memories"; directory.mkdir()
    path = directory / "USER.md"
    raw = "\ufeff  First line\nsecond line and bare § survive.\n§\n\n  Another complete entry.  "
    path.write_text(raw, encoding="utf-8")
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    value = read(tmp_path)
    source = value["sources"][0]
    assert source["entries"] == ["First line\nsecond line and bare § survive.", "Another complete entry."]
    assert source["source_filename"] == "USER.md" and source["complete"] is True
    assert source["file_modified_at"] == datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    assert value["checked_at"] == NOW.isoformat()
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert sorted(item.name for item in directory.iterdir()) == ["USER.md"]


def test_empty_invalid_utf8_and_nonregular_file_are_distinct(tmp_path):
    directory = tmp_path / "memories"; directory.mkdir()
    (directory / "USER.md").write_bytes(b" \n\xc2\xa7\n ")
    (directory / "MEMORY.md").write_bytes(b"\xff undecodable")
    sources = read(tmp_path)["sources"]
    assert sources[0]["state"] == "empty" and sources[0]["entries"] == []
    assert sources[1]["state"] == "unreadable" and sources[1]["entries"] is None
    (directory / "USER.md").unlink()
    os.mkfifo(directory / "USER.md")
    assert read(tmp_path)["sources"][0]["state"] == "unreadable"


def test_source_and_memory_directory_symlinks_are_never_followed(tmp_path):
    outside = tmp_path / "outside"; outside.mkdir()
    (outside / "USER.md").write_text("Do not export this unrelated file.")
    home = tmp_path / "home"; home.mkdir()
    directory = home / "memories"; directory.mkdir()
    (directory / "USER.md").symlink_to(outside / "USER.md")
    source = read(home)["sources"][0]
    assert source["state"] == "unreadable" and source["entries"] is None
    (directory / "USER.md").unlink(); directory.rmdir(); directory.symlink_to(outside, target_is_directory=True)
    assert all(source["state"] == "unreadable" for source in read(home)["sources"])
    assert (outside / "USER.md").read_text() == "Do not export this unrelated file."


def test_oversized_original_stays_intact_without_partial_entries(tmp_path):
    directory = tmp_path / "memories"; directory.mkdir()
    path = directory / "MEMORY.md"; path.write_bytes(b"x" * (memory.MAX_RESPONSE_BYTES + 1))
    source = read(tmp_path)["sources"][1]
    assert source["state"] == "too_large" and source["entries"] is None and source["complete"] is False
    assert path.stat().st_size == memory.MAX_RESPONSE_BYTES + 1


def test_actual_native_egress_masks_registered_vault_password(tmp_path, monkeypatch):
    from agent.redact import clear_vault_redaction_values, register_vault_redaction_value
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    directory = tmp_path / "memories"; directory.mkdir()
    secret = "SYNTHETIC-Vault-Passphrase-About-You"
    (directory / "USER.md").write_text("A saved note mentioning " + secret)
    clear_vault_redaction_values(); register_vault_redaction_value(secret)
    try:
        value = memory.read_saved_memory(tmp_path, now=NOW)
        assert secret not in json.dumps(value)
        assert (directory / "USER.md").read_text().endswith(secret)
    finally:
        clear_vault_redaction_values()


def test_handler_authentication_precedes_profile_resolution_and_read(monkeypatch):
    from aiohttp import web
    sentinel = web.json_response({"error": "authentication_required"}, status=401)
    monkeypatch.setattr(memory, "read_saved_memory", lambda *_args, **_kwargs: pytest.fail("Unauthorized read"))
    adapter = SimpleNamespace(_check_auth=lambda _request: sentinel)
    response = asyncio.run(memory.handle_about_you(adapter, SimpleNamespace(query={})))
    assert response is sentinel


def test_handler_uses_current_profile_without_an_agent_or_initializer(tmp_path, monkeypatch):
    import hermes_constants
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path / "absent-home")
    adapter = SimpleNamespace(_check_auth=lambda _request: None)
    response = asyncio.run(memory.handle_about_you(adapter, SimpleNamespace(query={})))
    assert response.status == 200 and response.headers["Cache-Control"] == "no-store"
    assert json.loads(response.body)["sources"][0]["state"] == "missing"
    assert list(tmp_path.iterdir()) == []


def test_redactor_failure_never_exports_raw_notes(tmp_path, monkeypatch):
    import agent.redact
    import hermes_constants
    directory = tmp_path / "memories"; directory.mkdir()
    secret = "SYNTHETIC-Private-Note-Do-Not-Export"
    (directory / "USER.md").write_text(secret)
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(agent.redact, "redact_for_egress", lambda _text: agent.redact.REDACTION_UNAVAILABLE)
    adapter = SimpleNamespace(_check_auth=lambda _request: None)
    response = asyncio.run(memory.handle_about_you(adapter, SimpleNamespace(query={})))
    assert response.status == 503
    assert json.loads(response.body) == {"error": "memory_unavailable"}
    assert secret.encode() not in response.body
    assert (directory / "USER.md").read_text() == secret


def test_native_reader_never_accepts_a_caller_supplied_file_path(monkeypatch):
    monkeypatch.setattr(memory, "read_saved_memory", lambda *_args, **_kwargs: pytest.fail("Unexpected read"))
    adapter = SimpleNamespace(_check_auth=lambda _request: None)
    response = asyncio.run(memory.handle_about_you(adapter, SimpleNamespace(query={"path": ".env"})))
    assert response.status == 400
    assert json.loads(response.body) == {"error": "memory_invalid_request"}
