"""Disposable, synthetic Selkies/native qualification. No model or live profile.

Run in the qualified test image. The same reviewed native driver used by Hermes
launches one headed Chromium, and all seven agent tools use its existing Unix
channel. The Selkies input handler is guarded in process; no input proxy can
outlive the controller. This module is not an application deployment entrypoint.
"""
import asyncio
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
STATE = Path(os.environ.get("RADHOUSE_QUALIFICATION_STATE", "/state"))
FIXTURE = "http://127.0.0.1:18081/"
NATIVE_NAME = "h_" + secrets.token_hex(5)
SOCKETS = STATE / ("native-" + NATIVE_NAME)
DISPLAY_NUMBER = secrets.randbelow(50000)+100
BROWSER_MODE = os.environ.get("RADHOUSE_BROWSER_MODE", "fixture")
PROXY = os.environ.get("RADHOUSE_REVIEW_PROXY")
SANDBOX_PROOF = None
CHROME_CHILD = None
CHROME_ENDPOINT = None


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


control = load("radhouse_browser_control", ROOT / "runtime/hermes/browser_control.py")
native = load("radhouse_native_control", ROOT / "runtime/hermes/native_control.py")
stream = load("radhouse_selkies_control", Path(__file__).with_name("control.py"))
sandbox = load("radhouse_selkies_sandbox", Path(__file__).with_name("sandbox.py"))


def prepare_environment():
    os.umask(0o077)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    SOCKETS.mkdir(mode=0o700)
    settings = {
        "SELKIES_MASTER_TOKEN": secrets.token_urlsafe(32),
        "SELKIES_MODE": "websockets", "SELKIES_SUBFOLDER": "/stream",
        "SELKIES_WEB_ROOT": "/opt/selkies-web", "SELKIES_ADDR": "0.0.0.0",
        "SELKIES_ENABLE_BASIC_AUTH": "false", "SELKIES_ENABLE_DUAL_MODE": "false",
        "SELKIES_AUDIO_ENABLED": "false", "SELKIES_ENABLE_RESIZE": "false",
        "SELKIES_GAMEPAD_ENABLED": "false|locked", "SELKIES_PRINTING_ENABLED": "false|locked",
        "SELKIES_MICROPHONE_ENABLED": "false|locked", "SELKIES_WEBCAM_ENABLED": "false|locked",
        "SELKIES_SECOND_SCREEN": "false|locked", "SELKIES_COMPUTER_USE_BIND": "",
        "SELKIES_MANUAL_WIDTH": "1280", "SELKIES_MANUAL_HEIGHT": "900",
        "SELKIES_FRAMERATE": "30-30", "SELKIES_ENCODER": "h264enc",
        "SELKIES_ENABLE_CLIPBOARD": "true", "SELKIES_CLIPBOARD_SEAMLESS": "true|locked",
        "SELKIES_ENABLE_BINARY_CLIPBOARD": "false|locked",
        "SELKIES_COMMAND_ENABLED": "false|locked", "SELKIES_ENABLE_COLLAB": "true|locked",
        "SELKIES_USE_CPU": "true",
        "SELKIES_WAYLAND": "false", "SELKIES_GPU_ID": "-1",
        "SELKIES_MAC_CMD_AS_CTRL": "true",
        "DISPLAY": ":"+str(DISPLAY_NUMBER), "SELKIES_PORT": "8080",
    }
    os.environ.update(settings)
    os.environ.pop("PIXELFLUX_CU", None)


def launch_native():
    global CHROME_CHILD, CHROME_ENDPOINT
    if BROWSER_MODE not in {"fixture", "public_web"} or (BROWSER_MODE == "public_web" and not PROXY):
        raise RuntimeError("review_mode_or_proxy_missing")
    env = {k: os.environ[k] for k in ("PATH", "HOME", "DISPLAY", "LANG") if k in os.environ}
    CHROME_CHILD, endpoint = sandbox.launch(STATE / ("profile-" + NATIVE_NAME), env, PROXY)
    CHROME_ENDPOINT = endpoint
    env.update(AGENT_BROWSER_SOCKET_DIR=str(SOCKETS))
    # Attach to our already sandboxed process. The native driver's automatic
    # container launch heuristic adds --no-sandbox, so it must not launch Chrome.
    result = subprocess.run(["/opt/browser/agent-browser", "--config", "/opt/browser/empty.json",
        "--cdp", endpoint, "--session", NATIVE_NAME, "--json", "open", "--", FIXTURE],
        env=env, capture_output=True, timeout=45, check=False)
    value = json.loads(result.stdout or b"{}")
    if result.returncode or not value.get("success"):
        raise RuntimeError("sandboxed_native_attach_failed")


def generation():
    if CHROME_CHILD is None or CHROME_CHILD.poll() is not None:
        raise RuntimeError("owned_browser_unavailable")
    info = (SOCKETS / (NATIVE_NAME + ".stream")).stat()
    return hashlib.sha256(f"{NATIVE_NAME}:{info.st_ino}:{info.st_mtime_ns}".encode()).hexdigest()[:32]


async def run():
    from aiohttp import web
    from selkies import sessions
    from selkies.settings import settings
    from selkies.stream_server import CentralizedStreamServer
    from selkies.websockets_mode import DataStreamingServer, client_permissions, reconcile_clients

    if (settings.enable_collab != (True, True) or settings.command_enabled[0]
            or settings.audio_enabled[0] or settings.enable_resize[0] or settings.wayland[0]
            or settings.microphone_enabled[0] or settings.webcam_enabled[0]
            or settings.second_screen[0] or settings.computer_use_bind):
        raise RuntimeError("effective_browser_settings_unqualified")

    # The upstream malformed-message logger includes payload excerpts. The
    # qualification keeps input contents out of its diagnostic log entirely.
    for name in ("input", "ws"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    identity = control.BrowserIdentity("qualification", "qualification", generation())
    c = control.BrowserController(STATE / ("control-" + NATIVE_NAME + ".sqlite3"), maintenance_held=lambda: False,
        lease_seconds=60)
    run_binding = control.RunBinding(uuid4().hex, identity.session_id, uuid4().hex)
    c.bind_browser(identity, run_binding, "qualification-owner")
    channel = native.NativeControlChannel(SOCKETS / (NATIVE_NAME + ".sock"), identity.generation,
        lambda: generation())
    last_handle = None
    last_observation = None

    # Unprivileged startup proof: owned non-root renderers must have an extra
    # PID namespace and BPF filter, with no sandbox-disabling flags. Host-side
    # deployment verification additionally checks user/network namespace inodes;
    # those links are deliberately unreadable by an unprivileged parent after
    # renderer dumpability is restricted. No page content is used as a proof.
    global SANDBOX_PROOF
    for attempt in range(50):
        try:
            SANDBOX_PROOF = sandbox.verify(CHROME_CHILD.pid, require_namespaces=False)
            break
        except RuntimeError as error:
            if str(error) != "renderer_sandbox_missing" or attempt == 49:
                raise
            await asyncio.sleep(.1)
    (STATE / "sandbox-proof.json").write_text(json.dumps(SANDBOX_PROOF))

    async def fence(state):
        nonlocal last_handle
        handle = channel.fence_after(uuid4().hex, last_handle)
        last_handle = handle
        ack = await handle.wait()
        if not isinstance(ack, native.FenceAck) or not ack.quiescent:
            raise stream.StreamRejected("native_fence_unconfirmed")
        return control.FenceObservation(identity, state.takeover_after, True)

    async def align_visible_page():
        nonlocal last_handle
        target = await sandbox.visible_target(CHROME_ENDPOINT)
        last_handle = channel.submit_trusted_target(uuid4().hex, target)
        selected = await last_handle.wait()
        if not selected.completed or selected.legacy.get("success") is not True:
            raise stream.StreamRejected("visible_page_unconfirmed")
        return target

    async def sensitive_clear():
        target = await align_visible_page()
        try:
            return await sandbox.sensitive_clear(CHROME_ENDPOINT, target)
        except Exception:
            raise stream.StreamRejected("page_check_unconfirmed") from None

    async def observe():
        nonlocal last_handle, last_observation
        if not await sensitive_clear():
            raise stream.StreamRejected("sensitive_fields_present")
        last_handle = channel.submit_tool(uuid4().hex, "browser_snapshot", {})
        snapshot = await last_handle.wait()
        if not snapshot.completed or snapshot.legacy.get("success") is not True:
            raise stream.StreamRejected("native_observation_unconfirmed")
        last_observation = snapshot.legacy["data"]
        return last_observation

    async def resume(owner, revision, observation):
        nonlocal run_binding
        old = run_binding
        fresh = control.RunBinding(uuid4().hex, identity.session_id, uuid4().hex)
        c.admit_run(identity, owner, fresh, lease_id=None, revision=revision,
            previous=control.RunTerminalObservation(old.run_id, old.session_id, "completed"),
            handover=control.HumanReturnObservation(identity, owner, revision, True))
        run_binding = fresh

    async def publish(table):
        sessions.user_tokens = table
        sessions.active_mk_token = next((t for t, p in table.items() if p.get("mk_control")), None)
        data.config_gate.set()
        await reconcile_clients()

    async def clear_clipboard():
        display = data.input_handler.xdisplay
        none = display.create_resource_object("window", 0)
        selections = [display.intern_atom("CLIPBOARD"), display.intern_atom("PRIMARY")]
        for selection in selections:
            none.set_selection_owner(selection, 0)
        display.sync()
        data.input_handler._clipboard_last_bytes = None
        data.input_handler._clipboard_self_write = None
        return all(display.get_selection_owner(selection) == 0 for selection in selections)

    boundary = stream.StreamingControl(c, identity, fence=fence, observe=observe,
        publish=publish, resume=resume, current=generation, clear_clipboard=clear_clipboard,
        sensitive_clear=sensitive_clear)
    desktop = boundary.add_viewer(control.OwnerBinding("qualification-owner", "a"*64, 1, "desktop"), can_take=True, persistent=True)
    phone = boundary.add_viewer(control.OwnerBinding("qualification-owner", "b"*64, 1, "phone"), persistent=True)

    def viewer(request):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise stream.StreamRejected("viewer_unavailable")
        return boundary.viewer(header[7:])

    def public(v):
        state = boundary.state()
        holder = state.mode == "human" and state.lease and state.lease.owner == v.owner
        return {"mode": state.mode, "revision": state.revision, "generation": identity.generation,
            "viewing_only": not v.can_take,
            "can_take": v.can_take and state.mode in {"agent", "paused"},
            "controlling": bool(holder), "lease_id": state.lease.lease_id if holder else None,
            "stream_token": boundary.input_token if holder else v.token,
            "page": FIXTURE, "qualification_only": True,
            "boundary_blocked": boundary._blocked,
            "public_web": BROWSER_MODE == "public_web", "sandbox_enabled": SANDBOX_PROOF is not None}

    async def new_session(request):
        parent = viewer(request)
        v = await boundary.new_session(parent,
            control.OwnerBinding("qualification-owner", secrets.token_hex(32), 1, uuid4().hex),
            connected_tokens={p.get("token") for p in client_permissions.values()})
        return web.json_response({"token": v.token, "state": public(v)})

    async def status(request):
        return web.json_response(public(viewer(request)), headers={"Cache-Control": "no-store"})

    async def diagnostics(request):
        if not viewer(request).can_take:
            raise stream.StreamRejected("viewing_only")
        h = data.input_handler
        return web.json_response({"received": boundary.received, "accepted": boundary.accepted,
            "authorized": boundary.authorized(boundary.input_token),
            "x11_connected": h.xdisplay is not None, "keyboard_connected": h.keyboard is not None,
            "collab": settings.enable_collab[0], "mode": boundary.state().mode,
            "native_pending": last_handle is not None and not last_handle.future.done(),
            "handover_phase": boundary.phase, "input_inflight": boundary.inflight,
            "input_locked": boundary.input_lock.locked(), "transition_locked": boundary.transition_lock.locked(),
            "buttons": h.button_mask, "keys": len(h.pressed_keys),
            "generation_matches": generation() == identity.generation})

    async def takeover(request):
        v = viewer(request)
        body = await request.json()
        await boundary.take(v, request_id=body["request_id"], revision=body["revision"],
            auth_expires_at=time.time()+3600)
        return web.json_response(public(v))

    async def handback(request):
        v = viewer(request)
        if not v.can_take:
            raise stream.StreamRejected("viewing_only")
        body = await request.json()
        await boundary.handback(v, lease_id=body["lease_id"], revision=body["revision"])
        return web.json_response(public(v))

    async def heartbeat(request):
        v = viewer(request)
        body = await request.json()
        c.heartbeat(identity, v.owner, body["lease_id"], body["revision"], auth_expires_at=time.time()+3600)
        return web.json_response(public(v))

    async def agent(request):
        nonlocal last_handle
        v = viewer(request)
        if not v.can_take or boundary._blocked:
            raise stream.StreamRejected("viewing_only")
        body = await request.json()
        name, args = body["tool"], body.get("arguments", {})
        # Validate the exact native map and argument shape before inspecting it.
        native.tool_command(name, args)
        if name == "browser_navigate":
            url = args.get("url", "")
            parsed = urlsplit(url)
            if not url.startswith(FIXTURE) and not (BROWSER_MODE == "public_web"
                    and parsed.scheme in {"http", "https"} and parsed.hostname
                    and parsed.username is None and parsed.password is None):
                raise stream.StreamRejected("review_navigation_rejected")
        command_id = uuid4().hex
        admitted = run_binding
        c.reserve_agent(identity, admitted, command_id)
        outcome = "uncertain"
        try:
            target = await align_visible_page()
            if name == "browser_snapshot" and not await sandbox.sensitive_clear(CHROME_ENDPOINT, target):
                # Nothing was sent to the agent driver; this denial must not
                # strand the owner in uncertain-action recovery.
                outcome = "completed"
                raise stream.StreamRejected("sensitive_fields_present")
            last_handle = channel.submit_tool(command_id, name, args)
            ack = await last_handle.wait()
            outcome = "completed" if ack.completed else "uncertain"
        except stream.StreamRejected:
            raise
        except Exception:
            raise stream.StreamRejected("native_action_unconfirmed") from None
        finally:
            c.complete_agent(identity, admitted, command_id, outcome=outcome)
        await boundary.settle_takeover()
        return web.json_response({"state": public(v), "result": ack.legacy})

    @web.middleware
    async def routes(request, handler):
        if request.path.startswith("/stream/api/") and request.path not in {
            "/stream/api/status", "/stream/api/health", "/stream/api/websockets"}:
            return web.json_response({"error": "browser_only"}, status=403)
        try:
            return await handler(request)
        except stream.StreamRejected as error:
            code = "sensitive_fields_present" if str(error) == "sensitive_fields_present" else "browser_control_rejected"
            return web.json_response({"error": code}, status=409)
        except (control.ControlRejected, native.NativeRejected):
            return web.json_response({"error": "browser_control_rejected"}, status=409)
        except (KeyError, TypeError, ValueError):
            return web.json_response({"error": "invalid_request"}, status=400)

    class Server(CentralizedStreamServer):
        async def initialize_app(self):
            app = await super().initialize_app()
            app.middlewares.insert(0, routes)
            app.router.add_get("/qualification/state", status)
            app.router.add_get("/qualification/diagnostics", diagnostics)
            app.router.add_post("/qualification/session", new_session)
            app.router.add_post("/qualification/take", takeover)
            app.router.add_post("/qualification/return", handback)
            app.router.add_post("/qualification/heartbeat", heartbeat)
            app.router.add_post("/qualification/agent", agent)
            app.router.add_get("/", lambda req: web.FileResponse(Path(__file__).with_name("web") / "index.html"))
            app.router.add_static("/qualification/assets", Path(__file__).with_name("web"))
            return app

    class Data(DataStreamingServer):
        def initialize(self):
            super().initialize()
            boundary.attach(self.input_handler,
                lambda cid: next((p.get("token") for ws, p in client_permissions.items() if id(ws) == cid), None))
            # An explicit copy uses the guarded inline read; no background
            # clipboard synchronization or connect-time clipboard snapshots.
            async def no_clipboard_monitor():
                return
            self.input_handler.start_clipboard = no_clipboard_monitor

    await asyncio.to_thread(settings.resolve_encoder_backends)
    server = Server(settings)
    data = Data(server)
    server.register_service("websockets", data)
    await server.switch_to_mode("websockets")
    await boundary.provision()
    (STATE / "viewer-links.json").write_text(json.dumps({
        "desktop": "http://127.0.0.1:18080/#token="+desktop.token,
        "phone": "http://127.0.0.1:18080/#phone&token="+phone.token}))

    async def watch():
        while True:
            await asyncio.sleep(0.2)
            if generation() != identity.generation:
                raise RuntimeError("owned_browser_unavailable")
            await boundary.reconcile()
            await boundary.settle_takeover()
            connected = {p.get("token") for p in client_permissions.values()}
            # A grant is initially allowed time for the client to connect.
            if boundary.input_token in connected:
                watched[0] = boundary.input_token
            elif watched[0] is not None and watched[0] == boundary.input_token:
                await boundary.disconnect(watched[0])
                watched[0] = None

    watched = [None]
    watchdog = asyncio.create_task(watch())
    task = asyncio.current_task()
    # A dead revocation watcher cannot leave a live input service behind.
    # The existing container restart policy starts a fresh pinned generation.
    watchdog.add_done_callback(lambda done: task.cancel() if not done.cancelled() else None)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        await server.run()
    finally:
        watchdog.cancel()
        await asyncio.gather(watchdog, return_exceptions=True)
        channel.close()


def main():
    prepare_environment()
    processes = [subprocess.Popen(["Xvfb", os.environ["DISPLAY"], "-screen", "0", "1280x900x24", "-ac", "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
        subprocess.Popen([sys.executable, str(Path(__file__).with_name("fixture") / "server.py")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    try:
        for _ in range(100):
            if Path("/tmp/.X11-unix/X"+str(DISPLAY_NUMBER)).exists():
                break
            time.sleep(0.05)
        launch_native()
        try:
            asyncio.run(run())
        except asyncio.CancelledError:
            pass
    finally:
        if CHROME_CHILD is not None and CHROME_CHILD.poll() is None:
            CHROME_CHILD.terminate()
            CHROME_CHILD.wait(timeout=5)
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
