"""Exercise the pinned native admission/worker functions, not a second fake runtime."""
import asyncio
from contextlib import nullcontext, suppress
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import threading
from types import ModuleType, SimpleNamespace
from typing import Any, Callable, Dict, List, Optional
import uuid

import pytest

RUNTIME = Path(__file__).resolve().parents[1] / "runtime/hermes"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bridge = load("radhouse_hermes_bridge", RUNTIME / "bridge.py")
overlay = load("radhouse_hermes_overlay", RUNTIME / "overlay.py")


class Response:
    def __init__(self, value, status=200, headers=None):
        self.status, self.headers = status, headers or {}
        self.body = json.dumps(value).encode()

    @property
    def value(self):
        return json.loads(self.body)


@pytest.fixture(autouse=True)
def reset_bridge(monkeypatch):
    monkeypatch.setattr(bridge, "_callback", None)
    monkeypatch.setattr(bridge, "_browser_configuration", None)
    monkeypatch.setattr(bridge, "_maintenance_configuration", None)
    monkeypatch.setattr(bridge, "_network_policy", {"schema": "radhouse.browser-network-policy.v1", "verified": False,
        "source": None, "verified_at": None, "enforcement": "vm_firewall", "allowed": [], "denied": []})
    monkeypatch.setattr(bridge, "_relays", {})


class ReceiptStore:
    """Transport-independent receipt boundary; native handler computes the fingerprint."""
    durable = True

    def __init__(self):
        self.records = {}

    def lookup(self, scope, key, fingerprint, **kwargs):
        value = self.records.get((scope, key))
        return ("missing", None) if value is None else (
            "reused" if value[0] == fingerprint else "conflict", value[1])

    def reserve(self, scope, key, fingerprint, run_id, status, **kwargs):
        outcome, record = self.lookup(scope, key, fingerprint)
        if record is not None:
            return outcome, record
        record = {"run_id": run_id, "status": dict(status)}
        self.records[(scope, key)] = (fingerprint, record)
        return "created", record

    def update_status(self, run_id, status):
        pass


def native_namespace(monkeypatch):
    lock = json.loads((RUNTIME / "source-lock.json").read_text())
    raw = (RUNTIME / "fixtures/api_server_runs.snapshot").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == lock["files"]["gateway/platforms/api_server_runs.py"]["snapshot_sha256"]
    module = ModuleType("pinned_native_test_runs")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    context = {name: globals()[name] for name in ("asyncio", "suppress", "dataclass", "Any", "Callable", "Dict", "List", "Optional", "uuid", "hashlib", "json", "re")}
    context.update(time=__import__("time"), web=SimpleNamespace(json_response=Response),
        logger=SimpleNamespace(exception=lambda *args: None), TERMINAL_STATUSES={"completed", "failed", "cancelled"},
        _json_error=lambda factory, message, code=None, status=400: Response({"error": code or message}, status),
        _room_retention_until=lambda request: 0,
        _resolve_conversation_history=lambda *args, **kwargs: ([], None, None, None),
        _runtime_contract=SimpleNamespace(fresh_admission_error=lambda *args, **kwargs: None),
        resolve_profile_request_limit=lambda value: value,
        _configured_run_tools=lambda *args: None,
        _USAGE_FIELDS=(("input_tokens", "session_prompt_tokens"),))
    module.__dict__.update(context)
    exec(compile(overlay.patch_runs(raw.decode()), str(RUNTIME / "fixtures/api_server_runs.snapshot"), "exec"), module.__dict__)
    return module


def worker_dependencies(monkeypatch):
    for name in ("gateway", "gateway.session_context", "gateway.hosted_room_execution_policy", "tools", "tools.approval", "tools.approval_context"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    sys.modules["gateway.session_context"].clear_session_vars = lambda token: None
    sys.modules["gateway.hosted_room_execution_policy"].__dict__.update(
        RoomExecutionPolicy=SimpleNamespace(from_mapping=lambda x: x), bind_room_execution_policy=lambda x: None,
        reset_room_execution_policy=lambda token: None)
    sys.modules["tools.approval"].__dict__.update(register_gateway_notify=lambda *args: None, unregister_gateway_notify=lambda *args: None)
    approval = ContextVar("native_approval")
    sys.modules["tools.approval_context"].__dict__.update(set_current_session_key=approval.set, reset_current_session_key=approval.reset)


def adapter(native):
    value = SimpleNamespace(_run_idempotency_store=ReceiptStore(), _run_idempotency_ids=set(), _run_owners={},
        _run_statuses={}, _run_streams={}, _run_streams_created={}, _run_approval_sessions={}, _active_run_tasks={},
        _background_tasks=set(), _model_name="test", _run_owner_pid=1, _run_owner_started=1,
        _parse_session_key_header=lambda request: (None, None), _run_idempotency_scope=lambda request: "test-owner",
        _resolve_route=lambda model: None, _request_route_conflict_error=lambda **kwargs: None,
        _concurrency_limited_response=lambda: None, _conversation_history_for_session=lambda session: asyncio.sleep(0, result=[]),
        _declared_conversation_session=lambda key: None, _activate_admitted_request=lambda: None,
        _profile_scope=lambda profile: nullcontext(), _bind_api_server_session=lambda **kwargs: None,
        _bind_declared_conversation=lambda *args: None,
        _durable_run_status=lambda request, run_id: None)
    async def normalize(request, body):
        return body, None
    value._normalize_room_dispatch = normalize
    value._set_run_status = lambda *args, **kwargs: native._set_run_status(value, *args, **kwargs)
    return value


def request(body, key="dispatch1"):
    async def read():
        return dict(body)
    return SimpleNamespace(json=read, headers={"Idempotency-Key": key}, path="/v1/runs")


def api_dependencies():
    return SimpleNamespace(_openai_error=None, _api_request_profile=ContextVar("testprofile", default="profile"),
        _api_request_browser_control_principal=ContextVar("testprincipal", default=None),
        _api_request_browser_control_transport_family=ContextVar("testtransport", default=None),
        _request_agent_overrides=lambda *args, **kwargs: {}, _publish_turn_process_ownership=lambda *args: None,
        _clear_turn_process_ownership=lambda *args: None)


def test_native_admission_receipt_precedes_first_tool_and_private_token_fingerprint(monkeypatch):
    native = native_namespace(monkeypatch)
    worker_dependencies(monkeypatch)
    value, api, seen = adapter(native), api_dependencies(), []
    monkeypatch.setattr(bridge, "_callback", object())
    token = "a" * 43
    body = {"input": "question", "session_id": "chat1", "allowed_tools": list(bridge.DOCUMENT_TOOLS), "document_scope_token": token}
    class Agent:
        def run_conversation(self, **kwargs):
            context = bridge.current_run_context(task_id=kwargs["task_id"], documents=True)
            status = value._run_statuses[context.run_id]
            assert status["dispatch_key"] == "dispatch1" and status["session_id"] == "chat1"
            assert status["allowed_tools"] == list(bridge.DOCUMENT_TOOLS)
            assert token not in json.dumps(status)
            seen.append(context)
            return "done"
    async def execute(owner, launch, **kwargs):
        assert token not in repr(launch) and token not in json.dumps(launch.agent_kwargs)
        return await asyncio.to_thread(native._run_agent_sync, owner, launch, Agent(), None, _api_server=api)
    native._execute_run = execute
    async def run():
        response = await native._handle_runs(value, request(body), _api_server=api)
        assert response.status == 202
        await asyncio.gather(*value._active_run_tasks.values())  # Before delivering acknowledgement to client.
        assert seen and bridge._context.get() is None
        replay = await native._handle_runs(value, request(body), _api_server=api)
        assert replay.status == 202 and replay.value["replayed"] is True
        conflict = await native._handle_runs(value, request({**body, "document_scope_token": "b" * 43}), _api_server=api)
        assert conflict.status == 409 and conflict.value["error"] == "idempotency_key_conflict"
        assert len(value._active_run_tasks) == 1
    asyncio.run(run())


def test_native_worker_resets_context_after_exception(monkeypatch):
    native = native_namespace(monkeypatch)
    worker_dependencies(monkeypatch)
    value, api = adapter(native), api_dependencies()
    launch = native._RunLaunch(value, "run1", None, "chat1", None, False, "question", [],
        {"allowed_tools": list(bridge.DOCUMENT_TOOLS), "room_dispatch": None}, None, None, None, "dispatch1", "a" * 48)
    class Agent:
        def run_conversation(self, **kwargs):
            assert bridge.current_run_context().run_id == "run1"
            raise RuntimeError("private parser failure")
    with pytest.raises(RuntimeError):
        native._run_agent_sync(value, launch, Agent(), None, _api_server=api)
    with pytest.raises(ValueError):
        bridge.current_run_context()


def test_document_schema_catalog_continuation_and_private_error_redaction(monkeypatch):
    calls = []
    class Callback:
        def post(self, operation, context, arguments):
            calls.append((operation, context, arguments))
            return {"kind": "catalog", "files": [], "next_cursor": None, "complete": True}
    monkeypatch.setattr(bridge, "_callback", Callback())
    token = bridge.bind_run_context("run1", "chat1", "dispatch1", "secret-private-token")
    try:
        assert json.loads(bridge.document_handler("read", {"cursor": "catalog-page2"}, task_id="chat1"))["kind"] == "catalog"
        assert calls[0][2] == {"cursor": "catalog-page2"}
        assert json.loads(bridge.document_handler("read", {}, task_id="other")) == {"error": "document_access_unavailable"}
        assert len(calls) == 1
        assert json.loads(bridge.document_handler("read", {"locator": "page1"})) == {"error": "document_access_unavailable"}
    finally:
        bridge.reset_run_context(token)
    monkeypatch.setenv("HERMES_SESSION_ID", "chat1")
    assert json.loads(bridge.document_handler("read", {})) == {"error": "document_access_unavailable"}


def test_concurrent_copied_thread_context_does_not_mix_scopes():
    raw = (RUNTIME / "fixtures/thread_context.snapshot").read_bytes()
    lock = json.loads((RUNTIME / "source-lock.json").read_text())
    assert hashlib.sha256(raw).hexdigest() == lock["files"]["tools/thread_context.py"]["snapshot_sha256"]
    namespace = {}
    exec(compile(raw, "pinned-native-thread-context", "exec"), namespace)
    snapshots, answers = [], []
    for number in (1, 2):
        token = bridge.bind_run_context(f"run{number}", f"chat{number}", f"dispatch{number}", f"scope{number}")
        snapshots.append(namespace["propagate_context_to_thread"])
        snapshots[-1] = snapshots[-1](lambda: read())
        bridge.reset_run_context(token)
    barrier = threading.Barrier(2)
    def read():
        barrier.wait(timeout=2)
        answers.append(bridge.current_run_context())
    threads = [threading.Thread(target=target) for target in snapshots]
    for thread in threads: thread.start()
    for thread in threads: thread.join(3)
    assert {item.run_id: item.scope_token for item in answers} == {"run1": "scope1", "run2": "scope2"}
    assert bridge._context.get() is None


def test_maintenance_gate_is_before_native_first_await(monkeypatch):
    # Execute the original decorated-admission body transformed by the same exact patch.
    raw = (RUNTIME / "fixtures/api_server.snapshot").read_text()
    lock = json.loads((RUNTIME / "source-lock.json").read_text())
    assert hashlib.sha256(raw.encode()).hexdigest() == lock["files"]["gateway/platforms/api_server.py"]["snapshot_sha256"]
    patched = overlay.patch_api(raw)
    import ast
    tree = ast.parse(patched)
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_admit_api_agent_request")
    namespace = {"wraps": __import__("functools").wraps,
        "_api_runs": SimpleNamespace(_uses_room_run_auth=lambda *args: False),
        "_error_response": lambda message, status, **kwargs: Response({"error": kwargs["code"]}, status),
        "_api_agent_request_reservation": ContextVar("reservation"),
        "_release_pending_api_work": lambda self, reservation: setattr(self, "_pending_agent_requests", self._pending_agent_requests - 1)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "pinned-native-admission", "exec"), namespace)
    monkeypatch.setattr(bridge, "maintenance_held", lambda: True)
    value = SimpleNamespace(_check_auth=lambda request: None, _pending_agent_requests=0,
        _draining_response=lambda: None)
    async def handler(*args):
        pytest.fail("held runtime reached first await")
    response = asyncio.run(namespace["_admit_api_agent_request"](handler)(value, request({})))
    assert response.status == 503 and value._pending_agent_requests == 0


def test_firewall_information_is_unverified_by_default_and_not_a_url_permission():
    value = SimpleNamespace(_run_idempotency_store=ReceiptStore())
    assert bridge.features(value)["browser_network_policy"]["verified"] is False
    assert bridge.http_url("http://192.168.50.66:8443/status")
    assert not bridge.http_url("file:///etc/passwd") and not bridge.http_url("https://user:password@example.com")
    policy = {"schema": "radhouse.browser-network-policy.v1", "verified": True, "source": "VM270 firewall snapshot",
        "verified_at": "2026-10-07T12:00:00+00:00", "enforcement": "vm_firewall", "allowed": ["Configured LAN destinations"], "denied": []}
    bridge.configure_network_policy(policy)
    prompt = bridge.trusted_browser_instructions("base instructions", bridge.BROWSER_TOOLS)
    assert "not permission" in prompt and "VM270 firewall snapshot" in prompt
    assert bridge.trusted_browser_instructions("base instructions", bridge.DOCUMENT_TOOLS) == "base instructions"
    with pytest.raises(ValueError):
        bridge.configure_network_policy({**policy, "verified_at": None})
    with pytest.raises(ValueError):
        bridge.configure_network_policy({**policy, "allowed": ["LAN café"]})
    from datetime import datetime, timedelta, timezone
    with pytest.raises(ValueError):
        bridge.configure_network_policy({**policy, "verified_at": (datetime.now(timezone.utc) + timedelta(minutes=6)).isoformat()})


def test_failed_plugin_setup_cannot_advertise_partial_document_configuration(monkeypatch):
    monkeypatch.setattr(bridge, "_register", lambda ctx: (setattr(bridge, "_callback", object()), (_ for _ in ()).throw(ValueError("private path"))))
    with pytest.raises(ValueError, match="radhouse_plugin_configuration_unverified"):
        bridge.register(object())
    assert bridge._callback is None
    assert bridge.features(SimpleNamespace(_run_idempotency_store=ReceiptStore()))["runs_document_scope"]["supported"] is False


def test_native_child_environment_cannot_inherit_credentials_or_browser_profile(monkeypatch):
    monkeypatch.setattr(bridge, "_browser_configuration", {"chromium_path": "/fixed/chrome", "agent_browser_path": "/fixed/browser", "empty_config_path": "/fixed/empty.json"})
    token = bridge.bind_run_context("run1", "chat1", "dispatch1", None)
    try:
        clean = bridge.browser_environment({"PATH": "/usr/bin", "HOME": "/home/bot", "OPENAI_API_KEY": "secret",
            "DOCUMENT_SCOPE_TOKEN": "private", "AGENT_BROWSER_ARGS": "--no-sandbox", "AGENT_BROWSER_PROFILE": "/private/profile"})
        assert set(clean) == {"PATH", "HOME", "AGENT_BROWSER_EXECUTABLE_PATH", "AGENT_BROWSER_ARGS"}
        assert "secret" not in json.dumps(clean) and "--no-sandbox" not in json.dumps(clean)
        assert bridge.browser_argv() == ["/fixed/browser", "--config", "/fixed/empty.json", "--executable-path", "/fixed/chrome"]
    finally:
        bridge.reset_run_context(token)


def test_browser_arguments_cannot_override_native_options_and_text_remains_literal(monkeypatch):
    tools = ModuleType("tools")
    tools.browser_tool = SimpleNamespace(_cloud=SimpleNamespace(_is_local_mode=lambda: True))
    monkeypatch.setitem(sys.modules, "tools", tools)
    monkeypatch.setattr(bridge, "_browser_configuration", {})
    token = bridge.bind_run_context("run1", "chat1", "dispatch1", None)
    seen = []
    try:
        for args in ({"ref": "--profile", "text": "safe"}, {"ref": "@e1", "text": "safe", "cdp": "ws://private"}):
            result = bridge.checked_browser_call("browser_type", args, {"task_id": "chat1"}, lambda: seen.append(args))
            assert json.loads(result) == {"error": "browser_access_unavailable"}
        result = bridge.checked_browser_call("browser_type", {"ref": "@e1", "text": "--config"},
                                             {"task_id": "chat1"}, lambda: "literal-text")
        assert result == "literal-text" and seen == []
    finally:
        bridge.reset_run_context(token)


def test_stationary_native_relay_retains_frame_with_unknown_capture_time(monkeypatch):
    async def idle(self):
        await asyncio.Event().wait()
    monkeypatch.setattr(bridge.NativeRelay, "listen", idle)
    async def run():
        relay = bridge.NativeRelay("chat1", 8123, "generation1")
        relay.ingest({"type": "status", "connected": True, "screencasting": True})
        relay.ingest({"type": "tabs", "tabs": [{"active": True, "url": "https://example.com/page?secret=1"}]})
        relay.ingest({"type": "frame", "data": __import__("base64").b64encode(b"\xff\xd8\xffactual-frame").decode(), "metadata": {"timestamp": 0}})
        first = await relay.snapshot(True)
        second = await relay.snapshot(True)
        assert first == second and first["captured_at"] is None and first["received_at"] > 0
        assert first["url"] == "https://example.com/page"
        relay.ingest({"type": "url", "url": "http://192.168.50.65/second?token=hidden"})
        assert relay.url == "http://192.168.50.65/second" and relay.frame is None
        relay.ingest({"type": "frame", "data": __import__("base64").b64encode(b"\xff\xd8\xffsecond-frame").decode()})
        assert (await relay.snapshot(True))["frame_id"] != first["frame_id"]
        relay.ingest({"type": "status", "connected": False})
        assert relay.frame is None
        relay.task.cancel()
        with suppress(asyncio.CancelledError): await relay.task
    asyncio.run(run())


def test_overlay_refuses_modified_source_and_preserves_existing_controls(tmp_path):
    with pytest.raises((ValueError, FileNotFoundError)):
        overlay.render(tmp_path)
    raw = (RUNTIME / "fixtures/api_server_runs.snapshot").read_text()
    patched = overlay.patch_runs(raw)
    assert "allowed_tools_not_configured" in patched and "provider_request_budget_requires_idempotency" in patched
    assert "_runtime_contract.fresh_admission_error" in patched and '"body": body' in patched
    with pytest.raises(ValueError):
        overlay.patch_runs(patched)


def test_declared_unchanged_thread_source_is_verified_and_passed_through(tmp_path, monkeypatch):
    raw = (RUNTIME / "fixtures/thread_context.snapshot").read_bytes()
    declaration = {"files": {"tools/thread_context.py": {"before_sha256": hashlib.sha256(raw).hexdigest()}}}
    package, source = tmp_path / "package", tmp_path / "source"
    package.mkdir()
    (package / "source-lock.json").write_text(json.dumps(declaration))
    (source / "tools").mkdir(parents=True)
    monkeypatch.setattr(overlay, "PACKAGE", package)
    with pytest.raises(FileNotFoundError):
        overlay.render(source)
    target = source / "tools/thread_context.py"
    target.write_bytes(raw + b"\n# modified propagation\n")
    with pytest.raises(ValueError, match="hermes_overlay_source_mismatch"):
        overlay.render(source)
    target.write_bytes(raw)
    result = overlay.render(source)
    assert result == {"tools/thread_context.py": raw.decode()}
    # write() must include the passthrough in its install map, too.
    (package / "bridge.py").write_text("# bridge source\n")
    (package / "plugin").mkdir()
    for name in ("__init__.py", "plugin.yaml"):
        (package / "plugin" / name).write_text("# plugin source\n")
    manifest = overlay.write(source, tmp_path / "rendered")
    assert manifest["tools/thread_context.py"] == hashlib.sha256(raw).hexdigest()


def test_grant_admission_requires_exact_frozen_bearer_and_both_tools(monkeypatch):
    monkeypatch.setattr(bridge, "_callback", object())
    body = {"session_id": "chat1", "allowed_tools": list(bridge.DOCUMENT_TOOLS), "document_scope_token": "a" * 43}
    assert bridge.validate_admission(body, "dispatch1", True) is None
    assert bridge.validate_admission({**body, "document_scope_token": "a" * 42}, "dispatch1", True) == "invalid_document_scope"
    assert bridge.validate_admission({**body, "allowed_tools": ["document_read"]}, "dispatch1", True) == "document_scope_unavailable"
    assert bridge.validate_admission({**body, "allowed_tools": [*bridge.DOCUMENT_TOOLS, "terminal"]}, "dispatch1", True) == "document_scope_unavailable"
    assert bridge.validate_admission(body, "", True) == "document_scope_unavailable"
    monkeypatch.setattr(bridge, "_browser_configuration", {})
    browser = {"session_id": "chat1", "allowed_tools": ["browser_navigate", "terminal"]}
    assert bridge.validate_admission(browser, "dispatch1", True) == "browser_scope_unavailable"


def test_malformed_or_drifted_persistent_hold_stops_new_admission(monkeypatch):
    monkeypatch.setattr(bridge, "_hold", lambda: (_ for _ in ()).throw(ValueError("changed-root-policy")))
    assert bridge.maintenance_held() is True
    monkeypatch.setattr(bridge, "_hold", lambda: ({"cycle_id": "c" * 32, "boot_id": "previous-boot"}, "digest"))
    assert bridge.maintenance_held() is True  # A restart/reboot never clears the file gate.
    monkeypatch.setattr(bridge, "_hold", lambda: (None, None))
    assert bridge.maintenance_held() is False


def test_maintenance_producer_timestamp_matches_strict_operator_iso_schema(monkeypatch):
    from datetime import datetime, timezone
    tools = ModuleType("tools")
    tools.browser_tool = SimpleNamespace(_cleanup_lock=threading.Lock(), _active_sessions={})
    monkeypatch.setitem(sys.modules, "tools", tools)
    monkeypatch.setattr(bridge, "_hold", lambda: ({"cycle_id": "a" * 32}, "hold-digest"))
    monkeypatch.setattr(bridge, "_maintenance_configuration", ("b" * 64, "c" * 64))
    value = SimpleNamespace(_pending_agent_requests=0, _inflight_agent_runs=0, _active_run_tasks={})
    response = bridge.maintenance_status(value)
    checked = datetime.fromisoformat(response["checked_at"])
    assert checked.tzinfo is not None and abs((datetime.now(timezone.utc) - checked).total_seconds()) < 1
    assert response["active_runs"] == response["active_browsers"] == 0 and response["verified"] is True


def test_bootstrap_promotes_only_real_isolation_proof_and_unwraps_cycle_receipt(tmp_path, monkeypatch):
    bootstrap = load("radhouse_browser_bootstrap_test", RUNTIME / "bootstrap.py")
    selected = {"release_id": "a" * 32, "manifest_path": "fixed", "manifest_sha256": "b" * 64}
    manifest = {"agent_browser_version": "0.38.2", "agent_browser_sha256": "c" * 64,
        "chromium_sha256": "d" * 64, "runtime_sha256": "e" * 64}
    record = {"candidate": {"state": "staged", "candidate": selected}, "qualification": {"state": "qualified",
        **manifest, "same_session_frame_progression": True, "sandbox_enabled": False, "origin_guard_verified": True,
        "view_only_input_ignored": True, "chrome_control_guard_verified": True, "candidate": selected}}
    monkeypatch.setattr(bootstrap.os, "geteuid", lambda: 0)
    monkeypatch.setattr(bootstrap, "candidate", lambda item, policy: (tmp_path, manifest))
    assert bootstrap.staged_candidate(record) == selected
    with pytest.raises(ValueError, match="browser_qualification_unverified"):
        bootstrap.promote(record, {"runtime_sha256": "e" * 64})
    record["qualification"]["sandbox_enabled"] = True
    record["qualification"]["origin_guard_verified"] = False
    with pytest.raises(ValueError, match="browser_qualification_unverified"):
        bootstrap.promote(record, {"runtime_sha256": "e" * 64})
    record["qualification"]["origin_guard_verified"] = True
    record["qualification"]["chrome_control_guard_verified"] = False
    with pytest.raises(ValueError, match="browser_qualification_unverified"):
        bootstrap.promote(record, {"runtime_sha256": "e" * 64})
    assert not (tmp_path / "qualification.json").exists()


def test_chrome_control_endpoint_is_only_resolved_from_owned_daemon_descendants(tmp_path, monkeypatch):
    import os
    bootstrap = load("radhouse_browser_bootstrap_endpoint_test", RUNTIME / "bootstrap.py")
    proc, profile = tmp_path / "proc", tmp_path / "owned-profile"
    profile.mkdir(mode=0o700)
    (profile / "DevToolsActivePort").write_text("34567\n/devtools/browser/12345678-abcd\n")
    monkeypatch.setattr(bootstrap, "_PROC_ROOT", proc)
    chrome = tmp_path / "pinned-chrome"
    chrome.touch()
    def process(pid, executable, children, arguments):
        root = proc / str(pid)
        (root / "task" / str(pid)).mkdir(parents=True)
        (root / "exe").symlink_to(executable)
        (root / "cmdline").write_bytes(b"\0".join(arguments) + b"\0")
        (root / "status").write_text(f"Uid:\t{os.geteuid()} {os.geteuid()} {os.geteuid()} {os.geteuid()}\n")
        (root / "task" / str(pid) / "children").write_text(children)
    process(10, tmp_path / "native", "", [b"native"])
    worker = proc / "10/task/12"
    worker.mkdir()
    (worker / "children").write_text("11")  # Tokio spawns Chrome from a worker thread.
    process(11, chrome, "13", [bytes(chrome), b"--user-data-dir=" + bytes(profile)])
    process(13, chrome, "", [bytes(chrome), b"--type=renderer"])
    for pid, namespace in ((10, "pid:[1]"), (11, "pid:[1]"), (13, "pid:[2]")):
        (proc / str(pid) / "ns").mkdir()
        (proc / str(pid) / "ns/pid").symlink_to(namespace)
    (proc / "13/status").write_text(f"Uid:\t{os.geteuid()}\nSeccomp:\t2\nNoNewPrivs:\t1\n")
    process(99, chrome, "", [bytes(chrome), b"--user-data-dir=" + bytes(profile)])
    assert bootstrap.owned_chrome_endpoint(10, chrome) == "http://127.0.0.1:34567/devtools/browser/12345678-abcd"
    monkeypatch.setattr(bootstrap.sys, "platform", "linux")
    assert bootstrap.sandbox_evidence(10, chrome) is True
    (worker / "children").write_text("")
    with pytest.raises(ValueError, match="browser_chrome_identity_unverified"):
        bootstrap.owned_chrome_endpoint(10, chrome)  # Same executable elsewhere is never discovered.
    assert bootstrap.sandbox_evidence(10, chrome) is False
    (worker / "children").write_text("11")
    profile.chmod(0o755)
    with pytest.raises(ValueError, match="browser_chrome_identity_unverified"):
        bootstrap.owned_chrome_endpoint(10, chrome)
    profile.chmod(0o700)
    endpoint = profile / "DevToolsActivePort"
    endpoint.unlink()
    endpoint.symlink_to(tmp_path / "unrelated-endpoint")
    with pytest.raises(OSError):
        bootstrap.owned_chrome_endpoint(10, chrome)


def test_owned_process_children_stops_at_thread_and_process_bounds(tmp_path):
    bootstrap = load("radhouse_browser_bootstrap_child_bounds_test", RUNTIME / "bootstrap.py")
    tasks = tmp_path / "task"
    tasks.mkdir()
    for number in range(1, 130):
        (tasks / str(number)).mkdir()
        (tasks / str(number) / "children").write_text("")
    with pytest.raises(ValueError, match="browser_process_identity_unverified"):
        bootstrap.owned_process_children(tmp_path)
    for number in (128, 129):
        (tasks / str(number) / "children").unlink()
        (tasks / str(number)).rmdir()
    (tasks / "1/children").write_text(" ".join(map(str, range(1, 66))))
    with pytest.raises(ValueError, match="browser_process_identity_unverified"):
        bootstrap.owned_process_children(tmp_path)


@pytest.mark.parametrize("contents", ["80\n/devtools/browser/12345678\n", "34567\n/devtools/page/12345678\n",
    "34567\n/devtools/browser/12345678\nextra\n", "34567\n/devtools/browser/" + "a" * 500])
def test_chrome_control_endpoint_rejects_malformed_native_endpoint(tmp_path, monkeypatch, contents):
    import os
    bootstrap = load("radhouse_browser_bootstrap_bad_endpoint_test", RUNTIME / "bootstrap.py")
    proc, profile = tmp_path / "proc", tmp_path / "owned-profile"
    profile.mkdir(mode=0o700)
    (profile / "DevToolsActivePort").write_text(contents)
    root = proc / "10"
    root.mkdir(parents=True)
    chrome = tmp_path / "pinned-chrome"
    (root / "exe").symlink_to(chrome)
    (root / "cmdline").write_bytes(bytes(chrome) + b"\0--user-data-dir=" + bytes(profile) + b"\0")
    (root / "status").write_text(f"Uid:\t{os.geteuid()}\n")
    monkeypatch.setattr(bootstrap, "_PROC_ROOT", proc)
    with pytest.raises(ValueError, match="browser_chrome_identity_unverified"):
        bootstrap.owned_chrome_endpoint(10, chrome)


def test_bootstrap_verify_runs_bot_canary_after_package_or_reboot_changes(monkeypatch):
    bootstrap = load("radhouse_browser_bootstrap_verify_test", RUNTIME / "bootstrap.py")
    selected = {"release_id": "a" * 32, "manifest_path": "fixed", "manifest_sha256": "b" * 64}
    calls = []
    monkeypatch.setattr(bootstrap.os, "geteuid", lambda: 0)
    monkeypatch.setattr(bootstrap, "current_receipt", lambda: selected)
    monkeypatch.setattr(bootstrap, "candidate", lambda item, policy: (Path("fixed"), {}))
    def execute(argv, payload):
        calls.append((argv, json.loads(payload)))
        return b'{"state":"qualified","sandbox_enabled":true}'
    monkeypatch.setattr(bootstrap, "qualification_output", execute)
    result = bootstrap.verify({}, {"runtime_sha256": "e" * 64, "hermes_python": "/pinned/venv/python"})
    assert result["state"] == "verified"
    assert calls[0][0][:4] == ["/usr/sbin/runuser", "-u", "radhousebot", "--"]
    assert "maintenance-qualify" in calls[0][0] and calls[0][1] == {"candidate": selected}


def test_qualification_observation_timeout_waits_for_child_finally(tmp_path):
    bootstrap = load("radhouse_browser_qualification_cleanup_test", RUNTIME / "bootstrap.py")
    marker = tmp_path / "finally-finished"
    script = ("import pathlib,time\ntry:\n time.sleep(0.06)\n"
              "finally:\n pathlib.Path(__import__('sys').argv[1]).write_text('cleaned')\n")
    with pytest.raises(ValueError, match="browser_qualification_observation_interrupted"):
        bootstrap.qualification_output([sys.executable, "-I", "-c", script, str(marker)], b"{}", timeout=0.001)
    assert marker.read_text() == "cleaned"


def test_qualification_repeated_termination_is_deferred_until_native_exit(monkeypatch):
    bootstrap = load("radhouse_browser_qualification_signal_test", RUNTIME / "bootstrap.py")
    handlers, originals, waits = {}, {}, []
    def install(sig, handler):
        before = handlers.get(sig, "original")
        if sig not in originals:
            originals[sig] = before
        handlers[sig] = handler
        return before
    class Canary:
        returncode = None
        pid = 123
        def wait(self, timeout):
            waits.append(timeout)
            for sig in (bootstrap.signal.SIGTERM, bootstrap.signal.SIGINT):
                handlers[sig](sig, None)
            raise bootstrap.subprocess.TimeoutExpired("fixed-canary", timeout)
        def poll(self):
            pytest.fail("fallback must not depend on Popen polling")
        def kill(self):
            pytest.fail("canary must not be killed")
        def terminate(self):
            pytest.fail("canary must not be terminated")
    child = Canary()
    def reap(pid, options):
        assert (pid, options) == (123, 0)
        waits.append("native-reap")
        for sig in (bootstrap.signal.SIGTERM, bootstrap.signal.SIGINT):
            handlers[sig](sig, None)
        if len(waits) < 3:
            raise OSError("failed observation")
        return pid, 0
    monkeypatch.setattr(bootstrap.signal, "signal", install)
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda *args, **kwargs: child)
    monkeypatch.setattr(bootstrap.os, "waitpid", reap)
    with pytest.raises(ValueError, match="browser_qualification_observation_interrupted"):
        bootstrap.qualification_output(["fixed-canary"], b"{}", timeout=0.01)
    assert child.returncode == 0 and len(waits) == 3
    assert handlers == originals


def test_qualification_failed_wait_still_reaps_real_child_cleanup(tmp_path, monkeypatch):
    bootstrap = load("radhouse_browser_qualification_wait_failure_test", RUNTIME / "bootstrap.py")
    marker = tmp_path / "finally-finished"
    real_process = bootstrap.subprocess.Popen
    class BrokenObserver(real_process):
        def wait(self, timeout=None):
            raise RuntimeError("diagnostic wait failed")
        def poll(self):
            pytest.fail("fallback must not depend on Popen polling")
    monkeypatch.setattr(bootstrap.subprocess, "Popen", BrokenObserver)
    script = ("import pathlib,time\ntry:\n time.sleep(0.04)\n"
              "finally:\n pathlib.Path(__import__('sys').argv[1]).write_text('cleaned')\n")
    with pytest.raises(ValueError, match="browser_qualification_observation_interrupted"):
        bootstrap.qualification_output([sys.executable, "-I", "-c", script, str(marker)], b"{}")
    assert marker.read_text() == "cleaned"


@pytest.mark.parametrize("arrives_during", ["stdout_read", "handler_restore"])
def test_qualification_rejects_signals_after_native_exit(monkeypatch, arrives_during):
    import io
    bootstrap = load("radhouse_browser_qualification_late_signal_test", RUNTIME / "bootstrap.py")
    handlers = {}
    files = []
    class Output(io.BytesIO):
        def read(self, *args):
            if self is files[1] and arrives_during == "stdout_read":
                handlers[bootstrap.signal.SIGTERM](bootstrap.signal.SIGTERM, None)
            return super().read(*args)
    def temporary_file():
        stream = Output()
        files.append(stream)
        return stream
    def install(sig, handler):
        previous = handlers.get(sig, "original")
        if handler == "original" and sig == bootstrap.signal.SIGINT and arrives_during == "handler_restore":
            handlers[bootstrap.signal.SIGTERM](bootstrap.signal.SIGTERM, None)
        handlers[sig] = handler
        return previous
    def completed(argv, **kwargs):
        kwargs["stdout"].write(b'{"state":"qualified","sandbox_enabled":true}')
        return SimpleNamespace(returncode=0, wait=lambda **kwargs: None)
    monkeypatch.setattr(bootstrap.tempfile, "TemporaryFile", temporary_file)
    monkeypatch.setattr(bootstrap.signal, "signal", install)
    monkeypatch.setattr(bootstrap.subprocess, "Popen", completed)
    with pytest.raises(ValueError, match="browser_qualification_observation_interrupted"):
        bootstrap.qualification_output(["fixed-canary"], b"{}")
    assert set(handlers.values()) == {"original"}


@pytest.mark.parametrize("script", ["import sys;sys.stdout.buffer.write(b'x'*65537)", "raise SystemExit(1)"])
def test_qualification_output_rejects_failure_and_oversized_result(script):
    bootstrap = load("radhouse_browser_qualification_result_test", RUNTIME / "bootstrap.py")
    with pytest.raises(ValueError, match="browser_current_qualification_failed"):
        bootstrap.qualification_output([sys.executable, "-I", "-c", script], b"{}")
