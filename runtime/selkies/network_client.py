"""Owned Chrome handle and loopback CDP relay to the isolated browser worker."""
import base64
import importlib.util
import os
from pathlib import Path
import re
import select
import socket
import socketserver
import stat
import subprocess
import sys
import threading
import time
from uuid import uuid4

name = 'radhouse_browser_worker_protocol'
if name not in sys.modules:
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name('network_protocol.py'))
    protocol = importlib.util.module_from_spec(spec)
    sys.modules[name] = protocol
    spec.loader.exec_module(protocol)
else:
    protocol = sys.modules[name]


class Tunnel:
    """One fixed Unix destination; never a general HTTP or destination proxy."""
    def __init__(self, path):
        self.path = path
        self.connections = set()
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(16)
        outer = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                remote = None
                try:
                    remote = protocol.connect(outer.path, timeout=5)
                    with outer.lock:
                        outer.connections.update((self.request, remote))
                    for peer in (self.request, remote):
                        peer.settimeout(5)
                    directions = {self.request: remote, remote: self.request}
                    while directions:
                        readable, _, _ = select.select(tuple(directions), (), (), 120)
                        if not readable:
                            return
                        for source in readable:
                            target = directions[source]
                            data = source.recv(65536)
                            if data:
                                target.sendall(data)
                            else:
                                del directions[source]
                                try:
                                    target.shutdown(socket.SHUT_WR)
                                except OSError:
                                    pass
                except (OSError, ValueError):
                    return
                finally:
                    with outer.lock:
                        outer.connections.discard(self.request)
                        if remote is not None:
                            outer.connections.discard(remote)
                    if remote is not None:
                        remote.close()

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            block_on_close = False

            def verify_request(self, request, address):
                return address[0] == '127.0.0.1' and outer.slots.acquire(blocking=False)

            def process_request(self, request, address):
                try:
                    super().process_request(request, address)
                except BaseException:
                    outer.slots.release()
                    raise

            def process_request_thread(self, request, address):
                try:
                    super().process_request_thread(request, address)
                finally:
                    outer.slots.release()

        self.server = Server(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        with self.lock:
            for peer in tuple(self.connections):
                try:
                    peer.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                peer.close()
        self.thread.join(timeout=2)


class RemoteChrome:
    """Unknown acknowledgements remain live/owned until positive retirement."""
    def __init__(self, socket_path):
        self.socket = socket_path
        self.launch_id = uuid4().hex
        self.pid = None
        self.tunnel = None
        self.endpoint = None
        self.proof = None
        self.retired = False
        self.retirement_lock = threading.Lock()
        self.pressure = False
        self.monitor_stop = threading.Event()

    def _request(self, operation, timeout=20, **fields):
        return protocol.request(self.socket, {'op': operation, 'launch_id': self.launch_id, **fields}, timeout=timeout)

    def start(self, environment):
        display = environment.get('DISPLAY')
        path = Path(environment.get('XAUTHORITY', ''))
        if type(display) is not str or not re.fullmatch(r':[0-9]{1,5}', display):
            raise protocol.Rejected('browser_display_unverified')
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, 'rb') as source:
                info = os.fstat(source.fileno())
                raw = source.read(4097)
        except OSError:
            raise protocol.Rejected('browser_display_unverified') from None
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or not 1 <= len(raw) <= 4096):
            raise protocol.Rejected('browser_display_unverified')
        try:
            value = self._request('start', display=display, xauthority=base64.b64encode(raw).decode())
        except protocol.Unavailable:
            raise protocol.Rejected('browser_worker_unavailable') from None
        if value.get('state') == 'rejected':
            raise protocol.Rejected('browser_worker_launch_rejected')
        if value.get('state') != 'running' or value.get('launch_id') != self.launch_id:
            raise protocol.Uncertain('browser_worker_launch_unconfirmed')
        pid, cdp, proof = value.get('pid'), value.get('browser_path'), value.get('sandbox')
        expected = '/run/radhouse-browser-worker/cdp-' + self.launch_id + '.sock'
        if (type(pid) is not int or pid <= 1 or value.get('cdp_socket') != expected
                or type(cdp) is not str or re.fullmatch(r'/devtools/browser/[A-Fa-f0-9-]{36}', cdp) is None
                or type(proof) is not dict or proof.get('enabled') is not True
                or value.get('isolated_public_network') is not True):
            raise protocol.Uncertain('browser_worker_launch_unconfirmed')
        self.pid, self.proof = pid, proof
        self.tunnel = Tunnel(expected)
        port = self.tunnel.server.server_address[1]
        self.endpoint = 'ws://127.0.0.1:' + str(port) + cdp
        self.monitor = threading.Thread(target=self._monitor, daemon=True)
        self.monitor.start()
        return self

    def _mark_retired(self):
        with self.retirement_lock:
            self.monitor_stop.set()
            if self.tunnel:
                self.tunnel.close()
                self.tunnel = None
            self.retired = True

    def _monitor(self):
        while not self.monitor_stop.wait(.5):
            try:
                value = self._request('status', timeout=2)
            except (protocol.Unavailable, protocol.Uncertain):
                continue  # Unknown is still owned; never infer a dead child.
            if value.get('launch_id') != self.launch_id:
                continue
            if value.get('state') == 'retired':
                self._mark_retired()
                return
            self.pressure = value.get('state') == 'running' and value.get('pressure') is True

    def poll(self):
        # Called by the native asyncio watcher: it must never block on IPC.
        return 0 if self.retired else None

    def memory_pressure(self):
        return self.pressure

    def sandbox_proof(self):
        if self.poll() is not None or not self.proof:
            raise ValueError('worker_browser_unverified')
        return self.proof

    def terminate(self):
        value = self._request('stop')
        if value.get('state') != 'retired' or value.get('launch_id') != self.launch_id:
            raise protocol.Uncertain('browser_worker_retirement_unconfirmed')
        self._mark_retired()

    def wait(self, timeout=None):
        deadline = time.monotonic() + (timeout if timeout is not None else 30)
        while self.poll() is None:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired('isolated-browser', timeout)
            time.sleep(.05)
        return 0
