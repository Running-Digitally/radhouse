"""Synthetic Unix executor: preserved outputs, ordering and uncertain outcomes."""
import asyncio
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading

import pytest

spec = importlib.util.spec_from_file_location("radhouse_native_control",
    Path(__file__).resolve().parents[1] / "runtime/hermes/native_control.py")
native = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = native
spec.loader.exec_module(native)


class Executor:
    def __init__(self, handler):
        # Short paths also fit macOS's Unix sockaddr limit. No external sockets.
        self.directory = tempfile.TemporaryDirectory(prefix="rh-native-", dir="/tmp")
        self.path = Path(self.directory.name) / "owned.sock"
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(self.path))
        self.path.chmod(0o600)
        self.listener.listen(1)
        self.generation = ["generation-1"]
        self.requests = []
        self.received = threading.Event()
        self.peer = None
        self.channel = None
        self.handler = handler
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def connect(self, **kwargs):
        self.channel = native.NativeControlChannel(self.path, "generation-1", lambda: self.generation[0], **kwargs)
        return self.channel

    def run(self):
        try:
            self.peer, _ = self.listener.accept()
            with self.peer.makefile("rb") as reader:
                for line in reader:
                    command = json.loads(line)
                    self.requests.append(command)
                    self.received.set()
                    response = self.handler(command)
                    if response is None:
                        return
                    data = response if type(response) is bytes else json.dumps(response).encode()+b"\n"
                    self.peer.sendall(data)
        except OSError:
            pass  # Fixture/channel cleanup, never a second connection or retry.
        finally:
            if self.peer:
                self.peer.close()

    def close(self):
        if self.channel:
            self.channel.close()
        for connection in (self.peer, self.listener):
            if connection:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.close()
        self.thread.join(timeout=2)
        self.directory.cleanup()


def success(command, data=None):
    return {"id":command["id"], "success":True, "data":data or {"connected":True}}


@pytest.fixture
def executor():
    fixtures = []

    def make(handler=success):
        fixture = Executor(handler)
        fixtures.append(fixture)
        return fixture

    yield make
    for fixture in fixtures:
        fixture.close()


TOOLS = [
    ("browser_navigate", {"url":"https://synthetic.invalid/"}, {"action":"navigate", "url":"https://synthetic.invalid/"}, {"url":"https://synthetic.invalid/", "title":"Synthetic"}),
    ("browser_snapshot", {}, {"action":"snapshot", "compact":True}, {"snapshot":"button [ref=e1]", "refs":{"e1":{"role":"button"}}}),
    ("browser_snapshot", {"full":True}, {"action":"snapshot"}, {"snapshot":"full synthetic snapshot", "refs":{}}),
    ("browser_click", {"ref":"e1"}, {"action":"click", "selector":"@e1"}, {"clicked":True}),
    ("browser_type", {"ref":"@e2", "text":"SENTINEL"}, {"action":"fill", "selector":"@e2", "value":"SENTINEL"}, {"filled":True}),
    ("browser_scroll", {"direction":"down"}, {"action":"scroll", "direction":"down", "amount":500}, {"scrolled":True}),
    ("browser_back", {}, {"action":"back"}, {"url":"https://synthetic.invalid/previous"}),
    ("browser_press", {"key":"Control+A"}, {"action":"press", "key":"Control+A"}, {"pressed":True}),
]


@pytest.mark.parametrize("name,arguments,command,data", TOOLS)
def test_all_seven_tools_keep_exact_native_map_and_legacy_output(executor, name, arguments, command, data):
    fixture = executor(lambda request: success(request, data))
    result = fixture.connect().submit_tool("command-1", name, arguments).result(2)
    assert fixture.requests == [{**command, "id":"command-1"}]
    assert result.completed is True
    assert result.legacy == {"success":True, "data":data, "error":None}
    assert "id" not in result.legacy


@pytest.mark.parametrize("command,args,expected", [
    ("open", ["about:blank"], {"action":"navigate", "url":"about:blank"}),
    ("snapshot", ["-c"], {"action":"snapshot", "compact":True}),
    ("snapshot", [], {"action":"snapshot"}),
    ("click", ["@e1"], {"action":"click", "selector":"@e1"}),
    ("fill", ["@e2", "new"], {"action":"fill", "selector":"@e2", "value":"new"}),
    ("scroll", ["up", "500"], {"action":"scroll", "direction":"up", "amount":500}),
    ("back", [], {"action":"back"}),
    ("press", ["Enter"], {"action":"press", "key":"Enter"}),
])
def test_existing_cli_call_forms_map_without_cli_execution(command, args, expected):
    assert native.legacy_command(command, args) == expected


@pytest.mark.parametrize("command,args", [
    ("evaluate", ["document.cookie"]), ("snapshot", ["--full"]),
    ("open", ["--cdp", "endpoint"]), ("screenshot", ["/tmp/file"]),
    ("fill", ["@e1", "text", "--profile"]), ("scroll", ["down", "501"]),
])
def test_adapter_accepts_no_extension_or_arbitrary_native_operation(command, args):
    with pytest.raises(native.NativeRejected):
        native.legacy_command(command, args)


def test_completed_native_error_preserves_internal_legacy_error_fields(executor):
    fixture = executor(lambda command: {"id":command["id"], "success":False,
        "error":"Synthetic operation partially failed", "code":"tab_gone", "warning":"Synthetic warning"})
    channel = fixture.connect()
    handle = channel.submit_tool("failed", "browser_click", {"ref":"e1"})
    result = handle.result(2)
    assert result.completed is True
    assert result.legacy == {"success":False, "data":None, "error":"Synthetic operation partially failed",
                            "code":"tab_gone", "warning":"Synthetic warning"}
    fence = channel.fence_after("fence", handle).result(2)
    assert fence.quiescent is False  # Same synthetic executor returns an error for status too.


def test_human_text_returns_only_fixed_sanitized_ack(executor):
    secret = "NON-SENSITIVE-SYNTHETIC-SENTINEL"
    fixture = executor(lambda command: {"id":command["id"], "success":False,
        "error":secret, "warning":secret, "data":{"text":secret, "url":secret}})
    result = fixture.connect().submit_input("text-1", "text", {"text":secret}).result(2)
    assert fixture.requests == [{"action":"inserttext", "text":secret, "id":"text-1"}]
    assert asdict(result) == {"command_id":"text-1", "completed":True, "outcome":"uncertain"}
    assert secret not in repr(result)


def test_click_is_one_serialized_complete_down_up_gesture(executor):
    fixture = executor()
    result = fixture.connect().submit_input("click-1", "click", {"x":12, "y":34}).result(2)
    assert result == native.HumanAck("click-1", True, "applied")
    assert fixture.requests == [
        {"id":"click-1:0", "action":"input_mouse", "type":"mousePressed", "x":12, "y":34, "button":"left", "clickCount":1},
        {"id":"click-1:1", "action":"input_mouse", "type":"mouseReleased", "x":12, "y":34, "button":"left", "clickCount":1},
    ]


def test_failed_click_step_is_uncertain_and_never_retried(executor):
    fixture = executor(lambda command: {"id":command["id"], "success":False, "error":"Synthetic failure"})
    result = fixture.connect().submit_input("click-1", "click", {"x":1, "y":2}).result(2)
    assert result == native.HumanAck("click-1", True, "uncertain")
    assert len(fixture.requests) == 1


def test_lost_release_ack_does_not_repeat_partial_gesture(executor):
    fixture = executor(lambda command: success(command) if command["id"].endswith(":0") else None)
    result = fixture.connect().submit_input("click-1", "click", {"x":1, "y":2}).result(2)
    assert result == native.HumanAck("click-1", False, "uncertain")
    assert [command["id"] for command in fixture.requests] == ["click-1:0", "click-1:1"]


def test_human_scroll_and_press_use_complete_native_commands(executor):
    fixture = executor()
    channel = fixture.connect()
    assert channel.submit_input("wheel", "scroll", {"x":1, "y":2, "delta_x":0, "delta_y":90}).result(2).outcome == "applied"
    assert channel.submit_input("key", "press", {"key":"Enter"}).result(2).outcome == "applied"
    assert fixture.requests == [
        {"id":"wheel", "action":"input_mouse", "type":"mouseWheel", "x":1, "y":2, "deltaX":0, "deltaY":90},
        {"id":"key", "action":"press", "key":"Enter"},
    ]


@pytest.mark.parametrize("operation,args", [("drag", {}), ("click", {"x":True, "y":1}),
    ("click", {"x":10**1000, "y":1}),
    ("scroll", {"x":1, "y":2, "delta_x":0, "delta_y":float("nan")}),
    ("text", {"text":"a\x00b"}), ("text", {"text":"text", "native_action":"evaluate"})])
def test_human_shape_rejection_is_definitely_before_dispatch(executor, operation, args):
    fixture = executor()
    channel = fixture.connect()
    with pytest.raises(native.NativeRejected):
        channel.submit_input("bad", operation, args)
    assert fixture.requests == []


def test_invalid_agent_argument_types_are_fixed_predispatch_rejections(executor):
    fixture = executor()
    channel = fixture.connect()
    with pytest.raises(native.NativeRejected, match="native_arguments_invalid"):
        channel.submit_tool("invalid", "browser_scroll", {"direction":[]})
    assert fixture.requests == []


def test_deadline_keeps_late_matching_ack_then_same_channel_fence(executor):
    release = threading.Event()
    def handler(command):
        if command["action"] != "stream_status":
            assert release.wait(2)
        return success(command)
    fixture = executor(handler)
    channel = fixture.connect()
    handle = channel.submit_tool("click", "browser_click", {"ref":"e1"})
    assert fixture.received.wait(1)
    assert handle.future.cancel() is False
    with pytest.raises(native.NativeWaitTimeout) as timeout:
        handle.result(0.01)
    assert timeout.value.handle is handle
    with pytest.raises(native.NativeRejected, match="native_ack_pending"):
        channel.fence_after("premature", handle)
    assert len(fixture.requests) == 1
    release.set()
    assert handle.result(2).completed
    fence = channel.fence_after("fence", handle).result(2)
    assert fence == native.FenceAck("fence", "click", "generation-1", True)
    assert [command["id"] for command in fixture.requests] == ["click", "fence"]


def test_async_deadline_does_not_cancel_ack_reader(executor):
    release = threading.Event()
    fixture = executor(lambda command: success(command) if release.wait(2) else None)
    handle = fixture.connect().submit_input("text", "text", {"text":"sentinel"})
    assert fixture.received.wait(1)
    async def check():
        with pytest.raises(native.NativeWaitTimeout):
            await handle.wait(0.01)
        assert not handle.future.cancelled()
        release.set()
        return await handle.wait(2)
    assert asyncio.run(check()) == native.HumanAck("text", True, "applied")
    assert len(fixture.requests) == 1


def test_single_worker_serializes_bounded_queue_and_freezes_submitted_arguments(executor):
    release = threading.Event()
    fixture = executor(lambda command: success(command) if release.wait(2) else None)
    channel = fixture.connect()
    first = channel.submit_tool("first", "browser_back", {})
    assert fixture.received.wait(1)
    args = {"ref":"e1", "text":"before"}
    second = channel.submit_tool("second", "browser_type", args)
    args["text"] = "after"
    with pytest.raises(native.NativeRejected, match="native_channel_busy"):
        channel.submit_tool("third", "browser_back", {})
    assert [command["id"] for command in fixture.requests] == ["first"]
    release.set()
    first.result(2)
    second.result(2)
    assert fixture.requests[1]["value"] == "before"
    assert [command["id"] for command in fixture.requests] == ["first", "second"]


def test_command_id_cannot_be_replayed_after_lost_wait_or_completed_ack(executor):
    fixture = executor()
    channel = fixture.connect()
    handle = channel.submit_tool("once", "browser_back", {})
    handle.result(2)
    with pytest.raises(native.NativeRejected, match="native_command_already_submitted"):
        channel.submit_tool("once", "browser_back", {})
    assert len(fixture.requests) == 1


@pytest.mark.parametrize("response,code", [
    (None, "native_connection_lost"),
    ({"id":"wrong", "success":True, "data":{}}, "native_response_invalid"),
    (b"invalid-json\n", "native_response_invalid"),
    ({"id":"once", "success":"true"}, "native_response_invalid"),
    ({"id":"once", "success":False, "error":{"secret":"invalid"}}, "native_response_invalid"),
])
def test_disconnect_or_mismatched_ack_poisons_without_reconnect_or_replay(executor, response, code):
    fixture = executor(lambda command: response)
    channel = fixture.connect()
    with pytest.raises(native.NativeChannelError, match=code) as failure:
        channel.submit_tool("once", "browser_back", {}).result(2)
    assert failure.value.completed is False
    with pytest.raises(native.NativeRejected, match="native_channel_closed"):
        channel.submit_tool("new", "browser_back", {})
    assert [command["id"] for command in fixture.requests] == ["once"]


def test_channel_loss_sanitizes_current_and_queued_human_ack(executor):
    release = threading.Event()
    fixture = executor(lambda command: None if release.wait(2) else success(command))
    channel = fixture.connect()
    current = channel.submit_input("current", "text", {"text":"sentinel"})
    assert fixture.received.wait(1)
    queued = channel.submit_input("queued", "text", {"text":"another"})
    release.set()
    assert current.result(2) == native.HumanAck("current", False, "uncertain")
    assert queued.result(2) == native.HumanAck("queued", False, "uncertain")
    assert [command["id"] for command in fixture.requests] == ["current"]


def test_generation_changed_before_command_is_never_sent(executor):
    fixture = executor()
    channel = fixture.connect()
    fixture.generation[0] = "generation-2"
    with pytest.raises(native.NativeChannelError, match="native_generation_changed"):
        channel.submit_tool("stale", "browser_back", {}).result(2)
    assert fixture.requests == []


@pytest.mark.parametrize("lifecycle", [{"launched":True}, {"relaunchedBrowser":True}])
def test_new_browser_incarnation_on_matching_ack_poisoned_before_next_input(executor, lifecycle):
    fixture = executor(lambda command: success(command, {"lifecycle":lifecycle}))
    channel = fixture.connect()
    with pytest.raises(native.NativeChannelError, match="native_browser_incarnation_changed") as failure:
        channel.submit_tool("first", "browser_back", {}).result(2)
    assert failure.value.completed is True
    with pytest.raises(native.NativeRejected, match="native_channel_closed"):
        channel.submit_input("next", "text", {"text":"sentinel"})


def test_generation_change_after_ack_proves_completion_but_revokes_channel(executor):
    fixture = None
    def handler(command):
        fixture.generation[0] = "generation-2"
        return success(command)
    fixture = executor(handler)
    channel = fixture.connect()
    with pytest.raises(native.NativeChannelError, match="native_generation_changed") as failure:
        channel.submit_tool("command", "browser_back", {}).result(2)
    assert failure.value.completed is True
    assert len(fixture.requests) == 1


def test_fence_requires_latest_matching_handle_on_this_channel(executor):
    fixture = executor()
    channel = fixture.connect()
    first = channel.submit_tool("first", "browser_back", {})
    first.result(2)
    with pytest.raises(native.NativeRejected, match="native_fence_order_unavailable"):
        channel.fence_after("missing")
    second = channel.submit_tool("second", "browser_back", {})
    second.result(2)
    with pytest.raises(native.NativeRejected, match="native_fence_order_unavailable"):
        channel.fence_after("old", first)
    other = executor().connect().submit_tool("foreign", "browser_back", {})
    other.result(2)
    with pytest.raises(native.NativeRejected, match="native_fence_order_unavailable"):
        channel.fence_after("foreign-fence", other)
    assert channel.fence_after("current-fence", second).result(2).quiescent


def test_status_probe_repeats_after_fence_without_browser_launch(executor):
    fixture = executor()
    channel = fixture.connect()
    handle = channel.submit_tool("agent", "browser_back", {})
    handle.result(2)
    channel.fence_after("fence", handle).result(2)
    assert channel.probe_status("heartbeat-1").result(2) == native.FenceAck("heartbeat-1", "fence", "generation-1", True)
    assert channel.probe_status("heartbeat-2").result(2) == native.FenceAck("heartbeat-2", "heartbeat-1", "generation-1", True)
    assert [command["action"] for command in fixture.requests] == ["back", "stream_status", "stream_status", "stream_status"]


def test_status_probe_never_overtakes_an_unresolved_ack(executor):
    release = threading.Event()
    fixture = executor(lambda command: success(command) if release.wait(2) else None)
    channel = fixture.connect()
    handle = channel.submit_input("human", "text", {"text":"sentinel"})
    assert fixture.received.wait(1)
    with pytest.raises(native.NativeRejected, match="native_ack_pending"):
        channel.probe_status("premature-heartbeat")
    assert len(fixture.requests) == 1
    release.set()
    handle.result(2)
    assert channel.probe_status("ordered-heartbeat").result(2).preceding_command_id == "human"


def test_status_probe_poisoned_generation_never_reconnects(executor):
    fixture = executor(lambda command: None)
    channel = fixture.connect()
    with pytest.raises(native.NativeChannelError, match="native_connection_lost"):
        channel.probe_status("lost-heartbeat").result(2)
    with pytest.raises(native.NativeRejected, match="native_channel_closed"):
        channel.probe_status("later-heartbeat")
    assert len(fixture.requests) == 1


def test_private_owned_socket_checked_before_connect(executor):
    fixture = executor()
    fixture.path.chmod(0o660)
    with pytest.raises(native.NativeRejected, match="native_socket_requires_private_owner"):
        fixture.connect()
    assert fixture.requests == []
    fixture.path.chmod(0o600)
    fixture.path.parent.chmod(0o755)
    with pytest.raises(native.NativeRejected, match="native_socket_requires_private_owner"):
        fixture.connect()
    fixture.path.parent.chmod(0o700)
    link = fixture.path.parent / "link.sock"
    link.symlink_to(fixture.path)
    with pytest.raises(native.NativeRejected, match="native_socket_requires_private_owner"):
        native.NativeControlChannel(link, "generation-1", lambda: "generation-1")


def test_generation_known_before_connect(executor):
    fixture = executor()
    fixture.generation[0] = None
    with pytest.raises(native.NativeChannelError, match="native_generation_changed"):
        fixture.connect()
    assert fixture.requests == []


def test_protocol_frame_bounds_reject_request_before_dispatch_and_poison_oversized_ack(executor):
    fixture = executor(lambda command: b"x"*1025)
    channel = fixture.connect(max_frame_bytes=1024)
    with pytest.raises(native.NativeRejected, match="native_request_too_large"):
        channel.submit_input("large", "text", {"text":"x"*1024})
    assert fixture.requests == []
    with pytest.raises(native.NativeChannelError, match="native_response_too_large"):
        channel.submit_tool("bounded", "browser_back", {}).result(2)
    assert len(fixture.requests) == 1


def test_native_lifecycle_close_uses_owned_channel_without_run_context(executor):
    fixture = executor()
    channel = fixture.connect()
    result = channel.submit_close("close").result(2)
    assert result.completed
    # Wait until close processed: subsequent admission must reject, even if a
    # future waiter resumed immediately after ACK but before worker cleanup.
    channel._worker.join(timeout=1)
    with pytest.raises(native.NativeRejected, match="native_channel_closed"):
        channel.submit_tool("late", "browser_back", {})
    assert fixture.requests == [{"action":"close", "id":"close"}]


@pytest.mark.parametrize("observed_generation", [None, "generation-2"])
def test_owned_close_handles_expected_generation_retirement_but_not_replacement(executor, observed_generation):
    fixture = None
    def handler(command):
        fixture.generation[0] = observed_generation
        return success(command)
    fixture = executor(handler)
    channel = fixture.connect()
    handle = channel.submit_close("close")
    if observed_generation is None:
        assert handle.result(2).legacy["success"] is True
    else:
        with pytest.raises(native.NativeChannelError, match="native_generation_changed") as failure:
            handle.result(2)
        assert failure.value.completed is True
    channel._worker.join(timeout=1)
    with pytest.raises(native.NativeRejected, match="native_channel_closed"):
        channel.probe_status("late")
    assert len(fixture.requests) == 1


def test_explicit_transport_close_marks_unresolved_human_work_uncertain(executor):
    release = threading.Event()
    fixture = executor(lambda command: success(command) if release.wait(2) else None)
    channel = fixture.connect()
    handle = channel.submit_input("text", "text", {"text":"sentinel"})
    assert fixture.received.wait(1)
    channel.close()
    assert handle.result(2) == native.HumanAck("text", False, "uncertain")
    release.set()
    assert len(fixture.requests) == 1
