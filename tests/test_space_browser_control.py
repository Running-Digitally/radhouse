import asyncio
import importlib.util
from pathlib import Path
import time
from uuid import uuid4

import pytest

from tests.test_selkies_control import fixture, take, stream, control
from tests.test_space_browser_guest import make, call, p

spec = importlib.util.spec_from_file_location('space_platform_test',
    Path(__file__).parents[1] / 'runtime/selkies/space_platform.py')
remote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remote)


async def connected(tmp_path):
    local = fixture(tmp_path)
    guest = make(tmp_path)
    await call(guest, 'start')
    class Client:
        async def call(self, operation, **body):
            value = p.request({'schema':p.SCHEMA, 'launch_id':guest.launch_id,
                'request_id':uuid4().hex, 'sequence':guest.sequence+1, 'op':operation, 'body':body})
            return await guest.execute(value)
    client = Client()
    async def publish(table):
        await client.call('publish', table=table, ttl=3, not_after=time.time()+3)
    async def drain():
        await client.call('drain')
    local.boundary.publish = publish
    local.boundary._drain = drain
    local.boundary.input_lock = remote.InputLock(client, local.boundary._publish)
    await local.boundary.provision()
    return local, guest, client


def test_actual_controller_handback_fences_guest_before_agent_admission(tmp_path):
    async def scenario():
        f, guest, client = await connected(tmp_path)
        state = await take(f)
        old = f.boundary.input_token
        assert guest.grants.allowed(old)
        prior = f.boundary.resume
        async def resume(*args):
            assert not guest.grants.allowed(old)
            assert f.boundary.input_token is None
            await prior(*args)
        f.boundary.resume = resume
        await f.boundary.handback(f.desktop, lease_id=state.lease.lease_id, revision=state.revision)
        assert f.boundary.state().admitted_run.run_id == 'fresh-run'
        assert not guest.grants.allowed(old) and guest.grants.freeze_id is None
    asyncio.run(scenario())


def test_sensitive_field_refusal_returns_same_human_control_after_guest_thaw(tmp_path):
    async def scenario():
        f, guest, client = await connected(tmp_path)
        state = await take(f)
        holder = f.boundary.input_token
        async def sensitive():
            assert not guest.grants.allowed(holder)
            return False
        f.boundary.sensitive_clear = sensitive
        with pytest.raises(stream.StreamRejected, match='sensitive_fields_present'):
            await f.boundary.handback(f.desktop, lease_id=state.lease.lease_id, revision=state.revision)
        assert f.boundary.state().mode == 'human'
        assert guest.grants.allowed(holder)
    asyncio.run(scenario())


def test_lost_freeze_ack_never_enters_controller_critical_section(tmp_path):
    async def scenario():
        f, guest, client = await connected(tmp_path)
        await take(f)
        holder = f.boundary.input_token
        original = client.call
        async def lost(operation, **body):
            value = await original(operation, **body)
            if operation == 'freeze':
                raise p.Uncertain('synthetic_lost_reply')
            return value
        client.call = lost
        entered = False
        with pytest.raises(p.Uncertain):
            async with f.boundary.input_lock:
                entered = True
        assert not entered and not guest.grants.allowed(holder)
        assert not f.boundary.input_lock.locked()
    asyncio.run(scenario())


def test_lost_publication_keeps_guest_frozen_and_agent_unadmitted(tmp_path):
    async def scenario():
        f, guest, client = await connected(tmp_path)
        state = await take(f)
        holder = f.boundary.input_token
        original = client.call
        async def lost(operation, **body):
            if operation == 'publish':
                raise p.Uncertain('synthetic_lost_reply')
            return await original(operation, **body)
        client.call = lost
        with pytest.raises(p.Uncertain):
            await f.boundary.handback(f.desktop, lease_id=state.lease.lease_id, revision=state.revision)
        assert not guest.grants.allowed(holder)
        assert guest.grants.freeze_id is not None
        assert 'agent-admitted' not in f.events
        with pytest.raises(control.ControlRejected):
            f.c.reserve_agent(f.identity, f.run, 'cannot-run-during-uncertain-handback')
    asyncio.run(scenario())


def test_uncertain_retirement_cleanup_requires_positive_host_receipt():
    from types import SimpleNamespace
    async def scenario():
        events = []
        class Base:
            def __init__(self, *args):
                self.renewer = None
            async def cleanup(self):
                assert self.chrome.retired
                await self.stop_transport()
                events.append('cleaned')
            async def stop_transport(self):
                if self.retirement is not None:
                    await self.retirement
                events.append('transport_stopped')
        class Chrome:
            unavailable, retired, proved = True, False, False
            def reconcile_retirement(self):
                if self.proved:
                    self.retired = True
                return self.retired
        factory = SimpleNamespace(Platform=Base, _chrome=Chrome(),
            load=lambda *a:SimpleNamespace(StreamingControl=object),
            retire=lambda:events.append('retirement_completed'),
            consume_failure=lambda task:task.exception())
        runtime = remote.create(factory, None, None)
        runtime.chrome = Chrome()
        async def lost():
            raise p.Uncertain('lost_stop_reply')
        runtime.retirement = asyncio.create_task(lost())
        await asyncio.gather(runtime.retirement, return_exceptions=True)
        with pytest.raises(p.Uncertain):
            await runtime.cleanup()
        assert not events and not runtime.chrome.retired
        runtime.chrome.proved = True
        await runtime.cleanup()
        assert events == ['retirement_completed', 'transport_stopped', 'cleaned']
        assert runtime.retirement.done() and runtime.retirement.exception() is None
    asyncio.run(scenario())


@pytest.mark.parametrize('chrome', [None, type('Retired', (), {'retired': True})()])
def test_stale_status_cannot_allocate_stream_after_native_retirement(chrome):
    from types import SimpleNamespace
    factory = SimpleNamespace(_chrome=chrome,
        load=lambda *a:pytest.fail('retired generation must not allocate a stream'))
    with pytest.raises(p.Rejected, match='browser_generation_unavailable'):
        remote.create(factory, None, None)
