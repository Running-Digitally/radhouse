"""Fixed authenticated browser transport. Never holds SPACE management credentials."""
import asyncio
import json
from pathlib import Path
import re
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

import radhouse_space_protocol as protocol


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise protocol.Uncertain("browser_redirect_refused")


class Client:
    def __init__(self, configuration, read_file):
        if (type(configuration) is not dict or set(configuration) != {
                "kind", "origin", "ca_path", "credential_path"}
                or configuration["kind"] != "space-browser-v1"):
            raise protocol.Rejected("browser_configuration_unverified")
        try:
            origin = configuration["origin"]
            parsed = urlsplit(origin)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"}
                    or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or parsed.port is not None and not 1 <= parsed.port <= 65535
                    or any(c.isspace() or ord(c) < 32 or c == "\\" for c in origin)):
                raise ValueError
            ca = read_file(Path(configuration["ca_path"]), 65536)
            credential_path = Path(configuration["credential_path"])
            if credential_path.lstat().st_mode & 0o007:
                raise ValueError
            credential = read_file(credential_path, 256).decode().strip()
            protocol.token(credential)
            self.ssl = ssl.create_default_context(cadata=ca.decode("ascii"))
        except (ValueError, TypeError, OSError, UnicodeError):
            raise protocol.Rejected("browser_configuration_unverified") from None
        self.origin = origin.rstrip("/")
        self.headers = {"X-Radhouse-Browser-Service": credential}
        self.opener = build_opener(ProxyHandler({}), HTTPSHandler(context=self.ssl), NoRedirect())
        self.lock = threading.Lock()
        self.async_lock = asyncio.Lock()
        self.sequence = 0
        self.launch_id = uuid4().hex

    def request(self, operation, *, timeout=15, **body):
        # One ordered controller connection, including renewals. No implicit replay.
        with self.lock:
            self.sequence += 1
            envelope = protocol.request({"schema": protocol.SCHEMA, "launch_id": self.launch_id,
                "request_id": uuid4().hex, "sequence": self.sequence, "op": operation, "body": body})
            raw = json.dumps(envelope, separators=(",", ":")).encode()
            if len(raw) > protocol.MAX_BODY:
                raise protocol.Rejected("browser_request_too_large")
            request = Request(self.origin + "/v1/request", data=raw, method="POST",
                headers={**self.headers, "Content-Type": "application/json"})
            try:
                with self.opener.open(request, timeout=timeout) as response:
                    if response.status != 200:
                        raise protocol.Uncertain("browser_response_unconfirmed")
                    data = response.read(protocol.MAX_BODY + 1)
                if len(data) > protocol.MAX_BODY:
                    raise protocol.Uncertain("browser_response_unconfirmed")
                value = json.loads(data)
                if (type(value) is not dict or set(value) != {"schema", "launch_id", "request_id", "sequence", "data"}
                        or any(value[k] != envelope[k] for k in ("schema", "launch_id", "request_id", "sequence"))
                        or type(value["data"]) is not dict):
                    raise protocol.Uncertain("browser_response_unconfirmed")
                return value["data"]
            except HTTPError as error:
                if error.code in {400, 401, 403}:
                    raise protocol.Rejected("browser_request_rejected") from None
                raise protocol.Uncertain("browser_response_unconfirmed") from None
            except (OSError, URLError, ValueError, TimeoutError):
                raise protocol.Uncertain("browser_response_unconfirmed") from None

    async def call(self, operation, **body):
        async with self.async_lock:
            return await asyncio.to_thread(self.request, operation, **body)

    def transport_headers(self):
        return {**self.headers, "X-Radhouse-Browser-Launch": self.launch_id}


class Tunnel:
    """Loopback native-driver connection to one guest CDP endpoint over TLS.

    Neither HTTP payloads nor caller-selected destinations are interpreted here.
    The guest binds each tunnel to its current launch and its fixed Chrome socket.
    """
    def __init__(self, client):
        self.client = client
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.error = None
        self.tasks = set()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        if not self.ready.wait(10) or self.error is not None:
            raise protocol.Uncertain("browser_tunnel_unavailable")

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.server = self.loop.run_until_complete(asyncio.start_server(self._connection, "127.0.0.1", 0))
            self.port = self.server.sockets[0].getsockname()[1]
        except BaseException as error:
            self.error = type(error).__name__
        finally:
            self.ready.set()
        if self.error is None:
            self.loop.run_forever()
        self.loop.close()

    async def _connection(self, reader, writer):
        from aiohttp import ClientSession, ClientTimeout, WSMsgType
        task = asyncio.current_task()
        if len(self.tasks) >= 16:
            writer.close()
            await writer.wait_closed()
            return
        self.tasks.add(task)
        children = []
        try:
            async with ClientSession(trust_env=False, timeout=ClientTimeout(total=None, connect=5)) as client:
                async with client.ws_connect(self.client.origin + "/v1/cdp", ssl=self.client.ssl,
                        headers=self.client.transport_headers(), max_msg_size=protocol.MAX_FRAME) as remote:
                    async def upload():
                        while data := await reader.read(65536):
                            await remote.send_bytes(data)
                    async def download():
                        async for message in remote:
                            if message.type != WSMsgType.BINARY:
                                break
                            writer.write(message.data)
                            await writer.drain()
                    children = [asyncio.create_task(upload()), asyncio.create_task(download())]
                    await asyncio.wait(children, return_when=asyncio.FIRST_COMPLETED)
        except Exception:
            # Page data and tokens must not enter transport diagnostics.
            pass
        finally:
            for child in children:
                child.cancel()
            await asyncio.gather(*children, return_exceptions=True)
            writer.close()
            try:
                await writer.wait_closed()
            finally:
                self.tasks.discard(task)

    async def _close(self):
        self.server.close()
        await self.server.wait_closed()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def close(self):
        if not self.loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(self._close(), self.loop).result(8)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(8)
        if self.thread.is_alive():
            raise protocol.Uncertain("browser_tunnel_retirement_unconfirmed")


class RemoteChrome:
    """Process-shaped handle; a network failure is never evidence of retirement."""
    def __init__(self, client):
        self.client = client
        self.tunnel = None
        self.endpoint = None
        self.proof = None
        self.retired = False
        self.unavailable = False

    def start(self, environment):
        value = self.client.request("start", timeout=45)
        path = value.get("browser_path")
        if (value.get("state") != "running" or type(path) is not str
                or re.fullmatch(r"/devtools/browser/[A-Fa-f0-9-]{36}", path) is None
                or type(value.get("sandbox")) is not dict or value["sandbox"].get("enabled") is not True
                or value.get("public_egress") is not True):
            raise protocol.Uncertain("browser_launch_unconfirmed")
        self.proof = value["sandbox"]
        self.tunnel = Tunnel(self.client)
        self.endpoint = f"ws://127.0.0.1:{self.tunnel.port}{path}"
        return self

    def poll(self):
        return 0 if self.retired else None

    def memory_pressure(self):
        return False  # Guest-local maintenance owns the actual browser budget.

    def sandbox_proof(self):
        if self.retired or self.proof is None:
            raise protocol.Uncertain("browser_sandbox_unconfirmed")
        return self.proof

    def terminate(self):
        value = self.client.request("stop", timeout=30)
        if value.get("state") != "retired":
            raise protocol.Uncertain("browser_retirement_unconfirmed")
        self.confirm_retired()

    def reconcile_retirement(self):
        """Read a positive receipt after an uncertain stop; never repeat its effect."""
        value = self.client.request("status", timeout=10)
        if value.get("state") != "retired":
            return False
        self.confirm_retired()
        return True

    def confirm_retired(self):
        if self.tunnel:
            self.tunnel.close()
        self.retired = True

    def wait(self, timeout=None):
        end = time.monotonic() + (timeout or 30)
        while not self.retired:
            if time.monotonic() >= end:
                import subprocess
                raise subprocess.TimeoutExpired("space-browser", timeout)
            time.sleep(.05)
        return 0
