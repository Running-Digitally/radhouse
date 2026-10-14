"""Managed sandboxed Chrome launch. No automatic sandbox-disabling fallback."""
import asyncio
import os
from pathlib import Path
import shlex
import subprocess
import time
from urllib.parse import urlsplit

CHROME = '/opt/browser/chrome-linux64/chrome'


def chrome_arguments(profile, proxy=None):
    args = [CHROME, '--disable-extensions', '--no-first-run', '--no-default-browser-check',
        '--disable-background-networking', '--disable-component-update', '--disable-sync',
        '--disable-breakpad', '--password-store=basic', '--use-mock-keychain',
        '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
        '--force-webrtc-ip-handling-policy=disable_non_proxied_udp', '--start-maximized',
        '--user-data-dir='+str(profile)]
    if proxy:
        p = urlsplit(proxy)
        if p.scheme != 'http' or not p.hostname or not p.port or p.username or p.password or p.path not in ('', '/') or p.query or p.fragment:
            raise ValueError('invalid_review_proxy')
        args += ['--proxy-server='+proxy,
            '--proxy-bypass-list=<-loopback>;127.0.0.1:18081']
    args.append('http://127.0.0.1:18081/')
    return args


def launch(profile, env, proxy=None):
    profile.mkdir(mode=0o700)
    child = subprocess.Popen(chrome_arguments(profile, proxy), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port_file = profile / 'DevToolsActivePort'
    for _ in range(200):
        if child.poll() is not None:
            raise RuntimeError('sandboxed_chrome_launch_refused')
        if port_file.is_file():
            port = int(port_file.read_text().splitlines()[0])
            if not 1 <= port <= 65535:
                raise RuntimeError('debug_port_invalid')
            return child, f'http://127.0.0.1:{port}'
        time.sleep(.05)
    child.terminate()
    child.wait(timeout=5)
    raise RuntimeError('sandboxed_chrome_not_ready')


def verify(browser_pid, proc=Path('/proc'), *, require_namespaces=True):
    """Owned renderer proof: nested user/PID/network namespaces and BPF filter.

    Chrome rewrites renderer argv into one cmdline field. Parse that field for
    role/flags only; never retain page URLs or whole process command lines.
    """
    parent = proc / str(browser_pid)
    def status(p):
        return dict(l.split(':', 1) for l in (p/'status').read_text().splitlines() if ':' in l)
    main = status(parent)
    parent_ns = {n: os.readlink(parent/'ns'/n) for n in ('user', 'pid', 'net')}
    parent_filters = int(main.get('Seccomp_filters', '0'))
    renderers = []
    for p in proc.glob('[0-9]*'):
        try:
            raw = (p/'cmdline').read_bytes().replace(b'\x00', b' ').decode()
            args = shlex.split(raw)
            if not args or args[0] != CHROME or '--type=renderer' not in args:
                continue
            ancestor = int(s0['PPid'].strip()) if (s0 := status(p)) else 0
            for _ in range(12):
                if ancestor in {0, 1, browser_pid}:
                    break
                ancestor = int(status(proc/str(ancestor))['PPid'].strip())
            if ancestor != browser_pid:
                continue
            if any(a in {'--no-sandbox', '--disable-seccomp-filter-sandbox', '--disable-namespace-sandbox'} for a in args):
                raise RuntimeError('renderer_sandbox_disabled')
            s = status(p)
            uid = int(s['Uid'].split()[0])
            nested = {n: os.readlink(p/'ns'/n) != parent_ns[n] for n in parent_ns} if require_namespaces else {}
            pid_depth = len(s.get('NSpid', '').split()) > len(main.get('NSpid', '').split())
            filters = int(s.get('Seccomp_filters', '0'))
            if uid == 0 or s.get('NoNewPrivs', '').strip() != '1' or s.get('Seccomp', '').strip() != '2' or filters <= parent_filters or not pid_depth or (require_namespaces and not all(nested.values())) or int(main.get('CapEff', '0'), 16):
                raise RuntimeError('renderer_sandbox_unconfirmed')
            renderers.append({'uid':uid, 'nested_namespaces':nested, 'nested_pid_namespace':pid_depth, 'seccomp_filters':filters})
        except (FileNotFoundError, ProcessLookupError):
            continue
    if not renderers:
        raise RuntimeError('renderer_sandbox_missing')
    return {'enabled':True, 'proof_level':'user_pid_net_namespaces_and_bpf' if require_namespaces else 'pid_namespace_and_bpf', 'renderer_count':len(renderers),
        'parent_seccomp_filters':parent_filters, 'renderers':renderers}


async def _rpc(ws, method, params=None, *, timeout=8):
    # ClientSession's HTTP timeout does not bound WebSocket receives. A crashed
    # renderer or unrelated events must not hold the human handback lock forever.
    async with asyncio.timeout(timeout):
        await ws.send_json({'id':1, 'method':method, 'params':params or {}})
        while True:
            reply = await ws.receive_json()
            if reply.get('id') == 1:
                if 'error' in reply or 'result' not in reply:
                    raise RuntimeError('page_check_unconfirmed')
                return reply['result']


def _target_url(endpoint, target):
    import re
    if not isinstance(target, str) or not re.fullmatch('[A-Fa-f0-9]{32}', target):
        raise RuntimeError('page_check_unconfirmed')
    return f'ws://127.0.0.1:{urlsplit(endpoint).port}/devtools/page/{target}'


async def _isolated_boolean(ws, frame, expression):
    world = await _rpc(ws, 'Page.createIsolatedWorld',
        {'frameId':frame, 'worldName':'radhouse-private-page-check'})
    context = world.get('executionContextId')
    if type(context) is not int:
        raise RuntimeError('page_check_unconfirmed')
    value = await _rpc(ws, 'Runtime.evaluate', {'expression':expression,
        'contextId':context, 'returnByValue':True})
    result = value.get('result', {}).get('value')
    if 'exceptionDetails' in value or type(result) is not bool:
        raise RuntimeError('page_check_unconfirmed')
    return result


async def _browser_url(client, endpoint):
    async with client.get(endpoint+'/json/version') as response:
        response.raise_for_status()
        version = await response.json()
    import re
    path = urlsplit(version['webSocketDebuggerUrl']).path
    if not re.fullmatch(r'/devtools/browser/[A-Fa-f0-9-]{36}', path):
        raise RuntimeError('browser_endpoint_unconfirmed')
    return f'ws://127.0.0.1:{urlsplit(endpoint).port}'+path


async def notify_memory_pressure(endpoint):
    # Fixed maintenance only: no heap snapshots, page values, input or agent API.
    from aiohttp import ClientSession, ClientTimeout
    async with asyncio.timeout(8), ClientSession(timeout=ClientTimeout(total=8)) as client:
        async with client.ws_connect(await _browser_url(client, endpoint)) as ws:
            await _rpc(ws, 'Memory.simulatePressureNotification', {'level':'critical'})
        # A browser pressure notification alone need not reclaim renderer Blob
        # wrappers promptly. Ask each owned page to collect unreachable objects;
        # otherwise completed high-speed transfers can OOM a cgroup-sized VM.
        # Do not enable a profiler or retrieve objects, content or response bodies.
        pages, _ = await _targets(client, endpoint)
        for page in pages:
            async with client.ws_connect(_target_url(endpoint, page.get('id'))) as ws:
                await _rpc(ws, 'HeapProfiler.collectGarbage')


async def _targets(client, endpoint):
    async with client.get(endpoint+'/json/list') as response:
        response.raise_for_status()
        targets = await response.json()
    pages = [p for p in targets if p.get('type') == 'page']
    # /json/list omits OOP iframe targets in current Chrome.
    async with client.ws_connect(await _browser_url(client, endpoint)) as ws:
        all_targets = await _rpc(ws, 'Target.getTargets')
    frames = {p['targetId'] for p in all_targets['targetInfos'] if p.get('type') == 'iframe'}
    if not 1 <= len(pages) <= 16 or len(frames) > 64:
        raise RuntimeError('page_check_unconfirmed')
    return pages, frames


async def visible_target(endpoint):
    """An isolated world prevents a site's getters from spoofing visibility."""
    from aiohttp import ClientSession, ClientTimeout
    async with asyncio.timeout(8), ClientSession(timeout=ClientTimeout(total=8)) as client:
        pages, _ = await _targets(client, endpoint)
        visible = []
        for page in pages:
            target = page.get('id')
            async with client.ws_connect(_target_url(endpoint, target)) as ws:
                tree = await _rpc(ws, 'Page.getFrameTree')
                frame = tree['frameTree']['frame']['id']
                if await _isolated_boolean(ws, frame, "document.visibilityState === 'visible'"):
                    visible.append(target)
        if len(visible) != 1:
            raise RuntimeError('visible_page_unconfirmed')
        return visible[0]


_SENSITIVE = r"""(() => {
    function sensitive(root) {
        for (const e of root.querySelectorAll('input')) {
            const tokens = e.autocomplete.toLowerCase().split(/\s+/);
            if ((e.type === 'password' || tokens.includes('one-time-code')) && e.value) return true;
        }
        for (const e of root.querySelectorAll('*')) {
            if (e.shadowRoot && sensitive(e.shadowRoot)) return true;
        }
        return false;
    }
    return sensitive(document);
})()"""


async def sensitive_clear(endpoint, target):
    """Return booleans only, including child/OOP frames and open shadow roots.

    The page's main-world querySelectorAll/value hooks cannot override these
    checks. Missing frames, detached contexts and protocol errors fail closed.
    """
    from aiohttp import ClientSession, ClientTimeout
    async with asyncio.timeout(8), ClientSession(timeout=ClientTimeout(total=8)) as client:
        pages, oop_frames = await _targets(client, endpoint)
        if target not in {p.get('id') for p in pages}:
            raise RuntimeError('page_check_unconfirmed')
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            sockets = {}
            async def connection(owner):
                if owner not in sockets:
                    sockets[owner] = await stack.enter_async_context(
                        client.ws_connect(_target_url(endpoint, owner)))
                return sockets[owner]
            ws = await connection(target)
            tree = await _rpc(ws, 'Page.getFrameTree')
            pending = [(tree['frameTree'], target)]
            # Page.getFrameTree omits OOP children too. Each OOP root carries
            # its real parentId; join only descendants of the selected page.
            children_by_parent = {}
            for frame in oop_frames:
                peer = await connection(frame)
                child_tree = (await _rpc(peer, 'Page.getFrameTree'))['frameTree']
                if child_tree['frame']['id'] != frame or not child_tree['frame'].get('parentId'):
                    raise RuntimeError('page_check_unconfirmed')
                children_by_parent.setdefault(child_tree['frame']['parentId'], []).append((child_tree, frame))
            seen = set()
            while pending:
                node, inherited = pending.pop()
                frame = node['frame']['id']
                if frame in seen:
                    continue
                seen.add(frame)
                if len(seen) > 64:
                    raise RuntimeError('page_check_unconfirmed')
                owner = frame if frame in oop_frames else inherited
                peer = await connection(owner)
                if await _isolated_boolean(peer, frame, _SENSITIVE):
                    return False
                children = list(node.get('childFrames', []))
                if owner != inherited:
                    child_tree = await _rpc(peer, 'Page.getFrameTree')
                    children.extend(child_tree['frameTree'].get('childFrames', []))
                pending.extend((child, owner) for child in children)
                pending.extend(children_by_parent.get(frame, []))
        return True
