"""Embedded, owner-bound Selkies transport for the canonical Hermes browser.

The package is installed separately from Hermes' immutable environment. No
model-facing arbitrary evaluation, X11, clipboard or HTTP proxy is exposed.
"""
import asyncio
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

runtime = None
configuration = None
_display = None
_chrome = None
_endpoint = None
_root = None


def load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def configure(bridge, path):
    global configuration, _root
    value = json.loads(bridge._root_file(Path(path), 2 * 1024 * 1024))
    if set(value) != {'schema', 'root', 'files', 'dependencies'} or value['schema'] != 'radhouse.selkies-platform.v1':
        raise ValueError('stream_installation_unverified')
    root = Path(value['root'])
    if not root.is_absolute() or not str(root).startswith('/opt/radhouse-selkies/'):
        raise ValueError('stream_installation_unverified')
    for name, digest in value['files'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('stream_installation_unverified')
        raw = bridge._root_file(root / name, 64 * 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('stream_installation_unverified')
    # Append: never shadow or replace an installed Hermes dependency.
    sys.path.append(str(root / 'python'))
    from importlib.metadata import version
    if any(version(name) != expected for name, expected in value['dependencies'].items()):
        raise ValueError('stream_dependencies_unverified')
    configuration, _root = value, root


def launch(bridge, directory, environment):
    global _display, _chrome, _endpoint
    if not configuration or (_chrome is not None and _chrome.poll() is None):
        raise ValueError('stream_browser_busy')
    previous = runtime
    if previous is not None:
        # Finish the old server/watcher before spawning another Chrome or
        # replacing its durable identity. Looking up the old generation after
        # bind_browser would be stale, and its watcher could retire the new page.
        old = bridge._controller.state(previous.owned.identity)
        if not old.retired or not bridge._pid_gone(previous.owned.pid, previous.owned.started):
            raise ValueError('stream_retirement_unconfirmed')
        try: calling_loop = asyncio.get_running_loop()
        except RuntimeError: calling_loop = None
        if calling_loop is previous.loop or not previous.loop.is_running():
            raise ValueError('stream_launch_requires_worker')
        stopped = asyncio.run_coroutine_threadsafe(previous.stop(), previous.loop)
        try: stopped.result(timeout=20)
        except BaseException:
            stopped.cancel()
            raise
        if runtime is not None:
            raise ValueError('stream_retirement_unconfirmed')
    if _display is None:
        display_number = secrets.randbelow(50000) + 100
        auth = Path(tempfile.mkdtemp(prefix='radhouse-display-')) / 'Xauthority'
        auth.touch(mode=0o600)
        subprocess.run(['/usr/bin/xauth','-f',str(auth),'add',':'+str(display_number),'.',secrets.token_hex(16)],
            check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        os.environ['XAUTHORITY'] = str(auth)
        _display = subprocess.Popen(['/usr/bin/Xvfb', ':'+str(display_number), '-screen', '0', '1280x900x24', '-nolisten', 'tcp', '-auth',str(auth), '-noreset'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.environ['DISPLAY'] = ':'+str(display_number)
        for _ in range(100):
            if _display.poll() is not None:
                raise ValueError('stream_display_unavailable')
            if Path('/tmp/.X11-unix/X'+str(display_number)).exists():
                break
            time.sleep(.05)
        else:
            raise ValueError('stream_display_unavailable')
    environment['DISPLAY'] = os.environ['DISPLAY']
    environment['XAUTHORITY'] = os.environ['XAUTHORITY']
    sandbox = load('radhouse_platform_sandbox', Path(__file__).with_name('sandbox.py'))
    sandbox.CHROME = bridge._browser_configuration['chromium_path']
    _chrome, _endpoint = sandbox.launch(directory / 'chrome-profile', environment, start_url='about:blank')
    for attempt in range(50):
        try:
            sandbox.verify(_chrome.pid,require_namespaces=False)
            break
        except RuntimeError as error:
            if str(error)!='renderer_sandbox_missing' or attempt==49:
                retire()
                raise
            time.sleep(.1)
    return _endpoint


def retire():
    global _chrome, _endpoint
    if _chrome is not None and _chrome.poll() is None:
        _chrome.terminate()
        try:
            _chrome.wait(timeout=8)
        except subprocess.TimeoutExpired:
            # Do not forget an unretired process or replace it with another page.
            raise ValueError('stream_retirement_unconfirmed') from None
    _chrome = _endpoint = None


async def ensure(bridge, owned):
    global runtime
    if runtime is None:
        runtime = Platform(bridge, owned)
        runtime.startup = asyncio.create_task(runtime.activate())
        runtime.startup.add_done_callback(consume_failure)
    current = runtime
    if current.owned is not owned:
        raise ValueError('stream_browser_busy')
    if current.stopped:
        raise ValueError('stream_retirement_unconfirmed')
    # A disconnected request cannot cancel a startup shared with other callers.
    # Nobody receives the instance until its server and boundary are ready.
    await asyncio.shield(current.startup)
    if runtime is not current or current.stopped:
        raise ValueError('stream_retirement_unconfirmed')
    return current


def consume_failure(task):
    # Startup/shutdown can outlive their HTTP request. Keep their result on the
    # instance for subsequent callers without an unobserved task exception.
    if not task.cancelled():
        task.exception()


class Platform:
    def __init__(self, bridge, owned):
        self.bridge, self.owned = bridge, owned
        self.loop = asyncio.get_running_loop()
        self.boundary = None
        self.socket = Path(tempfile.mkdtemp(prefix='radhouse-stream-')) / 'stream.sock'
        self.observers = {}
        self.handover = None
        self.aligned = None
        self.stopped = False
        self.connected_input = None
        self.pressure_checked = 0
        self.ready = False
        self.startup = None
        self.shutdown = None
        self.server = None
        self.data = None
        self.watcher = None
        self.retirement = None
        self.cleaned = False

    async def activate(self):
        try:
            await self.start()
            self.ready = not self.stopped
        except BaseException:
            self.stopped = True
            await self.cleanup()
            raise

    async def start(self):
        bridge, owned = self.bridge, self.owned
        control, native = bridge._control_modules()
        stream = load('radhouse_platform_control', Path(__file__).with_name('control.py'))
        self.sandbox = load('radhouse_platform_sandbox', Path(__file__).with_name('sandbox.py'))
        # Import settings only after the closed platform configuration is set.
        os.environ.update({
            'SELKIES_MASTER_TOKEN':secrets.token_urlsafe(32),
            'SELKIES_MODE':'websockets','SELKIES_SUBFOLDER':'/chat/browser/stream',
            'SELKIES_WEB_ROOT':str(_root / 'web'),'SELKIES_UNIX_SOCKET':str(self.socket),
            'SELKIES_JS_SOCKET_PATH':str(self.socket.parent),
            'SELKIES_WEBCAM_SOCKET_PATH':str(self.socket.parent),
            'SELKIES_ENABLE_BASIC_AUTH':'false','SELKIES_ENABLE_DUAL_MODE':'false',
            'SELKIES_AUDIO_ENABLED':'false','SELKIES_ENABLE_RESIZE':'false',
            'SELKIES_GAMEPAD_ENABLED':'false|locked','SELKIES_PRINTING_ENABLED':'false|locked',
            'SELKIES_MICROPHONE_ENABLED':'false|locked','SELKIES_WEBCAM_ENABLED':'false|locked',
            'SELKIES_SECOND_SCREEN':'false|locked','SELKIES_COMPUTER_USE_BIND':'',
            'SELKIES_MANUAL_WIDTH':'1280','SELKIES_MANUAL_HEIGHT':'900',
            'SELKIES_FRAMERATE':'30-30','SELKIES_ENCODER':'h264enc',
            'SELKIES_ENABLE_CLIPBOARD':'true','SELKIES_CLIPBOARD_SEAMLESS':'true|locked',
            'SELKIES_ENABLE_BINARY_CLIPBOARD':'false|locked','SELKIES_COMMAND_ENABLED':'false|locked',
            'SELKIES_ENABLE_COLLAB':'true|locked','SELKIES_USE_CPU':'true',
            'SELKIES_WAYLAND':'false','SELKIES_GPU_ID':'-1','SELKIES_MAC_CMD_AS_CTRL':'true'})
        os.environ.pop('PIXELFLUX_CU', None)
        from aiohttp import web
        from selkies import sessions
        from selkies.settings import settings
        # Upstream settings are process-cached. Rebind every generation-owned
        # endpoint and master capability before constructing another backend.
        settings.unix_socket = str(self.socket)
        settings.js_socket_path = str(self.socket.parent)
        settings.webcam_socket_path = str(self.socket.parent)
        settings.master_token = os.environ['SELKIES_MASTER_TOKEN']
        from selkies.stream_server import CentralizedStreamServer
        from selkies.websockets_mode import DataStreamingServer, client_permissions, reconcile_clients
        for name in ('input', 'ws'):
            logging.getLogger(name).setLevel(logging.CRITICAL)
        if (settings.enable_collab != (True, True) or settings.command_enabled[0]
                or settings.audio_enabled[0] or settings.enable_resize[0] or settings.wayland[0]
                or settings.microphone_enabled[0] or settings.webcam_enabled[0]
                or settings.second_screen[0] or settings.computer_use_bind):
            raise ValueError('stream_settings_unqualified')
        async def fence(state):
            handle = owned.channel.fence_after(uuid4().hex, owned.last_handle)
            owned.last_handle = handle
            ack = await handle.wait()
            if not isinstance(ack, native.FenceAck) or not ack.quiescent:
                raise ValueError('native_fence_unconfirmed')
            return control.FenceObservation(owned.identity, state.takeover_after, True)
        async def publish(table):
            sessions.user_tokens = table
            sessions.active_mk_token = next((t for t,p in table.items() if p.get('mk_control')), None)
            self.data.config_gate.set()
            await reconcile_clients()
        async def clear_clipboard():
            h = self.data.input_handler
            d = h.xdisplay
            none = d.create_resource_object('window',0)
            selections = [d.intern_atom('CLIPBOARD'),d.intern_atom('PRIMARY')]
            for selection in selections:
                none.set_selection_owner(selection,0)
            d.sync()
            h._clipboard_last_bytes = h._clipboard_self_write = None
            return all(d.get_selection_owner(s) == 0 for s in selections)
        async def resume(owner, revision, observation):
            # Typed proof is consumed only by the durably reserved fresh run.
            self.handover = control.HumanReturnObservation(owned.identity, owner, revision, True)
        self.boundary = boundary = stream.StreamingControl(bridge._controller, owned.identity,
            fence=fence, observe=self.snapshot, publish=publish, resume=resume,
            current=lambda: owned.identity.generation if _chrome and _chrome.poll() is None else None,
            clear_clipboard=clear_clipboard, sensitive_clear=self.sensitive_clear)
        @web.middleware
        async def closed(request, handler):
            if '/api/' in request.path and request.path not in {
                    '/chat/browser/stream/api/status','/chat/browser/stream/api/health',
                    '/chat/browser/stream/api/websockets'}:
                return web.Response(status=403)
            return await handler(request)
        class Server(CentralizedStreamServer):
            async def initialize_app(inner):
                app = await super().initialize_app()
                app.middlewares.insert(0, closed)
                return app
        class Data(DataStreamingServer):
            def initialize(inner):
                super().initialize()
                # The upstream handler otherwise creates process-wide gamepad
                # listeners, even with gamepad messages disabled. This adapter
                # owns only keyboard/pointer input and retires per generation.
                inner.input_handler.num_gamepads = 0
                boundary.attach(inner.input_handler, lambda cid: next((p.get('token') for ws,p in client_permissions.items() if id(ws)==cid),None))
                async def no_clipboard_monitor():
                    return
                inner.input_handler.start_clipboard = no_clipboard_monitor
        await asyncio.to_thread(settings.resolve_encoder_backends)
        self.server = Server(settings)
        self.data = Data(self.server)
        self.server.register_service('websockets', self.data)
        await self.server.switch_to_mode('websockets')
        await boundary.provision()
        await self.server.start_server()
        self.watcher = asyncio.create_task(self.watch())
        self.client_permissions = client_permissions

    async def viewer(self, owner):
        b = self.boundary
        for v in b.viewers.values():
            if v.owner == owner:
                return v
        if len(b.viewers) >= 16:
            # Only prune disconnected non-holders; capability reuse never crosses owners.
            connected = {p.get('token') for p in self.client_permissions.values()}
            for token,v in list(b.viewers.items()):
                if token not in connected and v.owner != b.input_owner:
                    b.viewers.pop(token); b._viewer_last_seen.pop(token,None)
                    break
            else:
                raise ValueError('stream_viewer_capacity')
        v = b.add_viewer(owner, can_take=True)
        await b.provision()
        return v

    async def visible(self):
        target = await self.sandbox.visible_target(_endpoint)
        if target != self.aligned:
            handle = self.owned.channel.submit_trusted_target(uuid4().hex, target)
            self.owned.last_handle = handle
            result = await handle.wait()
            if not result.completed or result.legacy.get('success') is not True:
                raise ValueError('visible_page_unconfirmed')
            self.aligned = target
        return target

    async def sensitive_clear(self):
        self.aligned = None
        target = await self.visible()
        return await self.sandbox.sensitive_clear(_endpoint,target)

    async def snapshot(self):
        if not await self.sensitive_clear():
            raise ValueError('sensitive_fields_present')
        handle = self.owned.channel.submit_tool(uuid4().hex,'browser_snapshot',{'full':True})
        self.owned.last_handle = handle
        ack = await handle.wait()
        if not ack.completed or not ack.legacy.get('success'):
            raise ValueError('native_observation_unconfirmed')
        return ack.legacy

    async def observation(self, context):
        b, c = self.boundary, self.bridge._controller
        grant = self.observers.get((context.run_id,context.dispatch_key))
        if grant is None:
            raise ValueError('browser_observation_denied')
        owner,lease_id,epoch = grant
        async with b.input_lock:
            c.authorize_observation(self.owned.identity,owner,lease_id,epoch)
            result = await self.snapshot()
            # Revocation is durable before its barrier waits. Discard late captures.
            c.authorize_observation(self.owned.identity,owner,lease_id,epoch)
            return result

    async def visibility(self, owner, body):
        b = self.boundary
        async with b.transition_lock:
            state = self.bridge._controller.observation_mode(self.owned.identity,owner,
                body.get('lease_id'),body.get('revision'),body.get('mode'))
            # No new observation can pass its post-capture epoch check; await any
            # earlier native read before confirming private to the owner.
            async with b.input_lock:
                return state

    async def watch(self):
        try:
            while True:
                await asyncio.sleep(.25)
                if (not _chrome or _chrome.poll() is not None
                        or hasattr(self.bridge,'_pid_gone') and self.bridge._pid_gone(self.owned.pid,self.owned.started)):
                    raise ValueError('stream_browser_unavailable')
                if time.monotonic()-self.pressure_checked >= 2:
                    self.pressure_checked = time.monotonic()
                    resources = load('radhouse_platform_resources',Path(__file__).with_name('resources.py'))
                    if resources.pressure():
                        try: await self.sandbox.notify_memory_pressure(_endpoint)
                        except Exception: pass  # Maintenance failure cannot discard the owner browser.
                await self.boundary.reconcile()
                await self.boundary.settle_takeover()
                connected = {p.get('token') for p in self.client_permissions.values()}
                token = self.boundary.input_token
                if token in connected and token is not None:
                    self.connected_input = token
                elif token is not None and token == self.connected_input:
                    await self.boundary.disconnect(token)
                    self.connected_input = None
        except asyncio.CancelledError:
            raise
        except Exception:
            self.boundary._blocked = True
            self.boundary.input_token = None
            try:
                state = self.bridge._controller.state(self.owned.identity)
                if state.lease is not None:
                    try: self.bridge._controller.pause(self.owned.identity,state.lease.owner)
                    except Exception:
                        if self.bridge._controller.state(self.owned.identity).lease is not None: raise
                await self.boundary.provision()
                await self.boundary._drain()
            finally:
                self.stopped = True
                self.retirement = asyncio.create_task(asyncio.to_thread(retire))
                self.retirement.add_done_callback(consume_failure)
                await asyncio.shield(self.retirement)

    async def stop(self):
        self.stopped = True
        self.ready = False
        if self.boundary is not None:
            self.boundary._blocked = True
            self.boundary.input_token = None
        if (self.shutdown is None or self.shutdown.cancelled()
                or self.shutdown.done() and self.shutdown.exception() is not None):
            self.shutdown = asyncio.create_task(self.finish_stop())
            self.shutdown.add_done_callback(consume_failure)
        await asyncio.shield(self.shutdown)

    async def finish_stop(self):
        # A stop requested during startup cannot race later server allocation.
        if self.startup is not None:
            try:
                await asyncio.shield(self.startup)
            except Exception:
                pass  # Cleanup may be retried, but failed ownership is retained.
        await self.cleanup()

    async def cleanup(self):
        global runtime
        if self.cleaned:
            return
        # Even failed revocation/draining must attempt to stop the transport.
        # Only a fully confirmed cleanup releases the generation reservation.
        try:
            if self.boundary is not None:
                self.boundary._blocked = True
                self.boundary.input_token = None
                if self.data is not None:
                    await self.boundary.provision()
                if self.boundary.handler is not None:
                    await self.boundary._drain()
        finally:
            await self.stop_transport()
        self.observers.clear()
        self.socket.unlink(missing_ok=True)
        self.socket.parent.rmdir()
        self.cleaned = True
        if runtime is self:
            runtime = None

    async def stop_transport(self):
        try:
            if self.watcher is not None:
                self.watcher.cancel()
                await asyncio.gather(self.watcher, return_exceptions=True)
            # Cancelling an asyncio waiter cannot stop an already-running thread.
            # Its result must be known before another generation can launch.
            if self.retirement is not None:
                await asyncio.shield(self.retirement)
        finally:
            if self.server is not None:
                await self.server.stop_server()


async def relay(bridge, adapter, request):
    """Service-authenticated fixed UDS relay. Never resolves caller-provided hosts."""
    from aiohttp import web, ClientSession, ClientTimeout, UnixConnector, WSMsgType
    error = adapter._check_auth(request)
    if error is not None:
        return error
    current = runtime
    tail = request.match_info['tail']
    if current is None or current.stopped or not current.ready or '..' in tail or tail.startswith('/'):
        return web.Response(status=409)
    path = '/chat/browser/stream/'+tail
    # The service-authenticated web relay asserts its freshly checked cookie
    # binding. A token from another auth session cannot cross this boundary.
    from selkies.stream_server import handshake_session_token
    token = handshake_session_token(request) if request.headers.get('Upgrade','').lower()=='websocket' else request.headers.get('X-Radhouse-Stream-Token','')
    try:
        bound = json.loads(request.headers['X-Radhouse-Stream-Owner'])
        if bound.get('conversation_id') != current.owned.identity.conversation_id:
            raise ValueError('owner_mismatch')
        if '/api/' in path:
            b = current.boundary
            owner = b.input_owner if token is not None and token==b.input_token else b.viewer(token).owner
            if any(bound.get(k) != getattr(owner,k) for k in ('principal_id','auth_session_digest','binding_revision')):
                raise ValueError('owner_mismatch')
    except Exception:
        return web.Response(status=403)
    if '/api/' in path and tail not in {'api/status','api/health','api/websockets'}:
        return web.Response(status=403)
    async with ClientSession(connector=UnixConnector(path=str(current.socket)),timeout=ClientTimeout(total=None,connect=5)) as client:
        url = 'http://localhost'+path
        if request.headers.get('Upgrade','').lower() == 'websocket':
            if tail != 'api/websockets':
                return web.Response(status=403)
            async with client.ws_connect(url,protocols=tuple(p.strip() for p in request.headers.get('Sec-WebSocket-Protocol','').split(',')),max_msg_size=8*1024*1024) as upstream:
                downstream = web.WebSocketResponse(max_msg_size=128*1024,protocols=('selkies',))
                await downstream.prepare(request)
                async def copy(source,destination):
                    async for message in source:
                        if message.type == WSMsgType.TEXT: await destination.send_str(message.data)
                        elif message.type == WSMsgType.BINARY: await destination.send_bytes(message.data)
                        else: break
                tasks = [asyncio.create_task(copy(downstream,upstream)),asyncio.create_task(copy(upstream,downstream))]
                try: await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in tasks: task.cancel()
                    await asyncio.gather(*tasks,return_exceptions=True)
                    await downstream.close()
                return downstream
        async with client.get(url,headers={'Authorization':'Bearer '+token} if token else {},timeout=ClientTimeout(total=15)) as response:
            chunks=[];size=0
            async for chunk in response.content.iter_chunked(64*1024):
                size+=len(chunk)
                if size>16*1024*1024: return web.Response(status=502)
                chunks.append(chunk)
            body=b''.join(chunks)
            return web.Response(body=body,status=response.status,headers={'Content-Type':response.headers.get('Content-Type','application/octet-stream'),'Cache-Control':'no-store'})
