"""Native file effects and visibility use the real durable ownership controller."""
import asyncio
from contextlib import contextmanager
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_selkies_control import fixture, take
from tests.test_browser_files import guest

spec = importlib.util.spec_from_file_location("native_browser_files_test", Path(__file__).parents[1] / "runtime/hermes/browser_files.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def test_human_transfer_requires_live_generation_lease_and_post_effect_authority(tmp_path, monkeypatch):
    async def scenario():
        f = fixture(tmp_path); state = await take(f); calls = []
        bridge = SimpleNamespace(_controller=f.c)
        monkeypatch.setattr(native, "file_module", lambda _: guest)
        async def call(operation, **value):
            calls.append((operation, value))
            return {"chooser": None, "downloads": [{"name": "excluded"}]}
        runtime = SimpleNamespace(boundary=f.boundary, remote=SimpleNamespace(call=call))
        owned = SimpleNamespace(identity=f.identity)
        body = {"generation": f.identity.generation, "revision": state.revision,
            "lease_id": state.lease.lease_id, "file": {"action": "list"}}
        assert await native.human(bridge, runtime, owned, f.desktop.owner, 2000, body) == {"chooser": None}
        for changed in ({"generation": "stale"}, {"lease_id": "stale"}, {"revision": 1}, {"file": {"action": "read", "id": "a" * 32, "offset": 0}}):
            with pytest.raises(ValueError):
                await native.human(bridge, runtime, owned, f.desktop.owner, 2000, {**body, **changed})
        assert len(calls) == 1
        with pytest.raises(ValueError):
            await native.human(bridge, runtime, owned, f.phone.owner, 2000, body)
        async def revoke(operation, **value):
            f.c.pause(f.identity, f.desktop.owner)
            return {"applied": True}
        runtime.remote.call = revoke
        with pytest.raises(ValueError):
            await native.human(bridge, runtime, owned, f.desktop.owner, 2000,
                {**body, "file": {"action": "commit", "id": "a" * 32}})
    asyncio.run(scenario())


def test_collector_keeps_private_provenance_outside_guest_and_checks_owner(tmp_path, monkeypatch):
    async def scenario():
        f = fixture(tmp_path)
        owned = SimpleNamespace(identity=f.identity)
        item = {"id": "b" * 32, "private": False, "producer": "assistant", "state": "completed"}
        class Remote:
            def __init__(self, *_): pass
            async def call(self, operation, **value): return {"chooser": {"destination": "private"}, "downloads": [dict(item)]}
        platform = SimpleNamespace(__file__=__file__, configuration={"network": {}}, load=lambda *_: SimpleNamespace(Client=Remote))
        bridge = SimpleNamespace(_controller=f.c, _streaming=platform, _root_file=None, _owned_browsers={"session": owned})
        monkeypatch.setattr(native, "file_module", lambda _: guest)
        native.remember(bridge, owned, SimpleNamespace(launch_id="a" * 32))
        body = {"collector": "owner", "launch_id": "a" * 32, "file": {"action": "list"}}
        before = await native.collect(bridge, "session", body)
        assert "chooser" not in before
        assert before["downloads"][0]["private"] == 0 and before["downloads"][0]["run_id"] == "old-run"
        state = await take(f)
        private = await native.collect(bridge, "session", body)
        assert private["downloads"][0]["private"] == 1
        await f.boundary.handback(f.desktop, lease_id=state.lease.lease_id, revision=state.revision)
        assert (await native.collect(bridge, "session", body))["downloads"][0]["private"] == 1
        with pytest.raises(ValueError, match="owner_mismatch"):
            await native.collect(bridge, "session", {**body, "collector": "other"})
        with pytest.raises(ValueError):
            await native.collect(bridge, "session", {**body, "file": {"action": "commit", "id": "b" * 32}})
        assert len((await native.collect(bridge, "session", {**body, "launch_id": None}))["launches"]) == 1
    asyncio.run(scenario())


def test_uncertain_human_commit_pauses_control_without_replaying(tmp_path, monkeypatch):
    async def scenario():
        f = fixture(tmp_path); state = await take(f); calls = []
        monkeypatch.setattr(native, "file_module", lambda _: guest)
        async def uncertain(operation, **value):
            calls.append(value["action"])
            raise TimeoutError("response lost after website effect")
        runtime = SimpleNamespace(boundary=f.boundary, remote=SimpleNamespace(call=uncertain))
        with pytest.raises(TimeoutError):
            await native.human(SimpleNamespace(_controller=f.c), runtime,
                SimpleNamespace(identity=f.identity), f.desktop.owner, 2000,
                {"generation": f.identity.generation, "revision": state.revision,
                 "lease_id": state.lease.lease_id, "file": {"action": "commit", "id": "a" * 32}})
        assert calls == ["commit"]
        assert f.c.state(f.identity).mode == "paused"
    asyncio.run(scenario())


@pytest.mark.parametrize("revoke,denied", [(False, False), (True, False), (False, True)])
def test_agent_upload_uses_granted_chunks_and_stops_on_control_loss(tmp_path, monkeypatch, revoke, denied):
    async def scenario():
        f = fixture(tmp_path)
        owned = SimpleNamespace(identity=f.identity)
        data = b"synthetic original" * 3000
        effects = []
        async def call(operation, **value):
            effects.append(value["action"])
            if value["action"] == "list":
                return {"chooser": {"id": "b" * 32, "destination": "https://example.org/upload"}}
            if revoke and value["action"] == "write":
                f.c.pause(f.identity)
            return {"applied": True}
        def content(operation, context, value):
            assert operation == "content" and value["file_id"] == "granted-file"
            if denied:
                raise ValueError("private_file")
            offset = value["offset"]
            return {"offset": offset, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "name": "example.txt", "data": base64.b64encode(data[offset:offset + 32768]).decode()}
        @contextmanager
        def operation(_context): yield owned
        runtime = SimpleNamespace(loop=asyncio.get_running_loop(), remote=SimpleNamespace(call=call), boundary=f.boundary)
        bridge = SimpleNamespace(_streaming=SimpleNamespace(runtime=runtime), _controller=f.c,
            _callback=SimpleNamespace(post=content), agent_browser_operation=operation,
            current_run_context=lambda **_: SimpleNamespace(run_id="old-run", session_id="session"))
        monkeypatch.setattr(native, "file_module", lambda _: guest)
        result = json.loads(await asyncio.to_thread(native.agent_upload, bridge,
            {"file_id": "granted-file", "destination": "https://example.org/upload"}))
        if revoke or denied:
            assert "error" in result and "commit" not in effects
        else:
            assert result == {"applied": True} and effects.count("write") == 2
    asyncio.run(scenario())
