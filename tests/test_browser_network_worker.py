"""Browser IPC uncertainty, peer identity and cleanup are security boundaries."""
import asyncio
import base64
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1] / 'runtime/selkies'


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


c = load('network_client_test', 'network_client.py')
w = load('network_worker_test', 'network_worker.py')
p = c.protocol
IDENTITY = 'a' * 32


class AckSocket:
    def __init__(self, replies):
        self.replies = iter(replies)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def sendall(self, raw):
        self.sent = raw
    def recv(self, size):
        return next(self.replies)


@pytest.mark.parametrize('raw', [b'', b'{}\n', b'[]\n', b'not-json\n', b'x' * (p.MAX_MESSAGE + 1),
                               b'{"schema":"radhouse.browser-worker.v1"}\nextra'])
def test_missing_or_ambiguous_ack_keeps_unknown_ownership(monkeypatch, raw):
    monkeypatch.setattr(p, 'connect', lambda *a: AckSocket([raw]))
    with pytest.raises(p.Uncertain):
        p.request('/run/unused/control.sock', {'op': 'start'})


def test_split_ack_and_presend_oversize(monkeypatch):
    raw = json.dumps({'schema': 'radhouse.browser-worker.v1', 'state': 'running'}).encode() + b'\n'
    monkeypatch.setattr(p, 'connect', lambda *a: AckSocket([raw[:8], raw[8:]]))
    assert p.request('unused', {})['state'] == 'running'
    monkeypatch.setattr(p, 'connect', lambda *a: pytest.fail('must reject before sending'))
    with pytest.raises(p.Rejected):
        p.request('unused', {'payload': 'x' * p.MAX_MESSAGE})


def test_wrong_kernel_peer_is_never_trusted(monkeypatch):
    class Peer:
        closed = False
        def settimeout(self, timeout):
            pass
        def connect(self, path):
            pass
        def close(self):
            self.closed = True
    peer = Peer()
    monkeypatch.setattr(p.socket, 'socket', lambda *a: peer)
    monkeypatch.setattr(p, 'managed_socket', lambda *a: 321)
    monkeypatch.setattr(p, 'credentials', lambda *a: (123, 322, 1002))
    with pytest.raises(p.Unavailable):
        p.connect('/run/unused/control.sock')
    assert peer.closed


def test_lost_stop_ack_cannot_retire_handle(monkeypatch):
    handle = c.RemoteChrome('unused')
    monkeypatch.setattr(handle, '_request', lambda *a, **k: (_ for _ in ()).throw(p.Uncertain()))
    with pytest.raises(p.Uncertain):
        handle.terminate()
    assert handle.poll() is None
    with pytest.raises(subprocess.TimeoutExpired):
        handle.wait(timeout=0)
    monkeypatch.setattr(handle, '_request', lambda *a, **k: {'state': 'retired', 'launch_id': handle.launch_id})
    handle.terminate()
    assert handle.poll() == 0


def test_native_poll_never_performs_ipc(monkeypatch):
    handle = c.RemoteChrome('unused')
    monkeypatch.setattr(handle, '_request', lambda *a, **k: pytest.fail('poll must be nonblocking'))
    assert handle.poll() is None


def test_cdp_tunnel_preserves_half_closed_request(monkeypatch):
    import threading
    left, right = socket.socketpair()
    monkeypatch.setattr(p, 'connect', lambda *a, **k: left)
    def backend():
        data = bytearray()
        with right:
            while chunk := right.recv(1024):
                data.extend(chunk)
            right.sendall(bytes(data) + b'-reply')
    thread = threading.Thread(target=backend)
    thread.start()
    tunnel = c.Tunnel('fixed-cdp-only')
    try:
        with socket.create_connection(tunnel.server.server_address, timeout=2) as client:
            client.sendall(b'complete')
            client.shutdown(socket.SHUT_WR)
            assert client.recv(1024) == b'complete-reply'
    finally:
        tunnel.close()
        thread.join(timeout=2)
    assert not thread.is_alive()


def test_unknown_or_stale_stop_cannot_kill_current_browser(monkeypatch):
    async def scenario():
        worker = w.Worker('/native', 1002)
        worker.launch_id = IDENTITY
        worker.chrome = SimpleNamespace(terminate=lambda: pytest.fail('wrong generation'))
        assert await worker.dispatch({'op': 'stop', 'launch_id': 'b' * 32}) == {'state': 'unknown', 'launch_id': 'b' * 32}
        worker.retired.add('c' * 32)
        assert (await worker.dispatch({'op': 'stop', 'launch_id': 'c' * 32}))['state'] == 'retired'
        assert worker.launch_id == IDENTITY
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', [RuntimeError('ready failed'), asyncio.CancelledError()])
def test_failed_start_owns_spawn_before_wait_and_propagates_cancellation(monkeypatch, tmp_path, failure):
    async def scenario():
        worker = w.Worker('/native', 1002)
        child = SimpleNamespace(pid=123)
        observed = []
        def ready(actual, profile):
            assert actual is child and worker.chrome is child and worker.launch_id == IDENTITY
            raise failure
        async def stop(identity):
            observed.append(identity)
            worker.chrome = worker.launch_id = None
        monkeypatch.setattr(w, 'RUN', tmp_path)
        monkeypatch.setattr(w, 'selected_chrome', lambda: 'synthetic-chrome')
        monkeypatch.setattr(w.subprocess, 'Popen', lambda *a, **k: child)
        monkeypatch.setattr(w.sandbox, 'wait_ready', ready)
        monkeypatch.setattr(worker, 'stop', stop)
        body = {'op': 'start', 'launch_id': IDENTITY, 'display': ':123', 'xauthority': base64.b64encode(b'fixture').decode()}
        if isinstance(failure, asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await worker.dispatch(body)
        else:
            assert await worker.dispatch(body) == {'state': 'rejected'}
        assert observed == [IDENTITY]
    asyncio.run(scenario())


def test_failed_cleanup_retains_and_blocks_second_launch(monkeypatch, tmp_path):
    async def scenario():
        worker = w.Worker('/native', 1002)
        child = SimpleNamespace(pid=123, poll=lambda: None)
        def fail(*args):
            raise ValueError('unconfirmed')
        async def stop(identity):
            raise ValueError('not reaped')
        monkeypatch.setattr(w, 'RUN', tmp_path)
        monkeypatch.setattr(w, 'selected_chrome', lambda: 'synthetic-chrome')
        monkeypatch.setattr(w.subprocess, 'Popen', lambda *a, **k: child)
        monkeypatch.setattr(w.sandbox, 'wait_ready', fail)
        monkeypatch.setattr(worker, 'stop', stop)
        body = {'op': 'start', 'launch_id': IDENTITY, 'display': ':123', 'xauthority': base64.b64encode(b'fixture').decode()}
        assert (await worker.dispatch(body))['state'] == 'retained'
        body['launch_id'] = 'b' * 32
        assert (await worker.dispatch(body))['state'] == 'rejected'
        assert worker.chrome is child and worker.launch_id == IDENTITY
    asyncio.run(scenario())


def test_client_must_match_uid_and_exact_cgroup(monkeypatch):
    worker = w.Worker('/radhouse.slice/native.service', 1002)
    writer = SimpleNamespace(get_extra_info=lambda key: object())
    monkeypatch.setattr(w.protocol, 'credentials', lambda *a: (123, 1003, 1002))
    assert not worker.authorized(writer)
    monkeypatch.setattr(w.protocol, 'credentials', lambda *a: (123, 1002, 1002))
    monkeypatch.setattr(w.Path, 'read_text', lambda *a: '0::/radhouse.slice/other.service\n')
    assert not worker.authorized(writer)
    monkeypatch.setattr(w.Path, 'read_text', lambda *a: '0::/radhouse.slice/native.service\n')
    assert worker.authorized(writer)


def test_public_browser_flags_remove_loopback_bypass():
    args = w.sandbox.chrome_arguments(Path('/synthetic-profile'), 'http://127.0.0.1:18082', public_only=True)
    assert '--proxy-bypass-list=<-loopback>' in args
    assert '--disable-quic' in args
    assert not any('18081' in arg for arg in args)
    with pytest.raises(ValueError):
        w.sandbox.chrome_arguments(Path('/synthetic-profile'), public_only=True)


def test_worker_websocket_discovery_uses_outer_control_tunnel():
    endpoint = 'ws://127.0.0.1:43210/devtools/browser/' + 'a' * 36
    assert w.sandbox._http_endpoint(endpoint) == 'http://127.0.0.1:43210'
    assert w.sandbox._target_url(endpoint, 'B' * 32) == 'ws://127.0.0.1:43210/devtools/page/' + 'B' * 32


@pytest.mark.parametrize('uid,interfaces,privileges,caps', [
    (1002, [(1,'lo')], '1', '0'), (0, [(1,'lo')], '1', '0'),
    (60000, [(1,'lo'),(2,'eth0')], '1', '0'),
    (60000, [(1,'lo')], '0', '0'), (60000, [(1,'lo')], '1', '1')])
def test_worker_refuses_unisolated_or_privileged_service(uid,interfaces,privileges,caps,monkeypatch):
    monkeypatch.setattr(w.os,'getuid',lambda:uid)
    monkeypatch.setattr(w.socket,'if_nameindex',lambda:interfaces)
    monkeypatch.setattr(w.Path,'read_text',lambda *a:'NoNewPrivs: '+privileges+'\nCapEff: '+caps+'\n')
    with pytest.raises(ValueError,match='browser_network_namespace_unverified'):
        w.isolated_process(1002)


def test_known_child_exit_requires_cleanup_before_retirement(monkeypatch):
    async def scenario():
        worker=w.Worker('/native',1002)
        worker.launch_id=IDENTITY
        worker.chrome=SimpleNamespace(poll=lambda:0)
        calls=[]
        async def stop(identity):
            calls.append(identity)
            raise ValueError('descendant_not_reaped')
        monkeypatch.setattr(worker,'stop',stop)
        with pytest.raises(ValueError,match='descendant_not_reaped'):
            await worker.dispatch({'op':'status','launch_id':IDENTITY})
        assert worker.launch_id==IDENTITY and calls==[IDENTITY]
        calls.clear()
        assert (await worker.dispatch({'op':'status','launch_id':'b'*32}))['state']=='unknown'
        assert calls==[]
    asyncio.run(scenario())
