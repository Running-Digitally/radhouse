"""One owned native Unix channel. No CLI payloads, retries or reconnection.

The caller supplies existing session/lifecycle identity and reserves ownership
before submission. This transport is deliberately unwired from Hermes for now.
"""
import asyncio
import json
import math
import os
import re
import socket
import stat
import threading
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Callable, Literal


class NativeRejected(ValueError):
    """Fixed pre-dispatch rejection; no native work was submitted."""


class NativeChannelError(RuntimeError):
    def __init__(self, code, *, completed=False):
        super().__init__(code)
        self.completed = completed


class NativeWaitTimeout(TimeoutError):
    def __init__(self, handle):
        super().__init__("native_ack_pending")
        self.handle = handle


@dataclass(frozen=True)
class AgentAck:
    command_id: str
    completed: bool
    legacy: dict = field(repr=False)


@dataclass(frozen=True)
class HumanAck:
    command_id: str
    completed: bool
    outcome: Literal["applied", "uncertain"]


@dataclass(frozen=True)
class FenceAck:
    command_id: str
    preceding_command_id: str | None
    generation: str
    quiescent: bool


class CommandHandle:
    def __init__(self, channel, command_id, future):
        self.command_id = command_id
        self._channel, self._future = channel, future

    @property
    def future(self):
        """Retained running future: caller cancellation cannot cancel native work."""
        return self._future

    def result(self, timeout=None):
        try:
            return self._future.result(timeout=timeout)
        except FutureTimeout:
            raise NativeWaitTimeout(self) from None

    async def wait(self, timeout=None):
        wrapped = asyncio.shield(asyncio.wrap_future(self._future))
        try:
            return await asyncio.wait_for(wrapped, timeout)
        except asyncio.TimeoutError:
            raise NativeWaitTimeout(self) from None


def _string(value):
    if type(value) is not str or "\x00" in value:
        raise NativeRejected("native_arguments_invalid")
    return value


def _identifier(value):
    value = _string(value)
    if not value or len(value) > 128 or any(ord(c) < 32 for c in value):
        raise NativeRejected("native_arguments_invalid")
    return value


def _shape(arguments, keys):
    if type(arguments) is not dict or set(arguments) != set(keys):
        raise NativeRejected("native_arguments_invalid")


def _ref(value):
    value = _string(value)
    if not re.fullmatch(r"@?e[0-9]{1,12}", value):
        raise NativeRejected("native_arguments_invalid")
    return value if value.startswith("@") else "@"+value


def tool_command(name, arguments):
    """Exact seven-tool protocol mapping; Hermes retains its existing policy/formatters."""
    if name == "browser_navigate":
        _shape(arguments, {"url"})
        return {"action":"navigate", "url":_string(arguments["url"])}
    if name == "browser_snapshot":
        if arguments == {}:
            arguments = {"full":False}
        _shape(arguments, {"full"})
        if type(arguments["full"]) is not bool:
            raise NativeRejected("native_arguments_invalid")
        return {"action":"snapshot"} if arguments["full"] else {"action":"snapshot", "compact":True}
    if name == "browser_click":
        _shape(arguments, {"ref"})
        return {"action":"click", "selector":_ref(arguments["ref"])}
    if name == "browser_type":
        _shape(arguments, {"ref", "text"})
        return {"action":"fill", "selector":_ref(arguments["ref"]), "value":_string(arguments["text"])}
    if name == "browser_scroll":
        _shape(arguments, {"direction"})
        if type(arguments["direction"]) is not str or arguments["direction"] not in {"up", "down"}:
            raise NativeRejected("native_arguments_invalid")
        return {"action":"scroll", "direction":arguments["direction"], "amount":500}
    if name == "browser_back":
        _shape(arguments, set())
        return {"action":"back"}
    if name == "browser_press":
        _shape(arguments, {"key"})
        return {"action":"press", "key":_identifier(arguments["key"])}
    raise NativeRejected("native_operation_unsupported")


def legacy_command(command, arguments):
    """Fixed existing _run_browser_command forms, not a general CLI parser."""
    if type(arguments) not in {list, tuple} or any(type(arg) is not str for arg in arguments):
        raise NativeRejected("native_arguments_invalid")
    if command == "open" and len(arguments) == 1:
        return tool_command("browser_navigate", {"url":arguments[0]})
    if command == "snapshot" and arguments in ([], (), ["-c"], ("-c",)):
        return tool_command("browser_snapshot", {"full":not bool(arguments)})
    if command == "click" and len(arguments) == 1:
        return tool_command("browser_click", {"ref":arguments[0]})
    if command == "fill" and len(arguments) == 2:
        return tool_command("browser_type", {"ref":arguments[0], "text":arguments[1]})
    if command == "scroll" and len(arguments) == 2 and arguments[1] == "500":
        return tool_command("browser_scroll", {"direction":arguments[0]})
    if command == "back" and not arguments:
        return tool_command("browser_back", {})
    if command == "press" and len(arguments) == 1:
        return tool_command("browser_press", {"key":arguments[0]})
    raise NativeRejected("native_operation_unsupported")


def human_commands(operation, arguments):
    """Complete gestures only; HTTP owns login, lease, frame and viewport validation."""
    if operation == "navigate":
        _shape(arguments, {"url"})
        return [{"action": "navigate", "url": _string(arguments["url"])}]
    if operation in {"back", "reload"}:
        _shape(arguments, set())
        return [{"action": operation}]
    if operation == "text":
        _shape(arguments, {"text"})
        return [{"action": "inserttext", "text": _string(arguments["text"])}]
    if operation == "press":
        _shape(arguments, {"key"})
        return [{"action": "press", "key": _identifier(arguments["key"])}]
    if type(operation) is not str or operation not in {"click", "scroll"}:
        raise NativeRejected("native_operation_unsupported")
    keys = {"x", "y"} if operation == "click" else {"x", "y", "delta_x", "delta_y"}
    _shape(arguments, keys)
    try:
        finite = all(
            type(v) in {int, float} and math.isfinite(v) for v in arguments.values()
        )
    except OverflowError:
        finite = False
    if not finite:
        raise NativeRejected("native_arguments_invalid")
    if operation == "click":
        return [
            {
                "action": "input_mouse",
                "type": kind,
                "x": arguments["x"],
                "y": arguments["y"],
                "button": "left",
                "clickCount": 1,
            }
            for kind in ("mousePressed", "mouseReleased")
        ]
    return [
        {
            "action": "input_mouse",
            "type": "mouseWheel",
            "x": arguments["x"],
            "y": arguments["y"],
            "deltaX": arguments["delta_x"],
            "deltaY": arguments["delta_y"],
        }
    ]


@dataclass
class _Job:
    handle: CommandHandle
    kind: str
    commands: list[dict] = field(repr=False)
    preceding: str | None = None


class NativeControlChannel:
    """All native writes for one already-bound generation must use this channel.

    Caller deadlines only stop waiting. Retain the handle to match the late ACK;
    neither reconnect nor pass an uncertain generation to a new channel. The
    existing lifecycle owns bootstrap, retirement, and the generation callback.
    An ACK with success=False proves executor completion, not absence of effects.
    """
    def __init__(self, socket_path: str | Path, generation: str,
                 current_generation: Callable[[], str | None], *, max_frame_bytes=8*1024*1024):
        self.path, self.generation = Path(socket_path).absolute(), _identifier(generation)
        if not callable(current_generation) or type(max_frame_bytes) is not int or max_frame_bytes < 256:
            raise NativeRejected("native_configuration_invalid")
        self._current_generation, self._max_frame = current_generation, max_frame_bytes
        self._lock = threading.RLock()
        self._queue = Queue(maxsize=1)
        self._pending, self._seen = {}, set()
        self._closed = False
        self._last_completed = None
        self._buffer = bytearray()
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            before = self._socket_identity()
            self._check_generation()
            self._socket.connect(str(self.path))
            if self._socket_identity() != before:
                raise NativeChannelError("native_socket_changed")
            self._check_generation()
        except Exception:
            self._socket.close()
            raise
        self._worker = threading.Thread(target=self._run, name="radhouse-native-control", daemon=True)
        self._worker.start()

    def _socket_identity(self):
        directory, node = self.path.parent.lstat(), self.path.lstat()
        if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.getuid() or directory.st_mode & 0o077
                or not stat.S_ISSOCK(node.st_mode) or node.st_uid != os.getuid() or node.st_mode & 0o077):
            raise NativeRejected("native_socket_requires_private_owner")
        return node.st_dev, node.st_ino, node.st_mtime_ns

    def _check_generation(self, *, allow_retired=False):
        try:
            current = self._current_generation()
        except Exception:
            raise NativeChannelError("native_generation_unavailable") from None
        if current != self.generation and not (allow_retired and current is None):
            raise NativeChannelError("native_generation_changed")

    def submit_tool(self, command_id, name, arguments):
        return self._submit(command_id, "agent", [tool_command(name, arguments)])

    def submit_legacy(self, command_id, command, arguments):
        return self._submit(command_id, "agent", [legacy_command(command, arguments)])

    def submit_input(self, command_id, operation, arguments):
        return self._submit(command_id, "human", human_commands(operation, arguments))

    def submit_trusted_evaluation(self, command_id, expression):
        """Private adapter only: no model-facing evaluation tool or CLI payload."""
        return self._submit(
            command_id,
            "trusted",
            [{"action": "evaluate", "script": _string(expression)}],
        )


    def submit_metadata(self, command_id):
        return self.submit_trusted_evaluation(
            command_id,
            "({url:location.href,title:document.title,width:innerWidth,height:innerHeight})",
        )


    def submit_close(self, command_id):
        return self._submit(command_id, "close", [{"action":"close"}])

    def probe_status(self, command_id):
        """Repeatable same-channel idle renewal, never a new browser launch.

        The controller validates the current lease before calling. This fixed
        probe is not a takeover proof over a separate/previous CLI connection.
        """
        with self._lock:
            if self._pending:
                raise NativeRejected("native_ack_pending")
            return self._submit(command_id, "fence", [{"action":"stream_status"}],
                                preceding=self._last_completed)

    def fence_after(self, command_id, preceding=None):
        with self._lock:
            if self._pending:
                raise NativeRejected("native_ack_pending")
            if preceding is not None:
                if (
                    not isinstance(preceding, CommandHandle)
                    or preceding._channel is not self
                    or preceding.command_id != self._last_completed
                    or not preceding.future.done()
                ):
                    raise NativeRejected("native_fence_order_unavailable")
                result = preceding.result()
                completed = (
                    isinstance(result, (AgentAck, HumanAck))
                    and result.completed
                    or isinstance(result, FenceAck)
                    and result.quiescent
                    and result.generation == self.generation
                )
                if not completed:
                    raise NativeRejected("native_fence_order_unavailable")
            elif self._last_completed is not None:
                raise NativeRejected("native_fence_order_unavailable")
            return self._submit(
                command_id,
                "fence",
                [{"action": "stream_status"}],
                preceding=preceding.command_id if preceding else None,
            )

    def _submit(self, command_id, kind, commands, *, preceding=None):
        command_id = _identifier(command_id)
        # Serialize now, so malformed/unencodable requests are rejected before dispatch.
        try:
            encoded = [json.dumps(command, allow_nan=False).encode() for command in commands]
        except (ValueError, TypeError, UnicodeError):
            raise NativeRejected("native_arguments_invalid") from None
        if any(len(frame) > self._max_frame-256 for frame in encoded):
            raise NativeRejected("native_request_too_large")
        with self._lock:
            if self._closed:
                raise NativeRejected("native_channel_closed")
            if command_id in self._seen:
                raise NativeRejected("native_command_already_submitted")
            future = Future()
            future.set_running_or_notify_cancel()
            handle = CommandHandle(self, command_id, future)
            try:
                job = _Job(handle, kind, [json.loads(frame) for frame in encoded], preceding)
                self._queue.put_nowait(job)
            except Full:
                raise NativeRejected("native_channel_busy") from None
            self._pending[command_id] = job
            self._seen.add(command_id)
            return handle

    def _read_ack(self, command_id):
        while b"\n" not in self._buffer:
            block = self._socket.recv(min(65536, self._max_frame-len(self._buffer)+1))
            if not block:
                raise NativeChannelError("native_connection_lost")
            self._buffer.extend(block)
            if len(self._buffer) > self._max_frame:
                raise NativeChannelError("native_response_too_large")
        line, _, remainder = self._buffer.partition(b"\n")
        self._buffer = bytearray(remainder)
        try:
            response = json.loads(line)
        except (ValueError, UnicodeError):
            raise NativeChannelError("native_response_invalid") from None
        if (type(response) is not dict or response.get("id") != command_id
                or type(response.get("success")) is not bool
                or "data" in response and type(response["data"]) is not dict
                or any(key in response and type(response[key]) is not str for key in ("error", "code", "warning"))):
            raise NativeChannelError("native_response_invalid")
        return response

    @staticmethod
    def _incarnation_changed(response):
        lifecycle = response.get("data", {}).get("lifecycle", {})
        return type(lifecycle) is dict and any(lifecycle.get(key) is True for key in ("launched", "relaunchedBrowser"))

    def _execute(self, job):
        response = None
        for index, command in enumerate(job.commands):
            self._check_generation()
            physical_id = job.handle.command_id if len(job.commands) == 1 else f"{job.handle.command_id}:{index}"
            self._socket.sendall(json.dumps({**command, "id":physical_id}, allow_nan=False).encode()+b"\n")
            response = self._read_ack(physical_id)
            if self._incarnation_changed(response):
                raise NativeChannelError("native_browser_incarnation_changed", completed=True)
            try:
                # Native successful close retires .stream before/around ACK
                # delivery. The matching close ACK is retained; it is not an
                # assertion that the daemon process has finished exiting.
                self._check_generation(allow_retired=job.kind == "close" and response["success"])
            except NativeChannelError as error:
                raise NativeChannelError(str(error), completed=True) from None
            if not response["success"]:
                break  # Never continue/retry an interrupted compound gesture.
        if job.kind == "human":
            return HumanAck(job.handle.command_id, True, "applied" if response["success"] else "uncertain")
        if job.kind == "fence":
            return FenceAck(job.handle.command_id, job.preceding, self.generation,
                response["success"] and response.get("data", {}).get("connected") is True)
        # CLI Response serializes data/error as null when absent, omits optional
        # code/warning, and never includes the native protocol id.
        legacy = {"success":response["success"], "data":response.get("data"), "error":response.get("error")}
        legacy.update({key:response[key] for key in ("code", "warning") if key in response})
        return AgentAck(job.handle.command_id, True, legacy)

    def _run(self):
        try:
            while True:
                job = self._queue.get()
                if job is None:
                    return
                with self._lock:
                    if self._closed:
                        return
                try:
                    result = self._execute(job)
                except NativeChannelError as error:
                    self._poison(str(error), job=job, completed=error.completed)
                    return
                except Exception:
                    self._poison("native_connection_lost", job=job)
                    return
                with self._lock:
                    if not job.handle.future.done():
                        job.handle.future.set_result(result)
                    self._pending.pop(job.handle.command_id, None)
                    self._last_completed = job.handle.command_id
                if job.kind == "close":
                    self.close()
                    return
        finally:
            while True:
                try:
                    self._queue.get_nowait()
                except Empty:
                    break

    def _poison(self, code, *, job=None, completed=False):
        with self._lock:
            self._closed = True
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._socket.close()
            for command_id, pending in self._pending.items():
                handle = pending.handle
                if handle.future.done():
                    continue
                is_current = job is not None and command_id == job.handle.command_id
                if pending.kind == "human":
                    handle.future.set_result(HumanAck(command_id, completed if is_current else False, "uncertain"))
                else:
                    handle.future.set_exception(NativeChannelError(code,
                        completed=completed if is_current else False))
            self._pending.clear()

    def close(self):
        """Close transport only; native browser retirement belongs to existing lifecycle."""
        self._poison("native_channel_closed")
        try:
            self._queue.put_nowait(None)
        except Full:
            pass
