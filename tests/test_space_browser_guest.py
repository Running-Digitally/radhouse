"""Exercise authority and recovery without installing a browser on the test host."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("space_guest_test", ROOT / "runtime/selkies/space_guest.py")
guest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guest)
p = guest.protocol
TOKEN = "a" * 43
VIEWER = "b" * 43
IDENTITY = "a" * 32


class Process:
    def __init__(self):
        self.alive = True

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False

    def wait(self, timeout):
        assert not self.alive
        return 0


class Fixture(guest.Guest):
    async def start(self, identity):
        if self.database.execute("SELECT 1 FROM launches WHERE id=? OR state!='retired'", (identity,)).fetchone():
            raise p.Rejected("previous_browser_unresolved")
        self.launch_id = identity
        self.record(identity, "running")
        self.child = Process()
        self.events = []
        self.boundary = SimpleNamespace(_blocked=False)
        self.started_at = time.monotonic()
        self.grants = p.GrantFence()
        self.faulted = False
        return self.status()

    async def drain(self):
        # No current holder is allowed to inject while authority is changing.
        self.events.append(("drain", self.boundary._blocked, self.grants.freeze_id))

    async def update_sessions(self):
        self.events.append(("publish", self.grants.input_token))


def make(tmp_path):
    return Fixture(tmp_path / "guest", "http://192.0.2.1:3128", "s" * 43)


async def call(service, op, *, identity=IDENTITY, sequence=None, **body):
    value = p.request({"schema": p.SCHEMA, "launch_id": identity,
        "request_id": "f" * 32, "sequence": sequence or service.sequence + 1, "op": op, "body": body})
    return await service.execute(value)


async def publish(service, holder=TOKEN, ttl=3, not_after=None):
    table = {holder: {"role": "viewer", "slot": None, "mk_control": True}}
    return await call(service, "publish", table=table, ttl=ttl,
        not_after=not_after or time.time() + ttl)


def test_lost_stop_reply_reconciles_without_retiring_new_browser(tmp_path):
    async def scenario():
        service = make(tmp_path)
        await call(service, "start")
        await call(service, "stop")  # Caller loses this response.
        newer = "b" * 32
        await call(service, "start", identity=newer)
        assert (await call(service, "status"))["state"] == "retired"
        assert (await call(service, "stop"))["state"] == "retired"
        assert service.launch_id == newer and service.running()
        with pytest.raises(p.Rejected):
            await publish(service)
        with pytest.raises(p.Rejected):
            await call(service, "start")
        await call(service, "stop", identity=newer)
        with pytest.raises(p.Rejected, match="previous_browser_unresolved"):
            await call(service, "start")
    asyncio.run(scenario())


def test_reordered_and_wrong_generation_commands_have_no_effect(tmp_path):
    async def scenario():
        service = make(tmp_path)
        await call(service, "start")
        await publish(service)
        events = list(service.events)
        for kwargs in ({"sequence": 1}, {"identity": "b" * 32}):
            with pytest.raises(p.Rejected, match="stale_browser_request"):
                await call(service, "freeze", **kwargs)
        assert service.grants.allowed(TOKEN) and service.events == events
    asyncio.run(scenario())


def test_delayed_publication_cannot_extend_controller_deadline(tmp_path):
    async def scenario():
        service = make(tmp_path)
        await call(service, "start")
        with pytest.raises(p.Rejected, match="invalid_grant_duration"):
            await publish(service, not_after=time.time() - .1)
        assert not service.grants.allowed(TOKEN)
        await publish(service, not_after=time.time() + .05)
        await asyncio.sleep(.07)
        assert not service.grants.allowed(TOKEN)
        with pytest.raises(p.Rejected, match="grant_expired"):
            await publish(service)
    asyncio.run(scenario())


def test_freeze_and_holder_rotation_drain_before_input_authority(tmp_path):
    async def scenario():
        service = make(tmp_path)
        await call(service, "start")
        await publish(service)
        assert service.events[:2] == [("drain", True, None), ("publish", TOKEN)]
        frozen = await call(service, "freeze")
        assert not service.grants.allowed(TOKEN)
        await publish(service, VIEWER)
        assert not service.grants.allowed(VIEWER)
        with pytest.raises(p.Rejected):
            await call(service, "thaw", freeze_id="c" * 32)
        await call(service, "thaw", freeze_id=frozen["freeze_id"])
        assert service.grants.allowed(VIEWER) and not service.grants.allowed(TOKEN)
    asyncio.run(scenario())


def test_expired_control_closes_existing_transports(tmp_path):
    async def scenario():
        service = make(tmp_path)
        await call(service, "start")
        closed = []
        class Pipe:
            async def close(self, code):
                closed.append(code)
        service.pipes.add(Pipe())
        await publish(service, ttl=.01)
        await asyncio.wait_for(service.watch(), 1)
        assert service.faulted and closed == [1008]
        assert not service.grants.allowed(TOKEN)
    asyncio.run(scenario())


def test_failed_stream_shutdown_still_terminates_browser_but_keeps_reservation(tmp_path):
    async def scenario():
        service = make(tmp_path)
        await call(service, "start")
        process = service.child
        class Server:
            async def stop_server(self):
                raise RuntimeError("synthetic_failure")
        service.server = Server()
        with pytest.raises(p.Uncertain, match="retirement_unconfirmed"):
            await call(service, "stop")
        assert process.poll() == 0 and service.launch_id == IDENTITY
        assert service.database.execute("SELECT state FROM launches").fetchone() == ("running",)
        service.server = None
        assert (await call(service, "stop"))["state"] == "retired"
    asyncio.run(scenario())


def test_service_restart_does_not_assume_old_process_retired(tmp_path):
    async def scenario():
        original = make(tmp_path)
        await call(original, "start")
        restarted = make(tmp_path)
        with pytest.raises(p.Rejected, match="previous_browser_unresolved"):
            await call(restarted, "start", identity="c" * 32)
    asyncio.run(scenario())


def test_http_authentication_and_closed_operation_surface(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer
    async def scenario():
        service = make(tmp_path)
        async with TestClient(TestServer(service.application())) as client:
            envelope = {"schema": p.SCHEMA, "launch_id": IDENTITY, "request_id": "b" * 32,
                "sequence": 1, "op": "start", "body": {}}
            assert (await client.post("/v1/request", json=envelope)).status == 401
            headers = {"X-Radhouse-Browser-Service": "s" * 43}
            for operation in ("exec", "read_file", [], {"command": "id"}):
                response = await client.post("/v1/request", headers=headers, json={**envelope, "op": operation})
                assert response.status == 400
            assert not service.running()
            response = await client.post("/v1/request", headers=headers, json=envelope)
            assert response.status == 200
            data = await response.json()
            assert all(data[k] == envelope[k] for k in ("launch_id", "request_id", "sequence"))
            assert (await client.get("/v1/cdp", headers={**headers, "X-Radhouse-Browser-Launch": "c" * 32})).status == 409
            assert (await client.post("/v1/exec", headers=headers)).status != 200
    asyncio.run(scenario())


def test_initial_session_publication_precedes_input_handler_initialization():
    async def scenario():
        service = guest.Guest.__new__(guest.Guest)
        service.sessions = SimpleNamespace()
        service.grants = p.GrantFence()
        service.boundary = SimpleNamespace(handler=None)
        service.data = SimpleNamespace(config_gate=asyncio.Event())
        reconciled = []
        async def reconcile():
            reconciled.append(True)
        service.reconcile_clients = reconcile
        await service.update_sessions()
        assert service.sessions.user_tokens == {} and service.sessions.active_mk_token is None
        assert service.data.config_gate.is_set() and reconciled
    asyncio.run(scenario())
