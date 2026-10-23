"""Private browser execution service inside one SPACE microVM.

No model, shell, file, vault or SPACE management API. The external Radhouse
controller supplies short-lived execution grants; guest input checks them at
injection, and loss of renewal retires every transport capability.
"""
import argparse
import asyncio
import contextlib
import hmac
import importlib.util
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import time
from urllib.parse import urlsplit

HERE = Path(__file__).parent


def load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


protocol = load("radhouse_space_protocol", HERE / "space_protocol.py")
stream = load("radhouse_guest_input", HERE / "control.py")
sandbox = load("radhouse_guest_sandbox", HERE / "sandbox.py")
resources = load("radhouse_guest_resources", HERE / "resources.py")


class InputBoundary(stream.StreamingControl):
    def authorized(self, capability):
        return not self._blocked and self.grants.allowed(capability)


class Guest:
    def __init__(self, state, proxy, credential):
        if os.geteuid() == 0:
            raise RuntimeError("non_root_service_required")
        protocol.token(credential)
        parsed = urlsplit(proxy)
        if (parsed.scheme != "http" or not parsed.hostname or not parsed.port
                or parsed.username or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment):
            raise RuntimeError("fixed_public_proxy_required")
        self.state = Path(state)
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.state.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError("private_state_required")
        self.proxy, self.credential = proxy, credential
        self.database = sqlite3.connect(self.state / "launches.sqlite3")
        self.database.execute("CREATE TABLE IF NOT EXISTS launches (id TEXT PRIMARY KEY, state TEXT NOT NULL)")
        self.database.commit()
        # A service restart is not permission to silently adopt or replace a
        # previously active browser. Its recorded identity must be retired first.
        self.launch_id = None
        self.sequence = 0
        self.command_lock = asyncio.Lock()
        self.grants = protocol.GrantFence()
        self.child = self.display = self.server = self.data = self.boundary = None
        self.endpoint = None
        self.proof = None
        self.watcher = None
        self.pipes = set()
        self.faulted = False
        self.started_at = None

    def record(self, identity, state):
        self.database.execute("INSERT INTO launches VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET state=excluded.state", (identity, state))
        self.database.commit()

    def running(self):
        return self.child is not None and self.child.poll() is None

    def status(self):
        connected = []
        if self.data is not None:
            connected = list({p.get("token") for p in self.permissions.values() if p.get("token")})
        return {"state": "running" if self.running() else ("unavailable" if self.launch_id else "retired"), "connected": connected,
                "faulted": self.faulted}

    async def start(self, identity):
        if self.launch_id is not None:
            raise protocol.Rejected("browser_already_owned")
        if self.database.execute("SELECT 1 FROM launches WHERE id=? OR state!='retired'", (identity,)).fetchone():
            raise protocol.Rejected("previous_browser_unresolved")
        self.launch_id = identity
        self.record(identity, "starting")
        self.directory = self.state / identity
        self.directory.mkdir(mode=0o700)
        self.grants = protocol.GrantFence()
        self.faulted = False
        self.started_at = time.monotonic()
        try:
            await asyncio.to_thread(self.launch_display_and_chrome)
            await self.start_stream()
            self.record(identity, "running")
            self.watcher = asyncio.create_task(self.watch())
            return {**self.status(), "browser_path": self.browser_path,
                    "sandbox": self.proof, "public_egress": True}
        except BaseException:
            await self.stop()
            raise

    def launch_display_and_chrome(self):
        display = ":" + str(secrets.randbelow(50000) + 100)
        authority = self.directory / "Xauthority"
        authority.touch(mode=0o600)
        subprocess.run(["/usr/bin/xauth", "-f", str(authority), "add", display, ".", secrets.token_hex(16)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG") if k in os.environ}
        home = self.directory / "home"
        home.mkdir(mode=0o700)
        env["HOME"] = str(home)
        env.update(DISPLAY=display, XAUTHORITY=str(authority))
        self.display = subprocess.Popen(["/usr/bin/Xvfb", display, "-screen", "0", "1280x900x24",
            "-nolisten", "tcp", "-auth", str(authority), "-noreset"], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if self.display.poll() is not None:
                raise RuntimeError("display_unavailable")
            if Path("/tmp/.X11-unix/X" + display[1:]).exists():
                break
            time.sleep(.05)
        else:
            raise RuntimeError("display_unavailable")
        os.environ.update(DISPLAY=display, XAUTHORITY=str(authority))
        profile = self.directory / "profile"
        profile.mkdir(mode=0o700)
        self.child = subprocess.Popen(sandbox.chrome_arguments(profile, self.proxy,
            start_url="about:blank", public_only=True), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.endpoint = sandbox.wait_ready(self.child, profile)
        self.browser_path = (profile / "DevToolsActivePort").read_text().splitlines()[1]
        for attempt in range(100):
            try:
                self.proof = sandbox.verify(self.child.pid, require_namespaces=False)
                break
            except RuntimeError:
                if attempt == 99:
                    raise
                time.sleep(.05)

    async def start_stream(self):
        os.environ.update({
            "SELKIES_MASTER_TOKEN": secrets.token_urlsafe(32),
            "SELKIES_MODE": "websockets", "SELKIES_SUBFOLDER": "/chat/browser/stream",
            "SELKIES_WEB_ROOT": "/opt/selkies-web", "SELKIES_UNIX_SOCKET": str(self.directory / "stream.sock"),
            "SELKIES_JS_SOCKET_PATH": str(self.directory), "SELKIES_WEBCAM_SOCKET_PATH": str(self.directory),
            "SELKIES_ENABLE_BASIC_AUTH": "false", "SELKIES_ENABLE_DUAL_MODE": "false",
            "SELKIES_AUDIO_ENABLED": "false", "SELKIES_ENABLE_RESIZE": "false",
            "SELKIES_GAMEPAD_ENABLED": "false|locked", "SELKIES_PRINTING_ENABLED": "false|locked",
            "SELKIES_MICROPHONE_ENABLED": "false|locked", "SELKIES_WEBCAM_ENABLED": "false|locked",
            "SELKIES_SECOND_SCREEN": "false|locked", "SELKIES_COMPUTER_USE_BIND": "",
            "SELKIES_MANUAL_WIDTH": "1280", "SELKIES_MANUAL_HEIGHT": "900",
            "SELKIES_FRAMERATE": "30-30", "SELKIES_ENCODER": "h264enc",
            "SELKIES_ENABLE_CLIPBOARD": "true", "SELKIES_CLIPBOARD_SEAMLESS": "true|locked",
            "SELKIES_ENABLE_BINARY_CLIPBOARD": "false|locked", "SELKIES_COMMAND_ENABLED": "false|locked",
            "SELKIES_ENABLE_COLLAB": "true|locked", "SELKIES_USE_CPU": "true",
            "SELKIES_WAYLAND": "false", "SELKIES_GPU_ID": "-1", "SELKIES_MAC_CMD_AS_CTRL": "true"})
        os.environ.pop("PIXELFLUX_CU", None)
        from selkies import sessions
        from selkies.settings import settings
        from selkies.stream_server import CentralizedStreamServer
        from selkies.websockets_mode import DataStreamingServer, client_permissions, reconcile_clients
        settings.unix_socket = str(self.directory / "stream.sock")
        settings.js_socket_path = settings.webcam_socket_path = str(self.directory)
        settings.master_token = os.environ["SELKIES_MASTER_TOKEN"]
        if (settings.enable_collab != (True, True) or settings.command_enabled[0]
                or settings.audio_enabled[0] or settings.enable_resize[0] or settings.wayland[0]
                or settings.microphone_enabled[0] or settings.webcam_enabled[0]
                or settings.second_screen[0] or settings.computer_use_bind):
            raise RuntimeError("stream_settings_unqualified")
        for name in ("input", "ws"):
            logging.getLogger(name).setLevel(logging.CRITICAL)
        self.sessions, self.reconcile_clients, self.permissions = sessions, reconcile_clients, client_permissions

        async def unused(*args):
            raise RuntimeError("controller_operation_not_available_in_guest")

        async def clear_clipboard():
            handler = self.data.input_handler
            display = handler.xdisplay
            none = display.create_resource_object("window", 0)
            selections = [display.intern_atom("CLIPBOARD"), display.intern_atom("PRIMARY")]
            for selection in selections:
                none.set_selection_owner(selection, 0)
            display.sync()
            handler._clipboard_last_bytes = handler._clipboard_self_write = None
            return all(display.get_selection_owner(s) == 0 for s in selections)

        boundary = self.boundary = InputBoundary(None, self.launch_id, fence=unused,
            observe=unused, publish=unused, resume=unused, current=lambda: self.launch_id,
            clear_clipboard=clear_clipboard, sensitive_clear=unused)
        boundary.grants = self.grants

        class Data(DataStreamingServer):
            def initialize(inner):
                super().initialize()
                inner.input_handler.num_gamepads = 0
                boundary.attach(inner.input_handler,
                    lambda cid: next((p.get("token") for ws, p in client_permissions.items() if id(ws) == cid), None))

                async def no_clipboard_monitor():
                    return
                inner.input_handler.start_clipboard = no_clipboard_monitor

        await asyncio.to_thread(settings.resolve_encoder_backends)
        self.server = CentralizedStreamServer(settings)
        self.data = Data(self.server)
        self.server.register_service("websockets", self.data)
        await self.server.switch_to_mode("websockets")
        await self.update_sessions()
        await self.server.start_server()

    async def update_sessions(self):
        self.sessions.user_tokens = self.grants.table
        self.sessions.active_mk_token = self.grants.input_token
        self.boundary.input_token = self.grants.input_token
        if self.boundary.handler is not None:
            self.boundary.handler.key_repeat_enabled = bool(
                self.grants.allowed(self.grants.input_token) and self.boundary._repeat_enabled)
        self.data.config_gate.set()
        await self.reconcile_clients()

    async def drain(self):
        if self.boundary is not None:
            await self.boundary._drain()

    async def revoke(self):
        self.grants.revoke()
        try:
            if self.boundary is not None:
                self.boundary._blocked = True
                await self.update_sessions()
                await self.drain()
        finally:
            await asyncio.gather(*(p.close(code=1008) for p in list(self.pipes)))

    async def watch(self):
        pressure_checked = 0
        try:
            while True:
                await asyncio.sleep(.1)
                expired = (not self.grants.live() if self.grants.initialized
                    else time.monotonic() - self.started_at >= 60)
                if not self.running() or expired:
                    self.faulted = True
                    await self.revoke()
                    return
                if time.monotonic() - pressure_checked >= 2 and resources.pressure():
                    pressure_checked = time.monotonic()
                    with contextlib.suppress(Exception):
                        await sandbox.notify_memory_pressure(self.endpoint)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.faulted = True
            self.grants.revoke()
            for pipe in list(self.pipes):
                await pipe.close(code=1011)

    async def stop(self):
        if self.watcher is not None:
            self.watcher.cancel()
            await asyncio.gather(self.watcher, return_exceptions=True)
        # Process retirement is still attempted after a failed input/stream drain.
        failure = None
        try:
            await self.revoke()
        except Exception:
            pass  # Confirmed process/transport death below supersedes an input ACK.
        finally:
            if self.server is not None:
                try:
                    await self.server.stop_server()
                except Exception as error:
                    failure = error
            for process in (self.child, self.display):
                if process is not None and process.poll() is None:
                    try:
                        process.terminate()
                        try:
                            await asyncio.to_thread(process.wait, 8)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            await asyncio.to_thread(process.wait, 8)
                    except Exception as error:
                        failure = error
        if failure is not None or any(p.poll() is None for p in (self.child, self.display) if p is not None):
            self.faulted = True
            raise protocol.Uncertain("browser_retirement_unconfirmed") from None
        if self.launch_id is not None:
            # Match the current local worker's ephemeral-profile contract.
            # Retirement must not silently turn browsing history and cookies
            # into an indefinitely retained archive on the guest disk.
            directory = self.state / self.launch_id
            if directory.exists():
                info = directory.lstat()
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                    raise protocol.Uncertain("browser_retirement_unconfirmed")
                shutil.rmtree(directory)
            self.record(self.launch_id, "retired")
        self.child = self.display = self.server = self.data = self.boundary = None
        self.launch_id = None
        self.sequence = 0
        return {"state": "retired", "connected": []}

    async def execute(self, value):
        operation, body, identity = value["op"], value["body"], value["launch_id"]
        async with self.command_lock:
            if operation == "start":
                if self.launch_id is not None:
                    raise protocol.Rejected("browser_already_owned")
                self.sequence = value["sequence"]
                return await self.start(identity)
            # A lost stop reply is reconciled from the durable retirement receipt.
            # This never repeats launch or replaces a newer generation.
            if identity != self.launch_id and operation in {"status", "stop"}:
                row = self.database.execute("SELECT state FROM launches WHERE id=?", (identity,)).fetchone()
                if row == ("retired",):
                    return {"state": "retired", "connected": [], "faulted": False}
            if identity != self.launch_id or value["sequence"] <= self.sequence:
                raise protocol.Rejected("stale_browser_request")
            self.sequence = value["sequence"]
            if operation == "status":
                return self.status()
            if operation == "stop":
                return await self.stop()
            if not self.running() or self.faulted:
                raise protocol.Rejected("browser_unavailable")
            if operation in {"publish", "renew"}:
                ttl = min(body["ttl"], body["not_after"] - time.time())
                protocol.duration(ttl)
                if operation == "publish":
                    holder = protocol.grants(body["table"])
                    # Revoke old input before waiting for its in-flight X11 ACK.
                    if holder != self.grants.input_token:
                        self.boundary._blocked = True
                        await self.drain()
                    self.grants.publish(body["table"], ttl)
                    self.boundary._blocked = False
                    await self.update_sessions()
                else:
                    self.grants.renew(ttl)
                return self.status()
            if operation == "freeze":
                self.grants.freeze(value["request_id"])
                await self.drain()
                return {"freeze_id": value["request_id"], "drained": True}
            if operation == "thaw":
                self.grants.thaw(body["freeze_id"])
                await self.update_sessions()
                return {"released": True}
            if operation == "drain":
                await self.drain()
                return {"drained": True}
            raise protocol.Rejected("invalid_operation")

    def application(self):
        from aiohttp import web, ClientSession, ClientTimeout, UnixConnector, WSMsgType

        @web.middleware
        async def authenticated(request, handler):
            supplied = request.headers.get("X-Radhouse-Browser-Service", "")
            if not hmac.compare_digest(supplied.encode(), self.credential.encode()):
                return web.json_response({"error": "unauthorized"}, status=401)
            try:
                return await handler(request)
            except protocol.Rejected:
                return web.json_response({"error": "browser_request_rejected"}, status=409)
            except web.HTTPException:
                raise
            except Exception as error:
                # Never log exception text, URLs, request bodies or credentials.
                frame = error.__traceback__
                while frame is not None and frame.tb_next is not None:
                    frame = frame.tb_next
                location = (Path(frame.tb_frame.f_code.co_filename).name, frame.tb_lineno) if frame else ('unknown', 0)
                logging.getLogger(__name__).warning('Browser request failed: kind=%s source=%s:%s',
                    type(error).__name__, *location)
                return web.json_response({"error": "browser_outcome_unconfirmed"}, status=503)

        async def rpc(request):
            try:
                value = protocol.request(await request.json())
            except (ValueError, TypeError, KeyError):
                return web.json_response({"error": "invalid_request"}, status=400)
            result = await self.execute(value)
            return web.json_response({**{k: value[k] for k in ("schema", "launch_id", "request_id", "sequence")},
                "data": result}, headers={"Cache-Control": "no-store"})

        def current(request):
            if (not self.running() or self.faulted or self.grants.initialized and not self.grants.live()
                    or request.headers.get("X-Radhouse-Browser-Launch") != self.launch_id):
                raise protocol.Rejected("stale_browser_transport")

        async def cdp(request):
            current(request)
            if len(self.pipes) >= 32:
                raise protocol.Rejected("browser_transport_capacity")
            remote, upstream = await asyncio.open_connection("127.0.0.1", urlsplit(self.endpoint).port)
            ws = web.WebSocketResponse(max_msg_size=protocol.MAX_FRAME)
            await ws.prepare(request)
            self.pipes.add(ws)

            async def upload():
                async for message in ws:
                    if message.type != WSMsgType.BINARY:
                        break
                    upstream.write(message.data)
                    await upstream.drain()

            async def download():
                while data := await remote.read(65536):
                    await ws.send_bytes(data)

            tasks = [asyncio.create_task(upload()), asyncio.create_task(download())]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                upstream.close()
                await upstream.wait_closed()
                await ws.close()
                self.pipes.discard(ws)
            return ws

        async def viewer(request):
            current(request)
            tail = request.match_info["tail"]
            if (not self.grants.live() or ".." in tail or tail.startswith("/")
                    or "/api/" in "/" + tail and tail not in {"api/status", "api/health", "api/websockets"}):
                raise protocol.Rejected("stream_request_rejected")
            url = "http://localhost/chat/browser/stream/" + tail
            async with ClientSession(connector=UnixConnector(path=str(self.directory / "stream.sock")),
                    timeout=ClientTimeout(total=None, connect=5), trust_env=False) as client:
                if request.headers.get("Upgrade", "").lower() == "websocket":
                    if tail != "api/websockets":
                        raise protocol.Rejected("stream_request_rejected")
                    protocols = tuple(p.strip() for p in request.headers.get("Sec-WebSocket-Protocol", "").split(","))
                    async with client.ws_connect(url, protocols=protocols, max_msg_size=protocol.MAX_FRAME) as upstream:
                        ws = web.WebSocketResponse(protocols=("selkies",), max_msg_size=128 * 1024)
                        await ws.prepare(request)
                        self.pipes.add(ws)

                        async def copy(source, destination):
                            async for message in source:
                                if message.type == WSMsgType.TEXT:
                                    await destination.send_str(message.data)
                                elif message.type == WSMsgType.BINARY:
                                    await destination.send_bytes(message.data)
                                else:
                                    break
                        tasks = [asyncio.create_task(copy(ws, upstream)), asyncio.create_task(copy(upstream, ws))]
                        try:
                            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                        finally:
                            for task in tasks:
                                task.cancel()
                            await asyncio.gather(*tasks, return_exceptions=True)
                            await ws.close()
                            self.pipes.discard(ws)
                        return ws
                capability = request.headers.get("X-Radhouse-Stream-Token", "")
                async with client.get(url, headers={"Authorization": "Bearer " + capability},
                        allow_redirects=False, timeout=ClientTimeout(total=15)) as response:
                    chunks, size = [], 0
                    async for chunk in response.content.iter_chunked(65536):
                        size += len(chunk)
                        if size > 16 * 1024 * 1024:
                            raise protocol.Rejected("stream_asset_too_large")
                        chunks.append(chunk)
                    return web.Response(body=b"".join(chunks), status=response.status,
                        headers={"Content-Type": response.headers.get("Content-Type", "application/octet-stream"),
                                 "Cache-Control": "no-store"})

        app = web.Application(middlewares=[authenticated], client_max_size=protocol.MAX_BODY)
        app.router.add_post("/v1/request", rpc)
        app.router.add_get("/v1/cdp", cdp)
        app.router.add_get("/chat/browser/stream/{tail:.*}", viewer)
        return app


async def run(args):
    from aiohttp import web
    os.umask(0o077)
    guest = Guest(args.state, args.proxy, Path(args.credential_file).read_text().strip())
    runner = web.AppRunner(guest.application(), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, args.bind, args.port).start()
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stopped.set)
    try:
        await stopped.wait()
    finally:
        try:
            await guest.stop()
        finally:
            await runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--proxy", required=True)
    parser.add_argument("--credential-file", required=True)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
