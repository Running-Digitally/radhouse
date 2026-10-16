"""One isolated Chrome generation. This service has no external network route.

The native adapter retains owner/lease/tool authority. This worker accepts only
fixed lifecycle requests from that adapter and never logs request payloads.
"""
import argparse
import asyncio
import base64
from collections import deque
import contextlib
import hashlib
import importlib.util
import json
import os
import pwd
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys

HERE = Path(__file__).parent
RUN = Path('/run/radhouse-browser-worker')
PROXY = Path('/run/radhouse-browser-egress/proxy.sock')


def load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


protocol = load('radhouse_browser_worker_protocol', HERE / 'network_protocol.py')
sandbox = load('radhouse_isolated_browser_sandbox', HERE / 'sandbox.py')
resources = load('radhouse_isolated_browser_resources', HERE / 'resources.py')


def root_bytes(path, maximum):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as source:
        info = os.fstat(source.fileno())
        raw = source.read(maximum + 1)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022
            or len(raw) > maximum):
        raise ValueError('worker_source_unverified')
    return raw


def selected_chrome():
    directory = Path('/opt/radhouse-browser/current').resolve(strict=True)
    if directory.parent != Path('/opt/radhouse-browser/releases'):
        raise ValueError('worker_browser_unverified')
    value = json.loads(root_bytes(directory / 'manifest.json', 65536))
    chrome = directory / 'chrome-linux64/chrome'
    info = chrome.lstat()
    with chrome.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if (value.get('chromium_path') != str(chrome) or not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0 or info.st_mode & 0o022 or digest != value.get('chromium_sha256')):
        raise ValueError('worker_browser_unverified')
    proof = root_bytes(directory / 'qualification.json', 65536)
    if hashlib.sha256(proof).hexdigest() != value.get('sandbox_proof_sha256'):
        raise ValueError('worker_browser_unverified')
    qualified = json.loads(proof)
    if (qualified.get('state') != 'qualified'
            or any(qualified.get(key) is not True for key in ['sandbox_enabled', 'origin_guard_verified', 'view_only_input_ignored', 'chrome_control_guard_verified', 'same_session_frame_progression'])
            or qualified.get('runtime_sha256') != value.get('runtime_sha256')
            or qualified.get('chromium_sha256') != value.get('chromium_sha256')):
        raise ValueError('worker_browser_unverified')
    return str(chrome)


def isolated_process(client_uid):
    state = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    if (os.getuid() in {0, client_uid} or set(name for _, name in socket.if_nameindex()) != {'lo'}
            or state.get('NoNewPrivs', '').strip() != '1'
            or int(state.get('CapEff', '0'), 16) != 0):
        raise ValueError('browser_network_namespace_unverified')


async def relay(reader, writer):
    while data := await asyncio.wait_for(reader.read(65536), 120):
        writer.write(data)
        await asyncio.wait_for(writer.drain(), 15)
    if writer.can_write_eof():
        writer.write_eof()
        await asyncio.wait_for(writer.drain(), 15)


async def duplex(reader, writer, remote, upstream):
    tasks = [asyncio.create_task(relay(reader, upstream)), asyncio.create_task(relay(remote, writer))]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        upstream.close()
        writer.close()


class Worker:
    def __init__(self, client_cgroup, client_uid):
        self.client_cgroup = client_cgroup
        self.client_uid = client_uid
        self.lock = asyncio.Lock()
        self.chrome = None
        self.launch_id = None
        self.retired = set()
        self.retired_order = deque()
        self.cdp = None
        self.cdp_connections = set()
        self.cdp_tasks = set()
        self.profile = None
        self.reply = None
        self.clients = 0
        self.proxy_clients = 0

    def authorized(self, writer):
        pid, uid, _ = protocol.credentials(writer.get_extra_info('socket'))
        if uid != self.client_uid or pid <= 0:
            return False
        try:
            groups = Path('/proc', str(pid), 'cgroup').read_text().splitlines()
            return '0::' + self.client_cgroup in groups
        except OSError:
            return False

    async def proxy_connection(self, reader, writer):
        if self.proxy_clients >= 128:
            writer.close()
            return
        self.proxy_clients += 1
        try:
            sock = await asyncio.to_thread(protocol.connect, PROXY, 5)
            sock.setblocking(False)
            remote, upstream = await asyncio.open_unix_connection(sock=sock)
            await duplex(reader, writer, remote, upstream)
        except (OSError, protocol.Unavailable):
            writer.close()
        finally:
            self.proxy_clients -= 1

    async def cdp_connection(self, reader, writer, port):
        if not self.authorized(writer) or len(self.cdp_connections) >= 16:
            writer.close()
            return
        self.cdp_connections.add(writer)
        self.cdp_tasks.add(asyncio.current_task())
        try:
            remote, upstream = await asyncio.open_connection('127.0.0.1', port)
            await duplex(reader, writer, remote, upstream)
        except OSError:
            writer.close()
        finally:
            self.cdp_connections.discard(writer)
            self.cdp_tasks.discard(asyncio.current_task())

    async def start(self, body):
        identity = body['launch_id']
        if identity in self.retired:
            return {'state': 'rejected'}
        if self.launch_id is not None:
            if identity == self.launch_id and self.chrome and self.chrome.poll() is None and self.reply:
                return self.reply
            return {'state': 'rejected'}
        if (set(body) != {'op', 'launch_id', 'display', 'xauthority'}
                or type(body.get('display')) is not str or re.fullmatch(r':[0-9]{1,5}', body['display']) is None
                or type(body.get('xauthority')) is not str):
            return {'state': 'rejected'}
        try:
            authority = base64.b64decode(body['xauthority'], validate=True)
        except (ValueError, TypeError):
            return {'state': 'rejected'}
        if not 1 <= len(authority) <= 4096:
            return {'state': 'rejected'}
        # Reserve before the first spawn. A failed/late observer cannot replace it.
        self.launch_id = identity
        self.profile = RUN / identity
        try:
            self.profile.mkdir(mode=0o700)
            auth = self.profile / 'Xauthority'
            auth.write_bytes(authority)
            auth.chmod(0o600)
            home = self.profile / 'home'
            home.mkdir(mode=0o700)
            sandbox.CHROME = selected_chrome()
            env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HOME': str(home),
                   'DISPLAY': body['display'], 'XAUTHORITY': str(auth)}
            browser_profile = self.profile / 'chrome-profile'
            browser_profile.mkdir(mode=0o700)
            # Assign the child before awaiting readiness; even a lost/failed
            # observer must retain the real child for affirmative cleanup.
            self.chrome = subprocess.Popen(sandbox.chrome_arguments(browser_profile, 'http://127.0.0.1:18082',
                                                                     start_url='about:blank', public_only=True),
                                           env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            await asyncio.to_thread(sandbox.wait_ready, self.chrome, browser_profile)
            for _ in range(50):
                try:
                    proof = sandbox.verify(self.chrome.pid, require_namespaces=False)
                    break
                except RuntimeError as error:
                    if str(error) != 'renderer_sandbox_missing':
                        raise
                    await asyncio.sleep(.1)
            else:
                raise ValueError('worker_sandbox_unverified')
            lines = (self.profile / 'chrome-profile/DevToolsActivePort').read_text().splitlines()
            if len(lines) != 2 or re.fullmatch(r'/devtools/browser/[A-Fa-f0-9-]{36}', lines[1]) is None:
                raise ValueError('worker_browser_unverified')
            port = int(lines[0])
            # DevToolsActivePort can precede a usable control channel. Do not
            # acknowledge a browser that the native driver cannot attach to.
            from aiohttp import ClientSession, ClientTimeout
            async with ClientSession(timeout=ClientTimeout(total=8)) as client:
                endpoint = await sandbox._browser_url(client, 'http://127.0.0.1:' + str(port))
                async with client.ws_connect(endpoint) as ws:
                    version = await sandbox._rpc(ws, 'Browser.getVersion')
                    if not version.get('product'):
                        raise ValueError('worker_browser_unverified')
            cdp_path = RUN / ('cdp-' + identity + '.sock')
            self.cdp = await asyncio.start_unix_server(lambda r, w: self.cdp_connection(r, w, port), str(cdp_path))
            cdp_path.chmod(0o660)
            self.reply = {'state': 'running', 'launch_id': identity, 'pid': self.chrome.pid,
                          'browser_path': lines[1], 'cdp_socket': str(cdp_path), 'sandbox': proof,
                          'isolated_public_network': True}
            return self.reply
        except BaseException as error:
            # Cleanup is affirmative only after the owned child is reaped.
            try:
                await self.stop(identity)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                if not isinstance(error, Exception):
                    raise error
                return {'state': 'retained', 'launch_id': identity}
            if not isinstance(error, Exception):
                raise
            return {'state': 'rejected'}

    async def stop(self, identity):
        if identity in self.retired:
            return {'state': 'retired', 'launch_id': identity}
        if identity != self.launch_id:
            return {'state': 'unknown', 'launch_id': identity}
        if self.cdp:
            self.cdp.close()
            await self.cdp.wait_closed()
        if self.chrome is not None:
            if self.chrome.poll() is None:
                self.chrome.terminate()
            try:
                await asyncio.to_thread(self.chrome.wait, 8)
            except subprocess.TimeoutExpired:
                pass  # The cgroup/pidfd barrier below escalates only owned children.
        await self.reap_remaining_children()
        if self.chrome is not None:
            await asyncio.to_thread(self.chrome.wait, 2)
        for connection in tuple(self.cdp_connections):
            connection.close()
        tasks = tuple(self.cdp_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 5)
        cdp_path = RUN / ('cdp-' + identity + '.sock')
        cdp_path.unlink(missing_ok=True)
        if self.profile is not None:
            shutil.rmtree(self.profile)
        self.retired.add(identity)
        self.retired_order.append(identity)
        if len(self.retired_order) > 128:
            self.retired.discard(self.retired_order.popleft())
        self.chrome = self.launch_id = self.profile = self.reply = self.cdp = None
        return {'state': 'retired', 'launch_id': identity}

    @staticmethod
    def remaining_children():
        group = next(line[3:] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
        relative = Path(group.lstrip('/'))
        if '..' in relative.parts:
            raise ValueError('worker_cgroup_unverified')
        pids = (Path('/sys/fs/cgroup') / relative / 'cgroup.procs').read_text().split()
        if len(pids) > 256:
            raise ValueError('worker_cgroup_unverified')
        return group, {int(pid) for pid in pids if int(pid) != os.getpid()}

    async def reap_remaining_children(self):
        # This unit contains only the worker and its Chrome descendants. A
        # pidfd plus a second membership check cannot signal a reused host PID.
        for signal_number in (signal.SIGTERM, signal.SIGKILL):
            group, pids = self.remaining_children()
            for pid in pids:
                descriptor = None
                try:
                    descriptor = os.pidfd_open(pid)
                    groups = Path('/proc', str(pid), 'cgroup').read_text().splitlines()
                    if '0::' + group in groups:
                        signal.pidfd_send_signal(descriptor, signal_number)
                except ProcessLookupError:
                    pass
                finally:
                    if descriptor is not None:
                        os.close(descriptor)
            for _ in range(40):
                if not self.remaining_children()[1]:
                    return
                await asyncio.sleep(.05)
        raise ValueError('browser_worker_retirement_unconfirmed')

    async def dispatch(self, body):
        if type(body) is not dict or type(body.get('launch_id')) is not str or re.fullmatch(r'[a-f0-9]{32}', body['launch_id']) is None:
            return {'state': 'rejected'}
        identity, operation = body['launch_id'], body.get('op')
        if operation == 'start':
            return await self.start(body)
        if set(body) != {'op', 'launch_id'}:
            return {'state': 'rejected'}
        if operation == 'stop':
            return await self.stop(identity)
        if operation == 'status':
            if identity in self.retired:
                return {'state': 'retired', 'launch_id': identity}
            if identity == self.launch_id and self.chrome is not None:
                if self.chrome.poll() is None:
                    return {'state': 'running', 'launch_id': identity, 'pressure': resources.pressure()}
                return await self.stop(identity)
            return {'state': 'unknown', 'launch_id': identity}
        return {'state': 'rejected'}

    async def handle(self, reader, writer):
        if not self.authorized(writer) or self.clients >= 16:
            writer.close()
            return
        self.clients += 1
        try:
            raw = await asyncio.wait_for(reader.readuntil(b'\n'), 10)
            if len(raw) > protocol.MAX_MESSAGE:
                return
            body = json.loads(raw)
            async with self.lock:
                value = await self.dispatch(body)
            writer.write(json.dumps({'schema': 'radhouse.browser-worker.v1', **value}).encode() + b'\n')
            await writer.drain()
        except (OSError, ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            # Never include a request, Xauthority value, path or browser output.
            return
        finally:
            self.clients -= 1
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()


async def main(args):
    client_uid = pwd.getpwnam(args.client_user).pw_uid
    isolated_process(client_uid)
    if RUN.stat().st_uid != os.getuid() or RUN.stat().st_mode & 0o022:
        raise ValueError('browser_worker_directory_unverified')
    worker = Worker(args.client_cgroup, client_uid)
    local_proxy = await asyncio.start_server(worker.proxy_connection, '127.0.0.1', 18082)
    server = await asyncio.start_unix_server(worker.handle, str(RUN / 'control.sock'), limit=protocol.MAX_MESSAGE)
    (RUN / 'control.sock').chmod(0o660)
    protocol.notify_ready()
    try:
        async with server, local_proxy:
            await server.serve_forever()
    finally:
        if worker.launch_id is not None:
            await worker.stop(worker.launch_id)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--client-cgroup', required=True)
    parser.add_argument('--client-user', default='radhousebot')
    asyncio.run(main(parser.parse_args()))
