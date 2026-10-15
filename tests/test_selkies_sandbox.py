import asyncio
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('review_sandbox', Path(__file__).parents[1]/'runtime/selkies/sandbox.py')
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


class RpcTests(unittest.IsolatedAsyncioTestCase):
    async def test_unrelated_events_do_not_replace_matching_result(self):
        class Socket:
            replies = iter([{'method':'Page.frameAttached'}, {'id':1,'result':{'accepted':True}}])
            async def send_json(self, value):
                self.sent = value
            async def receive_json(self):
                return next(self.replies)
        ws = Socket()
        self.assertEqual(await s._rpc(ws, 'Page.getFrameTree'), {'accepted':True})
        self.assertEqual(ws.sent, {'id':1,'method':'Page.getFrameTree','params':{}})

    async def test_protocol_error_does_not_echo_private_error_contents(self):
        class Socket:
            async def send_json(self, value):
                pass
            async def receive_json(self):
                return {'id':1,'error':{'message':'synthetic private protocol detail'}}
        with self.assertRaisesRegex(RuntimeError, '^page_check_unconfirmed$'):
            await s._rpc(Socket(), 'Page.getFrameTree')

    async def test_dead_renderer_cannot_leave_receive_waiting_forever(self):
        class Socket:
            async def send_json(self, value):
                pass
            async def receive_json(self):
                await asyncio.Future()
        async def bounded():
            with self.assertRaises(TimeoutError):
                await s._rpc(Socket(), 'Page.getFrameTree', timeout=.01)
        # An outer timeout must fail the test, not satisfy the expected error.
        await asyncio.wait_for(bounded(), .2)

    async def test_event_stream_does_not_restart_the_total_rpc_deadline(self):
        class Socket:
            async def send_json(self, value):
                pass
            async def receive_json(self):
                await asyncio.sleep(0)
                return {'method':'Page.frameAttached'}
        async def bounded():
            with self.assertRaises(TimeoutError):
                await s._rpc(Socket(), 'Page.getFrameTree', timeout=.01)
        # An outer timeout must fail the test, not satisfy the expected error.
        await asyncio.wait_for(bounded(), .2)


class MemoryMaintenanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_pressure_collects_each_page_without_reading_page_or_heap_contents(self):
        from unittest.mock import AsyncMock, patch
        from types import SimpleNamespace
        calls = []
        class Socket:
            def __init__(self, url):
                self.url = url
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
        class Client(Socket):
            def ws_connect(self, url):
                return Socket(url)
        async def rpc(ws, method, params=None):
            calls.append((ws.url, method, params))
            return {}
        endpoint = 'http://127.0.0.1:9123'
        pages = [{'id':'A'*32}, {'id':'B'*32}]
        with patch.dict('sys.modules', {'aiohttp':SimpleNamespace(ClientSession=lambda **k:Client('unused'), ClientTimeout=lambda **k:None)}), \
                patch.object(s, '_browser_url', AsyncMock(return_value='browser')), \
                patch.object(s, '_targets', AsyncMock(return_value=(pages, set()))), \
                patch.object(s, '_rpc', side_effect=rpc):
            await s.notify_memory_pressure(endpoint)
        self.assertEqual(calls, [
            ('browser', 'Memory.simulatePressureNotification', {'level':'critical'}),
            (s._target_url(endpoint, 'A'*32), 'HeapProfiler.collectGarbage', None),
            (s._target_url(endpoint, 'B'*32), 'HeapProfiler.collectGarbage', None)])

    async def test_untrusted_target_id_cannot_redirect_maintenance_socket(self):
        from unittest.mock import AsyncMock, patch
        from types import SimpleNamespace
        class Client:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def ws_connect(self, url):
                return self
        with patch.dict('sys.modules', {'aiohttp':SimpleNamespace(ClientSession=lambda **k:Client(), ClientTimeout=lambda **k:None)}), \
                patch.object(s, '_browser_url', AsyncMock(return_value='browser')), \
                patch.object(s, '_targets', AsyncMock(return_value=([{'id':'../other'}], set()))), \
                patch.object(s, '_rpc', AsyncMock()):
            with self.assertRaisesRegex(RuntimeError, '^page_check_unconfirmed$'):
                await s.notify_memory_pressure('http://127.0.0.1:9123')
