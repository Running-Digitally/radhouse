"""A lazy, owner-operated VM shell. It is independent of agent terminal tools.

Output is an ephemeral byte ring, never a transcript. Private HTTP bearer auth
precedes parsing; the public relay supplies the validated cookie/tab binding.
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import pwd
import re
import signal
import sys
import time
from uuid import uuid4

RING_BYTES = 1_048_576
CHUNK_BYTES = 65_536
CONTEXT_BYTES = 8192
RECONNECT_GRACE = 600
OPERATIONS = frozenset({"open", "status", "output", "input", "resize", "close", "context-scrub"})
_UUID = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}")
_OWNER_KEYS = {"principal_id", "auth_session_digest", "tab_id", "conversation_id", "binding_revision"}


class TerminalRejected(ValueError):
    pass


def _integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise TerminalRejected("terminal_invalid_request")
    return value


def _identifier(value, pattern=_ID):
    if type(value) is not str or not pattern.fullmatch(value):
        raise TerminalRejected("terminal_invalid_request")
    return value


def _owner(body, now):
    owner, expiry = body.get("owner"), body.get("auth_expires_at")
    if type(owner) is not dict or set(owner) != _OWNER_KEYS:
        raise TerminalRejected("terminal_invalid_request")
    for name in ("principal_id", "conversation_id"):
        _identifier(owner[name])
    _identifier(owner["tab_id"], _UUID)
    _identifier(owner["auth_session_digest"], re.compile(r"[a-f0-9]{64}"))
    _integer(owner["binding_revision"], 1, 2**53 - 1)
    if type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry <= now:
        raise TerminalRejected("authentication_required")
    return dict(owner), expiry


def _context(body, scrub):
    text = body.get("text")
    if (type(text) is not str or len(text.encode("utf-8")) > CONTEXT_BYTES
            or body.get("source") not in {"selection", "recent"}
            or type(body.get("captured_at")) is not str or len(body["captured_at"]) > 64
            or type(body.get("truncated")) is not bool):
        raise TerminalRejected("terminal_invalid_request")
    from datetime import datetime
    try:
        if datetime.fromisoformat(body["captured_at"]).tzinfo is None:
            raise ValueError
    except ValueError:
        raise TerminalRejected("terminal_invalid_request") from None
    for name in ("terminal_id", "generation"):
        _identifier(body.get(name), _UUID)
    value = scrub(text)
    if type(value) is not str or len(value.encode("utf-8")) > CONTEXT_BYTES:
        raise TerminalRejected("terminal_context_unavailable")
    return {"kind": "terminal_excerpt", "label": "Agent VM terminal",
        **{name: body[name] for name in ("terminal_id", "generation", "captured_at", "source", "truncated")},
        "text": value}


def _scrub(text):
    from agent.redact import REDACTION_UNAVAILABLE, redact_for_egress, redact_sensitive_text
    value = redact_for_egress(redact_sensitive_text(text, force=True))
    if value == REDACTION_UNAVAILABLE:
        raise TerminalRejected("terminal_context_unavailable")
    return value


def _children(pid, birth):
    """Only descendants of this exact, unreused shell process are candidates."""
    import psutil
    try:
        parent = psutil.Process(pid)
        if parent.create_time() != birth:
            return []
        children = []
        for child in parent.children(recursive=True):
            try:
                children.append((child.pid, child.create_time()))
            except psutil.Error:
                pass  # One already exited child must not hide its siblings.
        return children
    except (psutil.Error, OSError):
        return []


def _cleanup(bridge, birth, known):
    import psutil
    owned = set(known) | set(_children(bridge.pid, birth))
    # The stock bridge reaps its own PTY leader and group. Bash jobs can have
    # separate groups, so finish only the birth-time matched descendants too.
    bridge.close()
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid, created in owned:
            try:
                child = psutil.Process(pid)
                if child.create_time() == created and child.status() != psutil.STATUS_ZOMBIE:
                    child.send_signal(sig)
            except (psutil.Error, OSError):
                pass
        if sig == signal.SIGTERM:
            time.sleep(.15)


@dataclass
class Shell:
    owner: dict
    expiry: float
    bridge: object
    birth: float
    request_id: str
    last_seen: float = 0
    terminal_id: str = field(default_factory=lambda: str(uuid4()))
    generation: str = field(default_factory=lambda: str(uuid4()))
    attach_epoch: int = 1
    ring: bytearray = field(default_factory=bytearray, repr=False)
    cursor: int = 0
    state: str = "open"
    last_sequence: int = 0
    last_outcome: str = "none"
    changed: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    descendants: set = field(default_factory=set, repr=False)
    task: object = field(default=None, repr=False)

    def status(self):
        return {"state": self.state, "terminal_id": self.terminal_id,
            "generation": self.generation, "attach_epoch": self.attach_epoch,
            "next_cursor": self.cursor, "last_sequence": self.last_sequence,
            "last_outcome": self.last_outcome}


class OwnerTerminals:
    def __init__(self, *, cwd, home, shell="/bin/bash", bridge_factory=None, clock=time.time, scrub=_scrub):
        self.cwd, self.home, self.shell = str(cwd), str(home), shell
        self.clock, self.scrub, self.bridge_factory = clock, scrub, bridge_factory
        self.sessions = {}
        self.lock = asyncio.Lock()

    @staticmethod
    def key(owner):
        return tuple(owner[name] for name in ("principal_id", "auth_session_digest", "tab_id"))

    async def _finish(self, item):
        if item.state == "closed":
            return
        item.state = "closed"
        item.changed.set()
        await asyncio.to_thread(_cleanup, item.bridge, item.birth, item.descendants)
        item.ring.clear()

    async def _drain(self, item):
        sampled = 0
        try:
            while item.state != "closed":
                if self.clock() >= min(item.expiry, item.last_seen + RECONNECT_GRACE):
                    async with item.lock:
                        await self._finish(item)
                    return
                if time.monotonic() - sampled > 1:
                    item.descendants.update(await asyncio.to_thread(_children, item.bridge.pid, item.birth))
                    sampled = time.monotonic()
                if item.state == "exited":
                    await asyncio.sleep(.25)
                    continue
                data = await asyncio.to_thread(item.bridge.read, .2)
                if data is None:
                    item.state = "exited"
                    item.changed.set()
                elif data:
                    item.ring.extend(data)
                    item.cursor += len(data)
                    if len(item.ring) > RING_BYTES:
                        del item.ring[:-RING_BYTES]
                    item.changed.set()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Exceptions from the PTY may contain user input. Keep only state.
            async with item.lock:
                await self._finish(item)

    def _bound(self, item, owner, body):
        if (item.owner != owner or body.get("terminal_id") != item.terminal_id
                or body.get("generation") != item.generation
                or body.get("attach_epoch") != item.attach_epoch):
            raise TerminalRejected("terminal_binding_changed")

    async def call(self, operation, body):
        if operation not in OPERATIONS or type(body) is not dict:
            raise TerminalRejected("terminal_invalid_request")
        fields = {"open": {"request_id", "cols", "rows"}, "status": set(),
            "output": {"terminal_id", "generation", "attach_epoch", "cursor", "wait_ms"},
            "input": {"terminal_id", "generation", "attach_epoch", "sequence", "data_b64"},
            "resize": {"terminal_id", "generation", "attach_epoch", "cols", "rows"},
            "close": {"terminal_id", "generation", "attach_epoch"},
            "context-scrub": {"terminal_id", "generation", "text", "source", "captured_at", "truncated"}}
        if set(body) != fields[operation] | {"owner", "auth_expires_at"}:
            raise TerminalRejected("terminal_invalid_request")
        owner, expiry = _owner(body, self.clock())
        if operation == "context-scrub":
            return _context(body, self.scrub)
        key = self.key(owner)
        if operation == "open":
            _identifier(body.get("request_id"), _UUID)
            cols, rows = _integer(body.get("cols"), 2, 2000), _integer(body.get("rows"), 2, 1000)
            async with self.lock:
                # Closed shells retain no replay ledger or output. Bound RAM
                # by dropping their tombstones before another explicit Open.
                self.sessions = {key: item for key, item in self.sessions.items() if item.state != "closed"}
                item = self.sessions.get(key)
                if item and item.state != "closed":
                    async with item.lock:
                        if item.request_id != body["request_id"] or item.owner != owner:
                            item.attach_epoch += 1
                            item.request_id = body["request_id"]
                        item.owner, item.expiry, item.last_seen = owner, expiry, self.clock()
                        item.bridge.resize(cols, rows)
                        return item.status()
                if sum(item.state != "closed" for item in self.sessions.values()) >= 8:
                    raise TerminalRejected("terminal_capacity_reached")
                from hermes_cli.pty_bridge import PtyBridge
                import psutil
                factory = self.bridge_factory or PtyBridge.spawn
                # Never inherit provider tokens, preload hooks, shell profiles,
                # BASH_ENV or PROMPT_COMMAND from the gateway process.
                env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": self.home, "TERM": "xterm-256color",
                    "LC_ALL": "en_US.UTF-8" if sys.platform == "darwin" else "C.UTF-8"}
                bridge = await asyncio.to_thread(factory,
                    [self.shell, "--noprofile", "--norc", "+o", "history", "-i"],
                    cwd=self.cwd, env=env, cols=cols, rows=rows)
                try:
                    birth = psutil.Process(bridge.pid).create_time()
                except Exception:
                    await asyncio.to_thread(bridge.close)
                    raise TerminalRejected("terminal_unavailable") from None
                item = Shell(owner, expiry, bridge, birth, body["request_id"], last_seen=self.clock())
                self.sessions[key] = item
                item.task = asyncio.create_task(self._drain(item))
                return item.status()
        item = self.sessions.get(key)
        if item is None or item.state == "closed":
            if operation == "status":
                return {"state": "closed", "terminal_id": None, "generation": None,
                    "attach_epoch": 0, "next_cursor": 0, "last_sequence": 0, "last_outcome": "none"}
            raise TerminalRejected("terminal_closed")
        async with item.lock:
            if operation == "status":
                if item.owner != owner:
                    raise TerminalRejected("terminal_binding_changed")
                item.expiry, item.last_seen = expiry, self.clock()
                return item.status()
            self._bound(item, owner, body)
            item.expiry, item.last_seen = expiry, self.clock()
            if operation == "input":
                sequence = _integer(body.get("sequence"), 1, 2**53 - 1)
                if sequence != item.last_sequence + 1:
                    raise TerminalRejected("terminal_input_out_of_order")
                try:
                    if type(body.get("data_b64")) is not str or len(body["data_b64"]) > 87_384:
                        raise ValueError
                    data = base64.b64decode(body["data_b64"], validate=True)
                    if not 1 <= len(data) <= CHUNK_BYTES:
                        raise ValueError
                except ValueError:
                    raise TerminalRejected("terminal_invalid_request") from None
                if item.state != "open":
                    raise TerminalRejected("terminal_closed")
                item.descendants.update(await asyncio.to_thread(_children, item.bridge.pid, item.birth))
                item.last_sequence, item.last_outcome = sequence, "uncertain"
                try:
                    if await item.bridge.write(data, timeout=10):
                        item.last_outcome = "written"
                except Exception:
                    pass
                return item.status()
            if operation == "resize":
                item.bridge.resize(_integer(body.get("cols"), 2, 2000), _integer(body.get("rows"), 2, 1000))
                return item.status()
            if operation == "close":
                await self._finish(item)
                return item.status()
            cursor = _integer(body.get("cursor"), 0, 2**53 - 1)
            wait = _integer(body.get("wait_ms"), 0, 15_000) / 1000
            if cursor > item.cursor:
                raise TerminalRejected("terminal_invalid_cursor")
            item.changed.clear()
        if cursor == item.cursor and item.state == "open" and wait:
            try:
                await asyncio.wait_for(item.changed.wait(), wait)
            except TimeoutError:
                pass
        async with item.lock:
            # An explicit reattach while a poll was waiting fences its result.
            self._bound(item, owner, body)
            if self.clock() >= expiry:
                raise TerminalRejected("authentication_required")
            start = max(cursor, item.cursor - len(item.ring))
            data = bytes(item.ring[start - (item.cursor - len(item.ring)):][:CHUNK_BYTES])
            return {**item.status(), "data_b64": base64.b64encode(data).decode("ascii"),
                "next_cursor": start + len(data), "truncated": start != cursor}

    async def shutdown(self):
        for item in self.sessions.values():
            async with item.lock:
                await self._finish(item)
            if item.task:
                item.task.cancel()
        await asyncio.gather(*(item.task for item in self.sessions.values() if item.task), return_exceptions=True)
        self.sessions.clear()


_manager = None


def configure_owner_terminal(*, cwd=None, shell="/bin/bash"):
    global _manager
    if _manager is not None:
        return
    # The launcher may chdir into its immutable release. Start in the existing
    # OS user's home instead, independently of inherited HOME/profile markers.
    home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve(strict=True)
    directory = Path(cwd or home).resolve(strict=True)
    if not directory.is_dir() or shell != "/bin/bash":
        raise ValueError("terminal_configuration_invalid")
    _manager = OwnerTerminals(cwd=directory, home=home, shell=shell)


def owner_terminal_features():
    try:
        from hermes_cli.pty_bridge import PtyBridge
        supported = PtyBridge.is_available() and os.path.isfile("/bin/bash")
    except ImportError:
        supported = False
    return {"owner_terminal": {"supported": supported, "version": 1, "mode": "owner_vm_shell"}}


async def handle_owner_terminal(adapter, request, *, operation):
    error = adapter._check_auth(request)
    if error is not None:
        return error
    from aiohttp import web
    headers = {"Cache-Control": "no-store"}
    try:
        if request.query or request.content_length and request.content_length > 100_000:
            raise TerminalRejected("terminal_invalid_request")
        configure_owner_terminal()
        value = await _manager.call(operation, await request.json())
        return web.json_response(value, headers=headers)
    except TerminalRejected as exc:
        code = str(exc)
        status = 401 if code == "authentication_required" else 422 if code == "terminal_invalid_request" else 409
        return web.json_response({"error": code}, status=status, headers=headers)
    except Exception:
        return web.json_response({"error": "terminal_unavailable"}, status=503, headers=headers)


async def shutdown_owner_terminals():
    if _manager is not None:
        await _manager.shutdown()
