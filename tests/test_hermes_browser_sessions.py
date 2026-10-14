"""Session integration with exact upstream handlers and one real disposable Unix ACK channel."""

import asyncio
import hashlib
import json
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, Optional
from uuid import uuid4

import pytest

from tests.test_browser_control import control
from tests.test_hermes_runtime_bridge import (
    RUNTIME,
    Response,
    adapter,
    api_dependencies,
    bridge,
    native_namespace,
    overlay,
    request,
    worker_dependencies,
)
from tests.test_native_control import Executor, native, success


@pytest.fixture
def session(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "radhouse_browser_control", control)
    monkeypatch.setitem(sys.modules, "radhouse_native_control", native)
    aiohttp = ModuleType("aiohttp")
    aiohttp.web = SimpleNamespace(json_response=Response)
    monkeypatch.setitem(sys.modules, "aiohttp", aiohttp)
    c = control.BrowserController(
        tmp_path / "browser.sqlite3", maintenance_held=lambda: False
    )
    monkeypatch.setattr(bridge, "_controller", c)
    monkeypatch.setattr(bridge, "_vault", None)
    monkeypatch.setattr(bridge, "_owned_browsers", {})
    monkeypatch.setattr(bridge, "_relays", {})
    monkeypatch.setattr(bridge, "_browser_configuration", {"qualified": True})
    monkeypatch.setattr(bridge, "maintenance_held", lambda: False)
    monkeypatch.setattr(bridge, "_callback", object())
    monkeypatch.setattr(bridge, "_redacted", lambda value: value)
    browser = ModuleType("tools.browser_tool")
    tools = ModuleType("tools")
    browser._cloud = SimpleNamespace(_is_local_mode=lambda: True)
    browser._cleanup_lock = threading.RLock()
    browser._active_sessions = {}
    tools.browser_tool = browser
    lifecycle = ModuleType("tools.browser_tool_lifecycle")
    touches = []
    released = []
    lifecycle._update_session_activity = lambda sid: touches.append(sid)
    lifecycle._release_session_resources = lambda sid, record: released.append(sid)
    tools.browser_tool_lifecycle = lifecycle
    for module in (tools, browser, lifecycle):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    owner = control.OwnerBinding("alice", "a" * 64, 1, "tab-1")
    identity = control.BrowserIdentity("conversation", "session", "generation-1")
    run = control.RunBinding("old-run", "session", "old-dispatch")

    def respond(command):
        data = {"connected": True}
        if command["action"] == "evaluate":
            script = command["script"]
            data = {
                "result": False
                if script.startswith("Array.from")
                else (
                    "https://fixture.invalid"
                    if script == "location.origin"
                    else {
                        "url": "https://fixture.invalid/page?secret=omitted",
                        "title": "Fixture",
                        "width": 1280,
                        "height": 720,
                    }
                )
            }
        elif command["action"] == "navigate":
            data = {"url": command["url"], "title": "Fixture"}
        elif command["action"] == "back":
            data = {"url": "https://fixture.invalid/previous"}
        elif command["action"] == "snapshot":
            data = {"snapshot": "textbox [ref=e1]", "refs": {"e1": {"role": "textbox"}}}
        return success(command, data)

    executor = Executor(respond)
    owned = bridge.OwnedBrowser(identity, {}, 1234, 123.0, executor.connect())
    monkeypatch.setattr(bridge, "_pid_gone", lambda pid, started: False)
    monkeypatch.setattr(
        bridge,
        "_session_stream",
        lambda sid: (
            (23000, identity.generation) if sid in bridge._owned_browsers else None
        ),
    )

    def bind(run=run):
        c.bind_browser(
            identity,
            run,
            owner.principal_id,
            native_name="h_0123456789",
            native_pid=1234,
            native_started=123.0,
        )
        bridge._owned_browsers["session"] = owned
        return c.state(identity)

    def human():
        state = c.state(identity)
        state = c.request_takeover(
            identity,
            owner,
            "take-1",
            revision=state.revision,
            auth_expires_at=time.time() + 600,
        )
        return bridge._fence_takeover(owned, state)

    def body(state=None):
        state = state or c.state(identity)
        return {
            "owner": {
                "principal_id": owner.principal_id,
                "conversation_id": identity.conversation_id,
                "auth_session_digest": owner.auth_session_digest,
                "binding_revision": owner.binding_revision,
                "tab_id": owner.tab_id,
            },
            "auth_expires_at": time.time() + 600,
            "generation": identity.generation,
            "revision": state.revision,
            "lease_id": state.lease.lease_id if state.lease else None,
        }

    async def frame(*args, **kw):
        return {
            "url": "https://fixture.invalid/page",
            "jpeg": "jpeg",
            "frame_id": "frame-1",
            "received_at": time.time(),
            "captured_at": time.time(),
        }

    monkeypatch.setattr(bridge, "_native_frame", frame)
    value = SimpleNamespace(
        _check_auth=lambda req: None,
        _run_statuses={"old-run": {"session_id": "session", "status": "completed"}},
        _run_idempotency_scope=lambda req: "owner",
    )

    def call(operation, body=None):
        payload = body or {
            "owner": {
                "principal_id": "alice",
                "conversation_id": "conversation",
                "auth_session_digest": "a" * 64,
                "binding_revision": 1,
                "tab_id": "tab-1",
            },
            "auth_expires_at": time.time() + 600,
        }
        req = request(payload)
        req.match_info = {"session_id": "session"}
        req.path = "/v1/browser-sessions/session/" + operation

        async def invoke():
            response = await bridge.handle_browser_session(
                value, req, operation=operation, api_server=None
            )
            return response.status, json.loads(response.body)

        return asyncio.run(invoke())

    fixture = SimpleNamespace(
        c=c,
        owner=owner,
        identity=identity,
        run=run,
        owned=owned,
        executor=executor,
        browser=browser,
        lifecycle=lifecycle,
        touches=touches,
        released=released,
        bind=bind,
        human=human,
        body=body,
        value=value,
        call=call,
    )
    yield fixture
    executor.close()


def formatters(monkeypatch):
    raw = (RUNTIME / "fixtures/browser_tool.snapshot").read_text()
    lock = json.loads((RUNTIME / "source-lock.json").read_text())
    assert (
        hashlib.sha256(raw.encode()).hexdigest()
        == lock["files"]["tools/browser_tool.py"]["snapshot_sha256"]
    )
    namespace = {
        "Optional": Optional,
        "Dict": Dict,
        "Any": Any,
        "json": json,
        "_session": SimpleNamespace(
            _run_browser_command=lambda sid, cmd, args, **kw: (
                bridge.browser_command_override(sid, cmd, args)
            ),
            _get_session_info=bridge.owned_session_record,
        ),
        "_is_camofox_mode": lambda: False,
        "_last_session_key": lambda sid: sid,
        "_blocked_private_page_action": lambda *args: None,
        "_blocked_private_page_content": lambda *args: None,
        "_blocked_private_page": lambda *args: None,
        "_secret_url_error_normalized": lambda url: (url, None),
        "_navigation_session_key": lambda sid, url: sid,
        "_is_local_sidecar_key": lambda sid: False,
        "_url_policy_error": lambda *args, **kw: None,
        "_post_redirect_block": lambda *args: None,
        "_maybe_start_recording": lambda sid: None,
        "_get_open_command_timeout": lambda **kw: 10,
        "_last_active_session_key": {},
        "_lp": SimpleNamespace(_copy_fallback_warning=lambda output, result: output),
        "_snapshot_fields": lambda result: {
            "snapshot": result["data"]["snapshot"],
            "refs": result["data"]["refs"],
        },
        "_merge_fallback_warning": lambda *args: None,
        "_BOT_DETECTION_TITLE_PATTERNS": (),
        "_dumps": json.dumps,
        "_err": lambda message, **kw: {"success": False, "error": message, **kw},
        "logger": SimpleNamespace(debug=lambda *args: None),
    }
    display = ModuleType("agent.display")
    display.redact_tool_args_for_display = lambda name, args: args
    display.redact_browser_typed_text_for_display = lambda output, text: output
    monkeypatch.setitem(sys.modules, display.__name__, display)
    exec(
        compile(overlay.patch_browser(raw), "pinned_browser_formatters", "exec"),
        namespace,
    )
    return {
        name: namespace["_routed_handler"](
            name,
            lambda args, kw, name=name: namespace[name](**args, task_id=kw["task_id"]),
        )
        for name in bridge.BROWSER_TOOLS
    }


TOOL_ARGUMENTS = [
    ("browser_navigate", {"url": "https://fixture.invalid/page"}),
    ("browser_snapshot", {}),
    ("browser_click", {"ref": "e1"}),
    ("browser_type", {"ref": "e1", "text": "disposable"}),
    ("browser_scroll", {"direction": "down"}),
    ("browser_back", {}),
    ("browser_press", {"key": "Enter"}),
]


@pytest.mark.parametrize("name,args", TOOL_ARGUMENTS)
def test_seven_actual_upstream_formatters_share_gate_and_unix_transport(
    session, monkeypatch, name, args
):
    session.bind()
    handlers = formatters(monkeypatch)
    token = bridge.bind_run_context(
        session.run.run_id,
        "session",
        session.run.dispatch_key,
        None,
        {"principal_id": "alice", "conversation_id": "conversation"},
    )
    monkeypatch.setattr(bridge, "_launch_owned", lambda *a, **kw: session.owned)
    try:
        result = json.loads(handlers[name](args, task_id="session"))
        assert result["success"] is True
        assert session.executor.requests
        session.human()
        count = len(session.executor.requests)
        assert json.loads(handlers[name](args, task_id="session")) == {
            "error": "browser_access_unavailable"
        }
        assert len(session.executor.requests) == count
    finally:
        bridge.reset_run_context(token)


def test_status_and_frame_before_chat_are_passive_and_open_is_explicit(
    session, monkeypatch
):
    count = []

    def launch(*a, **kw):
        count.append(kw)
        session.bind(None)
        return session.owned

    monkeypatch.setattr(bridge, "_launch_owned", launch)
    status, response = session.call("status")
    assert status == 200 and response["state"] == "idle" and not count
    payload = {
        "session_id": "session",
        "owner": {
            "principal_id": "alice",
            "conversation_id": "conversation",
            "auth_session_digest": "a" * 64,
            "binding_revision": 1,
            "tab_id": "tab-1",
        },
        "auth_expires_at": time.time() + 600,
    }
    status, response = session.call("open", payload)
    assert status == 200 and response["control"]["mode"] == "human"
    assert count == [{}] and session.c.state(session.identity).admitted_run is None
    assert (
        response["url"] == "https://fixture.invalid/page"
    )  # query never leaves private runtime.
    assert (
        len(session.executor.requests) == 2
    )  # same-channel fence and bounded metadata only, no LLM run.


def test_agent_presence_renews_native_idle_without_takeover(session):
    session.bind()
    old = session.c.state(session.identity)
    status, response = session.call("heartbeat", session.body(old))
    assert status == 200 and response["control"]["mode"] == "agent"
    assert response["control"]["revision"] == old.revision
    assert "lease_id" not in response["control"] and session.touches == ["session"]
    assert session.executor.requests[0]["action"] == "stream_status"


def test_quiescent_close_preserves_previous_metadata_without_reopening(
    session, monkeypatch
):
    session.bind()
    session.owned.metadata()

    def gone(pid, started):
        return bool(
            session.executor.requests
            and session.executor.requests[-1]["action"] == "close"
        )

    monkeypatch.setattr(bridge, "_pid_gone", gone)
    status, response = session.call("close", session.body())
    assert status == 200 and response["state"] == "idle"
    assert response["page_context"] == {
        "current": None,
        "previous": {"url": "https://fixture.invalid/page", "title": "Fixture"},
    }
    assert session.released == ["session"]
    count = len(session.executor.requests)
    status, again = session.call("status")
    assert (
        again["page_context"] == response["page_context"]
        and len(session.executor.requests) == count
    )


def test_close_cannot_interrupt_an_active_agent_or_nonterminal_reply(session):
    session.bind()
    session.value._run_statuses["old-run"]["status"] = "running"
    assert session.call("close", session.body())[0] == 409
    assert not session.executor.requests
    session.value._run_statuses["old-run"]["status"] = "completed"
    session.c.reserve_agent(session.identity, session.run, "busy")
    assert session.call("close", session.body())[0] == 409
    assert not session.executor.requests


def test_human_input_applied_retry_keeps_saved_ack_after_frame_changes(session):
    session.bind()
    state = session.human()
    session.owned.viewport = {"width": 1280, "height": 720}
    relay = bridge.NativeRelay.__new__(bridge.NativeRelay)
    relay.generation = "generation-1"
    relay.frame = {"frame_id": "f1", "received_at": time.time()}
    relay.recent_frames = bridge.deque([("f1", relay.frame["received_at"])], maxlen=256)
    bridge._relays["session"] = relay
    body = {
        **session.body(state),
        "sequence": 1,
        "frame_id": "f1",
        "viewport": session.owned.viewport,
        "operation": "click",
        "arguments": {"x": 20, "y": 30},
    }
    first = bridge._human_input(session.owned, session.owner, body)
    bridge._relays["session"].frame = {"frame_id": "f2", "received_at": time.time()}
    count = len(session.executor.requests)
    assert bridge._human_input(session.owned, session.owner, body) == first
    assert (
        first == {"success": True, "outcome": "applied", "sequence": 1}
        and len(session.executor.requests) == count
    )
    assert (
        bridge._control_public(session.c.state(session.identity), session.owner)[
            "next_sequence"
        ]
        == 2
    )
    assert "lease_id" not in bridge._control_public(
        session.c.state(session.identity), replace(session.owner, tab_id="other-tab")
    )


def test_human_stale_frame_is_rejected_before_native_dispatch_and_consumes_sequence(
    session,
):
    session.bind()
    state = session.human()
    count = len(session.executor.requests)
    body = {
        **session.body(state),
        "sequence": 1,
        "frame_id": "missing",
        "viewport": {"width": 1280, "height": 720},
        "operation": "press",
        "arguments": {"key": "Enter"},
    }
    assert bridge._human_input(session.owned, session.owner, body) == {
        "success": False,
        "outcome": "rejected",
        "sequence": 1,
    }
    assert len(session.executor.requests) == count


def test_return_requires_terminal_old_run_and_sensitive_fields_empty(
    session, monkeypatch
):
    session.bind()
    state = session.human()
    context = session.body(state)
    body = {
        "session_id": "session",
        "browser_owner": {"principal_id": "alice", "conversation_id": "conversation"},
        "browser_context": context,
    }
    session.value._run_statuses["old-run"]["status"] = "running"
    assert (
        bridge.validate_browser_context(session.value, body, "fresh", "fresh-key")
        == "browser_context_rejected"
    )
    session.value._run_statuses["old-run"]["status"] = "completed"
    monkeypatch.setattr(session.owned, "evaluate", lambda script, **kw: True)
    assert (
        bridge.validate_browser_context(session.value, body, "fresh", "fresh-key")
        == "browser_context_rejected"
    )
    monkeypatch.setattr(session.owned, "evaluate", lambda script, **kw: False)
    assert (
        bridge.validate_browser_context(
            session.value, body, "fresh", "fresh-key", admit=True
        )
        is None
    )
    assert session.c.state(session.identity).admitted_run.run_id == "fresh"
    with pytest.raises(control.ControlRejected, match="run_mismatch"):
        session.c.reserve_agent(
            session.identity, session.run, "old-run-is-never-resumed"
        )


def test_real_pinned_run_admission_replay_precedes_expired_context(
    session, monkeypatch
):
    native_runs = native_namespace(monkeypatch)
    worker_dependencies(monkeypatch)
    # Preserve the actual controlled browser modules after worker import fixtures.
    monkeypatch.setitem(sys.modules, "radhouse_browser_control", control)
    monkeypatch.setitem(sys.modules, "radhouse_native_control", native)
    value = adapter(native_runs)
    api = api_dependencies()
    session.bind()
    state = session.human()
    value._run_statuses["old-run"] = {"session_id": "session", "status": "completed"}
    seen = []

    class Agent:
        def run_conversation(self, **kw):
            seen.append(bridge.current_run_context())
            return "finished"

    async def execute(owner, launch, **kw):
        return await asyncio.to_thread(
            native_runs._run_agent_sync, owner, launch, Agent(), None, _api_server=api
        )

    native_runs._execute_run = execute
    context = session.body(state)
    body = {
        "input": "Continue with this page",
        "session_id": "session",
        "allowed_tools": list(bridge.BROWSER_TOOLS),
        "browser_owner": {"principal_id": "alice", "conversation_id": "conversation"},
        "browser_context": context,
    }

    async def invoke():
        first = await native_runs._handle_runs(
            value, request(body, "fresh-dispatch"), _api_server=api
        )
        assert first.status == 202
        await asyncio.gather(*value._active_run_tasks.values())
        monkeypatch.setattr(bridge.time, "time", lambda: context["auth_expires_at"] + 1)
        replay = await native_runs._handle_runs(
            value, request(body, "fresh-dispatch"), _api_server=api
        )
        assert replay.status == 202 and replay.value["replayed"] is True
        rejected = await native_runs._handle_runs(
            value, request(body, "new-dispatch"), _api_server=api
        )
        assert rejected.status == 409 and rejected.value == {
            "error": "browser_context_rejected",
            "admitted": False,
        }

    asyncio.run(invoke())
    assert len(seen) == 1 and seen[0].browser_owner == body["browser_owner"]


def test_saved_vault_values_are_redacted_as_string_leaves_before_json_escaping(
    monkeypatch,
):
    # This exact native registry scrubber is the stage used by force=True redaction.
    source = (RUNTIME / "fixtures/vault_redaction.snapshot").read_bytes()
    lock = json.loads((RUNTIME / "source-lock.json").read_text())
    assert (
        hashlib.sha256(source).hexdigest()
        == lock["contract_fixtures"]["agent/redact.py"]["snapshot_sha256"]
    )
    scope = ModuleType("hermes_constants")
    scope.get_hermes_home = lambda: "qualification-profile"
    monkeypatch.setitem(sys.modules, scope.__name__, scope)
    redactor = ModuleType("agent.redact")
    redactor.__dict__.update(
        threading=threading,
        _VAULT_REDACTION_LOCK=threading.Lock(),
        _VAULT_REDACTION_VALUES={},
        _VAULT_REDACTION_MAX_PER_PROFILE=64,
    )
    exec(compile(source, "pinned_native_vault_redaction", "exec"), redactor.__dict__)
    redactor.redact_sensitive_text = lambda text, **kw: (
        redactor.redact_registered_vault_values(text)
    )
    monkeypatch.setitem(sys.modules, redactor.__name__, redactor)
    recorded = []
    monkeypatch.setattr(
        bridge,
        "_controller",
        SimpleNamespace(record_page=lambda *args: recorded.append(args[1])),
    )
    for marker in [
        'Synthetic"Quote!',
        "Synthetic\\Backslash!",
        "Synthetic\nLinebreak!",
    ]:
        redactor.register_vault_redaction_value(marker)
        output = bridge._redacted(
            {
                "title": marker,
                "items": [{"snapshot": marker}],
                "url": "https://fixture.invalid/",
            }
        )
        assert (
            marker not in json.dumps(output)
            and output["title"] == "«redacted-vault-secret»"
        )
        assert output["items"][0]["snapshot"] == "«redacted-vault-secret»"
        owned = bridge.OwnedBrowser(
            "qualification",
            {},
            1234,
            123.0,
            SimpleNamespace(submit_metadata=lambda key: object()),
        )
        owned.handle = lambda handle: SimpleNamespace(
            legacy={
                "success": True,
                "data": {
                    "result": {
                        "url": "https://fixture.invalid/",
                        "title": "A" * 490 + marker,
                        "width": 1280,
                        "height": 720,
                    }
                },
            },
        )
        page = owned.metadata()
        assert "Synthetic" not in page["title"]
        assert recorded[-1] == page


@pytest.mark.parametrize("verified", [True, False])
def test_failed_native_bootstrap_retires_only_with_positive_process_identity(
    session, monkeypatch, tmp_path, verified
):
    # Keep the real launch/failure path while injecting a malformed native launch ACK.
    browser_session = ModuleType("tools.browser_tool_session")
    browser_session._session_record = lambda *args: {
        "session_name": "h_0123456789",
        "features": args[2],
        "bb_session_id": None,
        "cdp_url": None,
    }
    browser_session._read_browser_daemon_pid = lambda *args: 4321
    monkeypatch.setitem(sys.modules, browser_session.__name__, browser_session)
    session.browser._socket_safe_tmpdir = lambda: str(tmp_path)
    lifecycle = session.lifecycle
    lifecycle._write_owner_pid = lambda *args: None
    lifecycle._start_browser_cleanup_thread = lambda: None
    lifecycle._verify_reapable_browser_daemon = lambda *args: verified
    gone = []
    lifecycle._kill_verified_daemon = lambda *args: gone.append(True)

    def release(sid, record):
        session.browser._active_sessions.pop(sid, None)

    lifecycle._release_session_resources = release
    monkeypatch.setattr(bridge, "_pid_gone", lambda *args: bool(gone))
    psutil = ModuleType("psutil")
    psutil.Process = lambda pid: SimpleNamespace(create_time=lambda: 123.0)
    monkeypatch.setitem(sys.modules, psutil.__name__, psutil)
    monkeypatch.setattr(
        bridge,
        "_browser_configuration",
        {
            "agent_browser_path": "/qualified/native",
            "chromium_path": "/qualified/chrome",
            "empty_config_path": "/qualified/config",
        },
    )
    launches = []

    def launch(argv, **kwargs):
        launches.append((argv, kwargs["umask"]))
        return SimpleNamespace(returncode=0, stdout=b"invalid JSON")

    monkeypatch.setattr(bridge.subprocess, "run", launch)
    with pytest.raises(control.ControlRejected, match="browser_launch_failed"):
        bridge._launch_owned("conversation", "session", "alice")
    assert launches[0][0][-2:] == ["--", "about:blank"] and launches[0][1] == 0o077
    assert ("session" not in session.browser._active_sessions) is verified
    assert (
        not bridge._owned_browsers
        and session.c.current("conversation", "session", "alice") is None
    )
    if not verified:
        with pytest.raises(
            control.ControlRejected, match="previous_generation_unresolved"
        ):
            bridge._launch_owned("conversation", "session", "alice")
        assert len(launches) == 1


def test_scoped_live_bot_owner_is_refused_before_durable_run_admission(monkeypatch):
    native_runs = native_namespace(monkeypatch)
    value = adapter(native_runs)
    api = api_dependencies()
    monkeypatch.setattr(bridge, "_callback", object())
    db = SimpleNamespace(
        db_path="/qualification/profile/state.db",
        get_compression_tip=lambda sid: "canonical",
    )
    value._ensure_session_db_async = lambda: asyncio.sleep(0, result=db)
    live = ModuleType("tools.bot_live_delivery")
    live.find_canonical_live_owner = lambda home: {"session_id": "canonical"}
    monkeypatch.setitem(sys.modules, live.__name__, live)
    body = {
        "input": "question",
        "session_id": "canonical",
        "allowed_tools": list(bridge.DOCUMENT_TOOLS),
        "document_scope_token": "a" * 43,
    }
    result = asyncio.run(
        native_runs._handle_runs(value, request(body), _api_server=api)
    )
    assert result.status == 409 and result.value["admitted"] is False
    assert (
        not value._active_run_tasks
        and not value._run_idempotency_store.records
        and not value._run_owners
    )


def test_reconnect_pause_requires_matched_native_ack_before_a_new_lease(session):
    session.bind()
    taken = session.human()
    receipt = session.c.reserve_input(
        session.identity, session.owner, taken.lease.lease_id, taken.revision, 1
    )
    with pytest.raises(control.ControlRejected, match="native_ack_pending"):
        bridge._pause_owned(session.owned, session.owner)
    assert session.c.state(session.identity).mode == "human"
    handle = session.owned.channel.submit_input(
        receipt.command_id, "press", {"key": "Enter"}
    )
    result = session.owned.handle(handle)
    session.c.complete_input(
        session.identity,
        taken.lease.lease_id,
        1,
        receipt.command_id,
        outcome=result.outcome,
    )
    paused = bridge._pause_owned(session.owned, session.owner)
    assert (
        paused.mode == "paused"
        and bridge._control_public(paused, session.owner)["can_take"]
    )
    fresh = session.c.request_takeover(
        session.identity,
        session.owner,
        "reconnect",
        revision=paused.revision,
        auth_expires_at=time.time() + 600,
    )
    human = bridge._fence_takeover(session.owned, fresh)
    assert human.mode == "human" and human.lease.lease_id != taken.lease.lease_id
    assert human.last_sequence == 0
    assert sum(r["action"] == "press" for r in session.executor.requests) == 1


def test_reconnect_never_clears_a_native_uncertain_hold(session):
    session.bind()
    taken = session.human()
    receipt = session.c.reserve_input(
        session.identity, session.owner, taken.lease.lease_id, taken.revision, 1
    )
    session.c.complete_input(
        session.identity,
        taken.lease.lease_id,
        1,
        receipt.command_id,
        outcome="uncertain",
    )
    with pytest.raises(control.ControlRejected, match="native_ack_pending"):
        bridge._pause_owned(session.owned, session.owner)
    state = session.c.state(session.identity)
    assert (
        state.mode == "recovering"
        and state.active_command.command_id == receipt.command_id
        and state.lease is None
    )


def test_maintenance_hold_does_not_renew_native_activity_through_observer_metadata(
    session, monkeypatch
):
    session.bind()
    session.owned.metadata()
    count = len(session.executor.requests)
    monkeypatch.setattr(bridge, "maintenance_held", lambda: True)
    assert session.call("status")[0] == 200
    assert len(session.executor.requests) == count


@pytest.mark.parametrize("exhausted", [True, False])
def test_native_default_recovery_does_not_wait_for_an_exhausted_admitted_budget(
    monkeypatch, exhausted
):
    from enum import Enum

    class Reason(Enum):
        overloaded = "overloaded"
        server_error = "server_error"
        timeout = "timeout"

    classifier = ModuleType("agent.error_classifier")
    classifier.FailoverReason = Reason
    monkeypatch.setitem(sys.modules, classifier.__name__, classifier)
    budget_module = ModuleType("agent.provider_request_budget")

    class ProviderRequestBudget:
        def snapshot(self):
            return {"exhausted": exhausted}

    budget_module.ProviderRequestBudget = ProviderRequestBudget
    monkeypatch.setitem(sys.modules, budget_module.__name__, budget_module)
    waits = []
    recovery = ModuleType("agent.turn_recovery")
    recovery.interruptible_backoff_sleep = lambda agent, wait, *args, **kw: (
        waits.append(wait)
    )
    retry_utils = ModuleType("agent.retry_utils")
    retry_utils.jittered_backoff = lambda cycle, **kw: 15.0
    retry_utils.provider_retry_after_seconds = lambda error: None
    monkeypatch.setitem(sys.modules, recovery.__name__, recovery)
    monkeypatch.setitem(sys.modules, retry_utils.__name__, retry_utils)
    source = (RUNTIME / "fixtures/turn_recovery_autorecover.snapshot").read_bytes()
    lock = json.loads((RUNTIME / "source-lock.json").read_text())
    assert (
        hashlib.sha256(source).hexdigest()
        == lock["files"]["agent/turn_recovery_autorecover.py"]["snapshot_sha256"]
    )
    namespace = {}
    exec(
        compile(
            overlay.patch_budget_recovery(source.decode()),
            "pinned_native_auto_recovery",
            "exec",
        ),
        namespace,
    )
    agent = SimpleNamespace(
        _provider_request_budget=ProviderRequestBudget(),
        _auto_recovery_cycles=5,
        _has_content_after_think_block=lambda text: False,
        _emit_diagnostic_status=lambda text: None,
        _emit_diagnostic_wait=lambda text: None,
        log_prefix="",
        _client_log_context=lambda: "qualification",
    )
    retry = SimpleNamespace(
        auto_recovery_cycles_used=0, restart_with_redirected_messages=False
    )
    result = namespace["auto_recover_after_exhaustion"](
        agent,
        Exception("synthetic SDK transport wrapper"),
        SimpleNamespace(reason=Reason.timeout),
        retry,
        messages=[],
        conversation_history=[],
        api_call_count=1,
    )
    if exhausted:
        assert result is None and waits == [] and retry.auto_recovery_cycles_used == 0
    else:
        assert (
            result == {"action": "continue"}
            and waits == [15.0]
            and retry.auto_recovery_cycles_used == 1
        )


def test_native_page_title_whitespace_is_normalized_before_web_status(session):
    session.bind()

    def result(command):
        return success(
            command,
            {
                "result": {
                    "url": "https://fixture.invalid/",
                    "title": "  First\nSecond\tTitle\x00  ",
                    "width": 1280,
                    "height": 720,
                }
            },
        )

    session.executor.handler = result
    page = session.owned.metadata()
    assert page["title"] == "First Second Title"
