"""One stream generation owns startup and cleanup even when requests disappear."""
import asyncio
from types import SimpleNamespace

import pytest

from tests.test_selkies_platform import platform


def lifecycle(monkeypatch, *, fail_start=False, fail_stop=False):
    events = []
    entered, release = asyncio.Event(), asyncio.Event()
    instances = []

    async def start(self):
        instances.append(self)
        events.append('start')
        entered.set()
        async def publish():
            events.append('revoke')
        async def drain():
            events.append('drain')
        async def stop_server():
            events.append('server-stop')
            if fail_stop:
                raise ValueError('synthetic_cleanup_unconfirmed')
        self.boundary = SimpleNamespace(_blocked=False, input_token='synthetic',
            handler=object(), provision=publish, _drain=drain)
        self.data = object()
        self.server = SimpleNamespace(stop_server=stop_server)
        await release.wait()
        if fail_start:
            raise ValueError('synthetic_start_failed')
        events.append('ready')

    monkeypatch.setattr(platform, 'runtime', None)
    monkeypatch.setattr(platform.Platform, 'start', start)
    return SimpleNamespace(events=events, entered=entered, release=release,
        instances=instances, bridge=object(), owned=object())


def test_concurrent_requests_share_startup_and_never_receive_partial_stream(monkeypatch):
    async def scenario():
        f = lifecycle(monkeypatch)
        first = asyncio.create_task(platform.ensure(f.bridge, f.owned))
        await f.entered.wait()
        second = asyncio.create_task(platform.ensure(f.bridge, f.owned))
        await asyncio.sleep(0)
        pending = not second.done()
        f.release.set()
        results = await asyncio.gather(first, second)
        await results[0].stop()
        assert pending
        assert results[0] is results[1]
        assert f.events.count('start') == 1
    asyncio.run(scenario())


def test_cancelled_request_does_not_cancel_or_repeat_shared_startup(monkeypatch):
    async def scenario():
        f = lifecycle(monkeypatch)
        first = asyncio.create_task(platform.ensure(f.bridge, f.owned))
        await f.entered.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        retained = platform.runtime
        f.release.set()
        current = await platform.ensure(f.bridge, f.owned)
        await current.stop()
        assert current is retained
        assert f.events.count('start') == 1
    asyncio.run(scenario())


def test_failed_start_revokes_drains_and_stops_partial_server(monkeypatch):
    async def scenario():
        f = lifecycle(monkeypatch, fail_start=True)
        first = asyncio.create_task(platform.ensure(f.bridge, f.owned))
        await f.entered.wait()
        f.release.set()
        with pytest.raises(ValueError, match='synthetic_start_failed'):
            await first
        assert f.events == ['start', 'revoke', 'drain', 'server-stop']
        assert platform.runtime is None
        assert not f.instances[0].socket.parent.exists()
    asyncio.run(scenario())


def test_failed_cleanup_retains_blocked_generation_and_denies_replacement(monkeypatch):
    async def scenario():
        f = lifecycle(monkeypatch, fail_start=True, fail_stop=True)
        first = asyncio.create_task(platform.ensure(f.bridge, f.owned))
        await f.entered.wait()
        f.release.set()
        with pytest.raises(ValueError, match='synthetic_cleanup_unconfirmed'):
            await first
        retained = platform.runtime
        assert retained is f.instances[0]
        assert retained.stopped
        assert retained.boundary._blocked
        assert retained.boundary.input_token is None
        with pytest.raises(ValueError, match='stream_browser_busy'):
            await platform.ensure(f.bridge, object())
        with pytest.raises(ValueError, match='stream_retirement_unconfirmed'):
            await platform.ensure(f.bridge, f.owned)
        async def recovered_stop():
            f.events.append('server-stop-confirmed')
        retained.server.stop_server = recovered_stop
        await retained.stop()
        assert platform.runtime is None
    asyncio.run(scenario())


def test_cancelled_stop_finishes_cleanup_before_releasing_generation(monkeypatch):
    async def scenario():
        f = lifecycle(monkeypatch)
        f.release.set()
        current = await platform.ensure(f.bridge, f.owned)
        closing, finish = asyncio.Event(), asyncio.Event()
        async def stop_server():
            closing.set()
            await finish.wait()
        current.server.stop_server = stop_server
        closing_request = asyncio.create_task(current.stop())
        await asyncio.wait_for(closing.wait(), timeout=2)
        closing_request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing_request
        assert platform.runtime is current
        assert current.boundary.input_token is None
        with pytest.raises(ValueError, match='stream_retirement_unconfirmed'):
            await platform.ensure(f.bridge, f.owned)
        finish.set()
        await current.stop()
        assert platform.runtime is None
    asyncio.run(scenario())


def test_stop_during_startup_waits_before_tearing_down_partial_server(monkeypatch):
    async def scenario():
        f = lifecycle(monkeypatch)
        first = asyncio.create_task(platform.ensure(f.bridge, f.owned))
        await f.entered.wait()
        current = platform.runtime
        stopping = asyncio.create_task(current.stop())
        await asyncio.sleep(0)
        waiting = not stopping.done()
        f.release.set()
        result = await asyncio.gather(first, stopping, return_exceptions=True)
        assert waiting
        assert isinstance(result[0], ValueError)
        assert f.events == ['start', 'ready', 'revoke', 'drain', 'server-stop']
        assert platform.runtime is None
    asyncio.run(scenario())


def test_failed_start_with_simultaneous_stop_cleans_up_once(monkeypatch):
    async def scenario():
        f = lifecycle(monkeypatch, fail_start=True)
        first = asyncio.create_task(platform.ensure(f.bridge, f.owned))
        await f.entered.wait()
        current = platform.runtime
        stopping = asyncio.create_task(current.stop())
        await asyncio.sleep(0)
        f.release.set()
        result = await asyncio.gather(first, stopping, return_exceptions=True)
        assert isinstance(result[0], ValueError)
        assert result[1] is None
        assert f.events.count('server-stop') == 1
        assert platform.runtime is None
    asyncio.run(scenario())


def test_failed_start_closes_real_unix_listener_before_releasing_ownership(monkeypatch):
    from aiohttp import web, ClientSession, UnixConnector, ClientError
    from aiohttp.test_utils import make_mocked_request
    async def scenario():
        monkeypatch.setattr(platform, 'runtime', None)
        # Keep the real Unix address below the platform's sockaddr_un limit.
        monkeypatch.setattr(platform.tempfile, 'tempdir', '/tmp')
        entered, release = asyncio.Event(), asyncio.Event()
        instances = []
        async def start(self):
            instances.append(self)
            app = web.Application()
            async def status(request):
                return web.Response(text='synthetic')
            app.router.add_get('/', status)
            runner = web.AppRunner(app, access_log=None)
            self.server = SimpleNamespace(stop_server=runner.cleanup)
            await runner.setup()
            await web.UnixSite(runner, str(self.socket)).start()
            entered.set()
            await release.wait()
            raise ValueError('synthetic_start_failed')
        monkeypatch.setattr(platform.Platform, 'start', start)
        task = asyncio.create_task(platform.ensure(object(), object()))
        await entered.wait()
        current = instances[0]
        request = make_mocked_request('GET', '/v1/browser-stream/index.html',
            match_info={'tail': 'index.html'})
        adapter = SimpleNamespace(_check_auth=lambda request: None)
        blocked = await platform.relay(object(), adapter, request)
        assert blocked.status == 409
        async with ClientSession(connector=UnixConnector(path=str(current.socket))) as client:
            async with client.get('http://localhost/') as response:
                assert response.status == 200
        release.set()
        with pytest.raises(ValueError, match='synthetic_start_failed'):
            await task
        async with ClientSession(connector=UnixConnector(path=str(current.socket))) as client:
            with pytest.raises(ClientError):
                await client.get('http://localhost/')
        assert platform.runtime is None
        assert not current.socket.parent.exists()
    asyncio.run(scenario())


def test_stop_waits_for_inflight_retirement_worker(monkeypatch):
    import threading
    async def scenario():
        f = lifecycle(monkeypatch)
        f.bridge = SimpleNamespace(_controller=SimpleNamespace(
            state=lambda identity: SimpleNamespace(lease=None)))
        f.owned = SimpleNamespace(identity='synthetic')
        f.release.set()
        current = await platform.ensure(f.bridge, f.owned)
        entered, finish = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        def retire():
            f.events.append('retire-start')
            loop.call_soon_threadsafe(entered.set)
            if not finish.wait(timeout=3):
                raise ValueError('synthetic_retirement_timeout')
            f.events.append('retire-complete')
        monkeypatch.setattr(platform, '_chrome', None)
        monkeypatch.setattr(platform, 'retire', retire)
        current.watcher = asyncio.create_task(current.watch())
        await asyncio.wait_for(entered.wait(), timeout=2)
        try:
            stopping = asyncio.create_task(current.stop())
            await asyncio.sleep(.02)
            retained = platform.runtime is current
            pending = not stopping.done()
        finally:
            finish.set()
        await stopping
        assert retained
        assert pending
        assert f.events.index('retire-complete') < f.events.index('server-stop')
    asyncio.run(scenario())


def test_unconfirmed_retirement_keeps_generation_blocked(monkeypatch):
    async def scenario():
        f = lifecycle(monkeypatch)
        f.release.set()
        current = await platform.ensure(f.bridge, f.owned)
        async def retire():
            raise ValueError('synthetic_retirement_unconfirmed')
        current.retirement = asyncio.create_task(retire())
        with pytest.raises(ValueError, match='synthetic_retirement_unconfirmed'):
            await current.stop()
        assert platform.runtime is current
        assert current.boundary._blocked
        assert current.boundary.input_token is None
        assert 'server-stop' in f.events
        with pytest.raises(ValueError, match='stream_retirement_unconfirmed'):
            await platform.ensure(f.bridge, f.owned)
        # The test's worker never owned a process; discharge its synthetic fence.
        current.retirement = None
        await current.stop()
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', ['revoke', 'drain'])
def test_failed_boundary_cleanup_still_stops_transport_and_retains_ownership(monkeypatch, failure):
    async def scenario():
        f = lifecycle(monkeypatch)
        f.release.set()
        current = await platform.ensure(f.bridge, f.owned)
        async def unconfirmed():
            raise ValueError('synthetic_boundary_unconfirmed')
        name = 'provision' if failure == 'revoke' else '_drain'
        original = getattr(current.boundary, name)
        setattr(current.boundary, name, unconfirmed)
        with pytest.raises(ValueError, match='synthetic_boundary_unconfirmed'):
            await current.stop()
        assert 'server-stop' in f.events
        assert platform.runtime is current
        assert current.boundary.input_token is None
        setattr(current.boundary, name, original)
        await current.stop()
        assert platform.runtime is None
    asyncio.run(scenario())
