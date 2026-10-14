"""Qualification adapter for Selkies input and the existing native controller.

The input lock spans authorization and X11 dispatch. Handback closes the grant
before waiting for that lock, releases held input, and synchronizes the same X
connection before a fresh native observation. Tokens and input contents are not
stored in the controller. This adapter deliberately qualifies X11 only.
"""
import asyncio
import base64
import secrets
from contextvars import ContextVar
from dataclasses import dataclass, field


class StreamRejected(ValueError):
    pass


@dataclass(frozen=True)
class Viewer:
    owner: object
    can_take: bool
    token: str = field(repr=False)


class StreamingControl:
    # A closed allowlist excludes resize, shell, gamepads, media and file APIs.
    INPUT = frozenset({"kd", "ku", "kr", "kh", "m", "m2", "co", "cw", "cws", "cwd", "cwe", "REQUEST_CLIPBOARD"})

    def __init__(self, controller, identity, *, fence, observe, publish, resume, current, clear_clipboard, sensitive_clear):
        self.controller, self.identity = controller, identity
        self.fence, self.observe, self.publish = fence, observe, publish
        self.resume = resume
        self.current = current
        self.clear_clipboard = clear_clipboard
        self.sensitive_clear = sensitive_clear
        self.viewers = {}
        self.input_token = None
        self.input_owner = None
        self.handler = None
        self.input_lock = asyncio.Lock()
        self.transition_lock = asyncio.Lock()
        self._dispatch = None
        self._lookup = None
        self._blocked = False
        self.received = 0
        self.accepted = 0
        self.inflight = None
        self.phase = "idle"
        self._dispatch_task = None
        self._drain_task = None
        self._repeat_enabled = False
        self._scope = ContextVar("radhouse_stream_injection", default=None)
        self._keyboard = None

    def add_viewer(self, owner, *, can_take=False):
        token = secrets.token_urlsafe(32)
        viewer = Viewer(owner, can_take, token)
        self.viewers[token] = viewer
        return viewer

    def viewer(self, token):
        viewer = self.viewers.get(token)
        if viewer is None:
            raise StreamRejected("viewer_unavailable")
        return viewer

    def state(self):
        return self.controller.state(self.identity)

    async def _publish(self):
        table = {token: {"role": "viewer", "slot": None} for token in self.viewers}
        if self.input_token is not None:
            table[self.input_token] = {"role": "viewer", "slot": None, "mk_control": True}
        await self.publish(table)

    def attach(self, handler, lookup):
        if getattr(handler, "is_wayland", True):
            raise StreamRejected("x11_required")
        if self.handler is not None:
            raise StreamRejected("input_handler_already_bound")
        self.handler, self._dispatch, self._lookup = handler, handler.on_message, lookup
        self._repeat_enabled = getattr(handler, "key_repeat_enabled", False)
        handler.on_message = self.dispatch
        for name in ("send_x11_keypress", "send_x11_mouse"):
            if hasattr(handler, name):
                original = getattr(handler, name)
                async def guarded(*args, _original=original, **kwargs):
                    return await self._inject(_original, *args, **kwargs)
                setattr(handler, name, guarded)

    async def _inject(self, original, *args, **kwargs):
        self._bind_keyboard()
        task = asyncio.current_task()
        if task is self._dispatch_task or task is self._drain_task:
            return await original(*args, **kwargs)
        epoch = self.input_token
        async with self.input_lock:
            if not self.authorized(epoch):
                return
            self._dispatch_task = task
            scope = {"active": True}
            reset = self._scope.set(scope)
            try:
                return await original(*args, **kwargs)
            finally:
                scope["active"] = False
                self._scope.reset(reset)
                self._dispatch_task = None

    def _bind_keyboard(self):
        keyboard = getattr(self.handler, "keyboard", None)
        if keyboard is None or keyboard is self._keyboard:
            return
        self._keyboard = keyboard
        for name in ("press", "release"):
            original = getattr(keyboard, name)
            def guarded(*args, _original=original, **kwargs):
                scope = self._scope.get()
                # to_thread carries the accepted operation's context. Its
                # mutable lifetime marker also expires inherited child tasks.
                if scope is not None and scope["active"]:
                    return _original(*args, **kwargs)
                # X11's repeat loop has a synchronous atomic-key path. On this
                # one event loop it cannot interleave with a held input lock.
                if not self.input_lock.locked() and self.authorized(self.input_token):
                    return _original(*args, **kwargs)
            setattr(keyboard, name, guarded)

    def authorized(self, token):
        if self._blocked or token is None or token != self.input_token:
            return False
        try:
            if self.current() != self.identity.generation:
                return False
            state = self.state()
        except Exception:
            return False
        return bool(state.mode == "human" and state.lease is not None
                    and state.lease.owner == self.input_owner
                    and not state.retired and state.active_command is None)

    async def dispatch(self, message, display_id="primary", conn_id=None):
        self.received += 1
        # Never pass unknown or malformed payloads into upstream's payload logs.
        if not isinstance(message, str) or len(message) > 128 * 1024:
            return
        verb = message.split(",", 1)[0]
        # Upstream viewer connections leave their transport display ID unset;
        # their SETTINGS branch joins primary without claiming a display.
        # This candidate owns exactly one display, so normalize that trusted
        # viewer case and refuse every explicit secondary display.
        if verb not in self.INPUT or display_id not in {None, "primary"}:
            return
        if verb == "co" and not message.startswith("co,end,"):
            return
        if verb in {"cw", "cwd"}:
            try:
                if len(base64.b64decode(message.rsplit(",", 1)[1], validate=True)) > 65536:
                    return
            except (ValueError, IndexError):
                return
        if verb == "cws":
            try:
                if not 0 < int(message.split(",")[2]) <= 65536:
                    return
            except (ValueError, IndexError):
                return
        task = asyncio.current_task()
        # Selkies turns punctuation into co,end by calling its own on_message.
        # That is part of the already-admitted operation, not a new transport
        # request. Reacquiring the lock here would deadlock the input boundary.
        if conn_id is None and (task is self._dispatch_task or task is self._drain_task):
            return await self._dispatch(message, "primary", conn_id=None)
        repeat = conn_id is None and task is getattr(self.handler, "key_repeat_task", None)
        if conn_id is None and not repeat:
            return
        epoch = self.input_token if repeat else self._lookup(conn_id)
        async with self.input_lock:
            token = epoch
            if not self.authorized(token):
                return
            self.accepted += 1
            self.inflight = verb
            self._dispatch_task = task
            self._bind_keyboard()
            scope = {"active": True}
            reset = self._scope.set(scope)
            try:
                if verb == "REQUEST_CLIPBOARD":
                    # Keep an explicit copy inside the input boundary and
                    # target only its requester, without an untracked task.
                    await asyncio.sleep(0.15)
                    data, mime = await self.handler.read_clipboard(use_binary=False)
                    if self.authorized(token):
                        await self.handler.send_clipboard_data(data or "", mime or "text/plain", conn_id=conn_id)
                    return
                await self._dispatch(message, "primary", conn_id=conn_id)
            finally:
                scope["active"] = False
                self._scope.reset(reset)
                self.inflight = None
                self._dispatch_task = None

    async def provision(self):
        async with self.transition_lock:
            await self._publish()

    async def take(self, viewer, *, request_id, revision, auth_expires_at):
        if not viewer.can_take or self.viewers.get(viewer.token) is not viewer:
            raise StreamRejected("viewing_only")
        if self._blocked or self.handler is None:
            raise StreamRejected("input_boundary_unavailable")
        if self.current() != self.identity.generation:
            raise StreamRejected("stale_browser")
        async with self.transition_lock:
            state = self.controller.request_takeover(self.identity, viewer.owner,
                request_id, revision=revision, auth_expires_at=auth_expires_at)
            if state.mode == "human":
                return state
            if state.active_command is not None:
                return state
            return await self._grant(state)

    async def _grant(self, state):
        # Both the in-flight native ACK and its same-channel fence are required.
        observation = await self.fence(state)
        async with self.input_lock:
            state = self.controller.confirm_takeover(self.identity, state.revision, observation)
            self.input_owner = state.lease.owner
            self.input_token = secrets.token_urlsafe(32)
            self.handler.key_repeat_enabled = self._repeat_enabled
            try:
                await self._publish()
            except Exception:
                self.input_token = None
                self._blocked = True
                self.controller.pause(self.identity, self.input_owner)
                raise StreamRejected("grant_unconfirmed") from None
            return state

    async def settle_takeover(self):
        async with self.transition_lock:
            state = self.state()
            if state.mode == "takeover_pending" and state.active_command is None:
                return await self._grant(state)
            return state

    async def _drain(self):
        if self.handler is not None:
            self.handler.key_repeat_enabled = False
        async with self.input_lock:
            self._drain_task = asyncio.current_task()
            self._bind_keyboard()
            scope = {"active": True}
            reset = self._scope.set(scope)
            try:
                await self._drain_locked()
            finally:
                scope["active"] = False
                self._scope.reset(reset)
                self._drain_task = None

    async def _drain_locked(self):
        handler = self.handler
        if handler is None or getattr(handler, "is_wayland", True) or handler.xdisplay is None:
            raise StreamRejected("input_boundary_unavailable")
        await handler.release_mouse_buttons()
        await handler.reset_keyboard()
        # This is the injecting connection's X round trip, after input and
        # releases. A different X connection would not establish ordering.
        handler.xdisplay.sync()
        if handler.button_mask or handler.pressed_keys or handler.translated_keys:
            raise StreamRejected("held_input_unconfirmed")
        if (any(handler.xdisplay.query_keymap())
                or handler.xdisplay.screen().root.query_pointer().mask & 0x1f00):
            raise StreamRejected("physical_input_unconfirmed")
        handler._reset_multipart_clipboard()
        if not await self.clear_clipboard():
            raise StreamRejected("clipboard_clear_unconfirmed")
        handler.xdisplay.sync()

    async def handback(self, viewer, *, lease_id, revision):
        self.phase = "transition_wait"
        async with self.transition_lock:
            self.phase = "input_wait"
            async with self.input_lock:
                self.phase = "sensitive_check"
                state = self.state()
                if (state.mode != "human" or state.lease is None or state.lease.owner != viewer.owner
                        or state.lease.lease_id != lease_id or state.revision != revision):
                    raise StreamRejected("control_lease_unavailable")
                if not await self.sensitive_clear():
                    self.phase = "idle"
                    raise StreamRejected("sensitive_fields_present")
                state = self.controller.begin_return(self.identity, viewer.owner, lease_id, revision)
                self.input_token = None
            # Revoke native authority first. Events already inside dispatch may
            # finish, but agent admission remains closed until _drain returns.
            try:
                self.phase = "revoke"
                await self._publish()
                self.phase = "drain"
                await self._drain()
                self.phase = "observe"
                observation = await self.observe()
                self.phase = "resume"
                await self.resume(viewer.owner, state.revision, observation)
            except Exception:
                self.phase = "unconfirmed"
                self._blocked = True
                raise StreamRejected("handback_unconfirmed") from None
            self.input_owner = None
            self.phase = "idle"
            return observation

    async def reconcile(self):
        async with self.transition_lock:
            state = self.state()
            if self.input_token is not None and not self.authorized(self.input_token):
                if state.mode == "human":
                    state = self.controller.pause(self.identity, self.input_owner)
                self.input_token = None
                try:
                    await self._publish()
                    await self._drain()
                except Exception:
                    self._blocked = True
                    raise StreamRejected("revocation_unconfirmed") from None
                self.input_owner = None
            return state

    async def disconnect(self, token):
        if token != self.input_token:
            return
        async with self.transition_lock:
            if token != self.input_token:
                return
            self.controller.pause(self.identity, self.input_owner)
            self.input_token = None
            try:
                await self._publish()
                await self._drain()
            except Exception:
                self._blocked = True
                raise StreamRejected("disconnect_unconfirmed") from None
            self.input_owner = None
