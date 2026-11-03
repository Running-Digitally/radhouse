"""Execute the pinned native contracts with synthetic state and no provider calls.

These tests qualify integration seams, not a running gateway or handset delivery.
Set RADHOUSE_PROACTIVE_SOURCE to require a particular clean upstream checkout.
"""
import ast
import asyncio
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest


PACKAGE = Path(__file__).resolve().parents[1] / "runtime/hermes"


@pytest.fixture(scope="module")
def source():
    explicit = os.environ.get("RADHOUSE_PROACTIVE_SOURCE")
    package = importlib.util.find_spec("hermes_cli")
    if not explicit and package is None:
        pytest.skip("Exact pinned Hermes source required for native qualification")
    root = Path(explicit) if explicit else Path(package.origin).parent.parent
    lock = json.loads((PACKAGE / "proactive-source-lock.json").read_text())
    active = json.loads((PACKAGE / "source-lock.json").read_text())
    assert lock["upstream_commit"] == active["upstream_commit"]
    for path, expected in lock["files"].items():
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == expected, path
    return root


@pytest.fixture
def isolated_home(tmp_path, monkeypatch, source):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "native-home"))
    monkeypatch.syspath_prepend(str(source))
    return tmp_path


def function(source, name, namespace, *, async_only=False):
    """Compile actual source with collaborators replaced at explicit seams."""
    matches = [node for node in ast.walk(ast.parse(source.read_text()))
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
               and (not async_only or isinstance(node, ast.AsyncFunctionDef))]
    assert len(matches) == 1
    node = matches[0]
    node.decorator_list = []
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    code = ast.fix_missing_locations(ast.Module(body=[future, node], type_ignores=[]))
    exec(compile(code, str(source), "exec"), namespace)
    return namespace[name]


@pytest.fixture
def heartbeat(isolated_home, monkeypatch):
    from hermes_cli import heartbeat
    from hermes_state import SessionDB
    db = SessionDB(isolated_home / "heartbeat.db")
    monkeypatch.setattr(heartbeat, "_get_session_db", lambda: db)
    monkeypatch.setattr(heartbeat.time, "time", lambda: 1000.0)
    try:
        yield heartbeat, db
    finally:
        db.close()


def test_heartbeat_roundtrip_coalesces_missed_ticks(heartbeat):
    native, db = heartbeat
    native.HeartbeatManager("synthetic-session").set("Review the synthetic fixture", 60)
    restarted = native.HeartbeatManager("synthetic-session")
    assert restarted.due_prompt(1059) is None
    assert "synthetic fixture" in restarted.due_prompt(1600)
    assert restarted.due_prompt(1600) is None
    assert restarted.state.fire_count == 1
    assert native.HeartbeatManager("synthetic-session").due_prompt(1659) is None
    assert json.loads(db.get_meta("heartbeat:synthetic-session"))["last_fired_at"] == 1600


def test_heartbeat_new_process_reads_durable_state(heartbeat, source):
    native, db = heartbeat
    native.HeartbeatManager("synthetic-session").set("Synthetic purpose", 60)
    code = """import json, sys
from pathlib import Path
from hermes_state import SessionDB
from hermes_cli import heartbeat
db = SessionDB(Path(sys.argv[1]))
heartbeat._get_session_db = lambda: db
try:
    manager = heartbeat.HeartbeatManager('synthetic-session')
    print(json.dumps({'prompt': manager.state.prompt, 'due': manager.due_prompt(1060) is not None}))
finally:
    db.close()
"""
    env = {**os.environ, "PYTHONPATH": str(source)}
    result = subprocess.run([sys.executable, "-c", code, str(db.db_path)], env=env,
                            capture_output=True, text=True, timeout=30, check=True)
    assert json.loads(result.stdout) == {"prompt": "Synthetic purpose", "due": True}


def test_pause_resume_clear_and_session_rotation(heartbeat, monkeypatch):
    native, _ = heartbeat
    manager = native.HeartbeatManager("parent")
    manager.set("Synthetic purpose", 60)
    manager.pause()
    assert native.HeartbeatManager("parent").due_prompt(5000) is None
    monkeypatch.setattr(native.time, "time", lambda: 5000)
    manager.resume()
    assert manager.due_prompt(5059) is None
    assert native.migrate_heartbeat_to_session("parent", "child") is True
    assert native.load_heartbeat("parent") is None
    child = native.HeartbeatManager("child")
    assert child.due_prompt(5060) is not None
    assert child.clear() is True
    assert native.HeartbeatManager("child").has_heartbeat() is False


def test_abandoned_fire_restores_due_but_cannot_undo_pause(heartbeat):
    native, _ = heartbeat
    manager = native.HeartbeatManager("synthetic-session")
    manager.set("Synthetic purpose", 60)
    manager.due_prompt(1060)
    assert manager.abandon_fire() is True
    assert manager.due_prompt(1060) is not None
    native.HeartbeatManager("synthetic-session").pause()
    assert manager.abandon_fire() is False
    assert native.load_heartbeat("synthetic-session").status == "paused"


def test_failed_persistence_is_not_an_activation_receipt(heartbeat, monkeypatch):
    native, _ = heartbeat
    def fail(*args):
        raise OSError("synthetic storage unavailable")
    monkeypatch.setattr(native, "_get_session_db", lambda: SimpleNamespace(set_meta=fail, get_meta=fail))
    accepted_in_memory = native.HeartbeatManager("synthetic-session").set("Synthetic purpose", 60)
    assert accepted_in_memory.status == "active"
    assert native.load_heartbeat("synthetic-session") is None


@pytest.mark.parametrize("response,silent", [
    ("[SILENT]", True), ("[SILENT] No change", True),
    ("Nothing new\nNO_REPLY", True), ("", False),
    ("The documentation mentions [SILENT] as a marker.", False),
])
def test_native_autonomous_silence_contract(source, isolated_home, response, silent):
    test = function(source / "cron/scheduler.py", "_is_cron_silence_response", {})
    assert test(response) is silent


def test_failure_marker_is_not_quiet_success(source):
    test = function(source / "cron/scheduler.py", "_cron_failure_marker_error",
                    {"CRON_FAILURE_MARKER": "[CRON_FAILURE]"})
    assert test("[CRON_FAILURE]\nSource inaccessible") == "Source inaccessible"
    assert test("Report quotes [CRON_FAILURE]") is None


def test_native_tool_resolution_empty_means_empty_and_mcp_merge_is_explicit(source, monkeypatch):
    config = ModuleType("hermes_cli.tools_config")
    config.enabled_mcp_server_names = lambda _: {"mcp-unrelated"}
    config._get_platform_tools = lambda *_: ["terminal", "browser"]
    monkeypatch.setitem(sys.modules, config.__name__, config)
    namespace = {}
    path = source / "cron/scheduler.py"
    function(path, "_merge_mcp_into_per_job_toolsets", namespace)
    resolve = function(path, "_resolve_cron_enabled_toolsets", namespace)
    assert resolve({"enabled_toolsets": []}, {}) == []
    assert resolve({"enabled_toolsets": ["web"]}, {}) == ["web", "mcp-unrelated"]
    assert resolve({"enabled_toolsets": ["web", "no_mcp"]}, {}) == ["web"]
    def fail(*args):
        raise ValueError("synthetic config failure")
    config._get_platform_tools = fail
    with pytest.raises(RuntimeError, match="refused"):
        resolve({}, {})


def test_cron_constructor_loads_memory_even_without_workdir(source):
    capture = lambda **kwargs: kwargs
    namespace = {"_resolve_cron_enabled_toolsets": lambda *_: [],
                 "_resolve_cron_disabled_toolsets": lambda *_: ["messaging", "cronjob"]}
    construct = function(source / "cron/scheduler.py", "_construct_cron_agent", namespace)
    setup = SimpleNamespace(runtime={}, model="synthetic", max_iterations=2,
                            reasoning_config=None, prefill_messages=None, fallback_model=None,
                            credential_pool=None)
    agent = construct(capture, {"enabled_toolsets": []}, {}, setup,
                      workdir=None, session_id="synthetic", session_db=None)
    assert agent["enabled_toolsets"] == []
    assert agent["skip_context_files"] is True
    assert agent["skip_memory"] is False
    assert agent["load_soul_identity"] is True


@pytest.mark.parametrize("ok,changed", [(True, False), (True, True), (False, False)])
def test_monitor_gate_distinguishes_quiet_change_and_failure(source, monkeypatch, ok, changed):
    monitor = ModuleType("cron.monitor")
    monitor.job_has_monitor = lambda _: True
    monitor.check_monitor = lambda _: SimpleNamespace(ok=ok, changed=changed,
        error="synthetic read failure", context_block="untrusted observed data")
    monkeypatch.setitem(sys.modules, monitor.__name__, monitor)
    gate = function(source / "cron/scheduler.py", "_apply_monitor_gate", {
        "_hermes_now": lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
        "_job_doc_header": lambda *_: "synthetic header", "SILENT_MARKER": "[SILENT]",
        "logger": logging.getLogger(__name__)})
    early, prompt, context = gate({}, "synthetic-id", "synthetic-name", "owner instruction")
    assert prompt == "owner instruction"
    if not ok:
        assert early[0] is False
        assert early[3] == "synthetic read failure"
    elif changed:
        assert early is None
        assert context == "untrusted observed data"
    else:
        assert early[0] is True
        assert early[2] == "[SILENT]"


def test_jobs_http_does_not_accept_a_restricted_script_contract(source):
    calls = []
    create = function(source / "gateway/platforms/api_server.py", "_handle_create_job", {
        "web": SimpleNamespace(json_response=lambda body, **_: body),
        "_cron_create": lambda **kwargs: calls.append(kwargs) or {"id": "synthetic"},
        "_CronSchedulerRegistrationError": type("SchedulerError", (Exception,), {})})
    adapter = SimpleNamespace(_cron_request_guard=lambda _: (None, None), _MAX_NAME_LENGTH=100,
        _validate_cron_prompt=lambda _: None, _cron_origin_from_request=lambda _: None)
    async def body():
        return {"name": "synthetic", "schedule": "every 1h", "prompt": "test",
                "paused": True, "enabled_toolsets": [], "no_agent": True, "script": "/synthetic.py"}
    result = asyncio.run(create(adapter, SimpleNamespace(json=body)))
    assert result["job"]["id"] == "synthetic"
    assert calls[0]["paused"] is True
    assert "enabled_toolsets" not in calls[0]
    assert "no_agent" not in calls[0]
    assert "script" not in calls[0]


def test_http_adapter_has_no_outbound_delivery(source):
    send = function(source / "gateway/platforms/api_server.py", "send", {"SendResult": SimpleNamespace}, async_only=True)
    result = asyncio.run(send(None, "synthetic-chat", "Synthetic result"))
    assert result.success is False
    assert "request/response" in result.error


def test_messaging_helper_is_not_registered_for_agent_calls(source):
    tree = ast.parse((source / "tools/send_message_tool.py").read_text())
    registrations = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == "register"]
    assert registrations == []


def test_native_cron_paused_job_roundtrip_and_explicit_scope(source, isolated_home):
    from cron import jobs
    script = isolated_home / "synthetic.py"
    script.write_text("print('[SILENT]')\n")
    with jobs.use_cron_store(isolated_home / "native-cron"):
        created = jobs.create_job(prompt="", name="synthetic-radhouse-wake", schedule="every 1h",
            script=str(script), no_agent=True, enabled_toolsets=[], deliver="local", paused=True)
        saved = jobs.get_job(created["id"])
        assert saved["state"] == "paused"
        assert saved["enabled"] is False
        assert saved["next_run_at"] is None
        assert saved["no_agent"] is True
        assert saved["enabled_toolsets"] == []
        assert saved["script"] == str(script)
        assert saved["deliver"] == "local"
        resumed = jobs.resume_job(created["id"])
        assert resumed["enabled"] is True
        assert resumed["next_run_at"] is not None
        assert jobs.pause_job(created["id"])["enabled"] is False


def test_radhouse_provisioning_is_native_paused_idempotent_and_checks_effective_scope(source, isolated_home):
    spec = importlib.util.spec_from_file_location("native_commitment_worker_test", PACKAGE / "commitment_worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    from cron import jobs
    with jobs.use_cron_store(isolated_home / "native-cron"):
        first = worker.provision()
        assert first["enabled"] is False
        assert first["no_agent"] is True
        assert first["deliver"] == "local"
        assert worker.provision()["id"] == first["id"]
        assert len(jobs.list_jobs(include_disabled=True)) == 1
        assert worker.provision(activate=True)["enabled"] is True
        jobs.update_job(first["id"], {"enabled_toolsets": ["terminal"]})
        with pytest.raises(ValueError, match="scope_mismatch"):
            worker.provision(activate=True)
        assert jobs.get_job(first["id"])["enabled"] is False


def test_native_fire_claim_deduplicates_and_respects_pause(source, isolated_home):
    from cron import jobs
    with jobs.use_cron_store(isolated_home / "native-cron"):
        job = jobs.create_job(prompt="Synthetic purpose", name="synthetic", schedule="every 1h", paused=True)
        assert jobs.claim_job_for_fire(job["id"]) is False
        jobs.resume_job(job["id"])
        assert jobs.claim_job_for_fire(job["id"], manual=True) is True
        assert jobs.claim_job_for_fire(job["id"], manual=True) is False
        jobs.pause_job(job["id"])
        assert jobs.claim_job_for_fire(job["id"], manual=True) is False


def test_real_native_scheduler_executes_only_profile_script_and_keeps_config_locator(source, isolated_home, monkeypatch):
    from cron import scheduler, jobs
    home = Path(os.environ["HERMES_HOME"])
    scripts = home / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    script = scripts / "synthetic-wake.py"
    script.write_text("import os\nassert os.environ['RADHOUSE_COMMITMENT_WORKER_CONFIG']=='/synthetic/private-config.json'\nprint('[SILENT]')\n")
    monkeypatch.setenv("RADHOUSE_COMMITMENT_WORKER_CONFIG", "/synthetic/private-config.json")
    with jobs.use_cron_store(home):
        job = jobs.create_job(prompt="", name="synthetic-script", schedule="every 1h", script=str(script),
            no_agent=True, interpreter=sys.executable, enabled_toolsets=[], deliver="local", paused=True)
        success, _, response, error = scheduler.run_job(job)
        assert success is True
        assert response.strip() == "[SILENT]"
        assert error is None
        outside = isolated_home / "outside.py"
        outside.write_text("raise AssertionError('must not execute')\n")
        success, _, _, error = scheduler.run_job({**job, "script":str(outside)})
        assert success is False
        assert "outside the scripts directory" in error
