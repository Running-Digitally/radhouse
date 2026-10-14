"""Managed sandboxed Chrome launch. No automatic sandbox-disabling fallback."""
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


async def visible_target(endpoint):
    """Inspect only Chrome's visibility boolean; retain no page URL/content."""
    from aiohttp import ClientSession, ClientTimeout
    async with ClientSession(timeout=ClientTimeout(total=8)) as client:
        async with client.get(endpoint+'/json/list') as response:
            pages = [p for p in await response.json() if p.get('type') == 'page']
        if not 1 <= len(pages) <= 16:
            raise RuntimeError('visible_page_unconfirmed')
        visible = []
        port = urlsplit(endpoint).port
        for page in pages:
            target = page.get('id')
            import re
            if not isinstance(target,str) or not re.fullmatch('[A-Fa-f0-9]{32}',target):
                raise RuntimeError('visible_page_unconfirmed')
            # Construct the fixed local endpoint rather than trust any URL from
            # page metadata. This connection cannot be supplied by an agent.
            async with client.ws_connect(f'ws://127.0.0.1:{port}/devtools/page/{target}') as ws:
                await ws.send_json({'id':1,'method':'Runtime.evaluate','params':{
                    'expression':"document.visibilityState === 'visible'",'returnByValue':True}})
                while True:
                    value = await ws.receive_json()
                    if value.get('id') == 1:
                        if value.get('result',{}).get('result',{}).get('value') is True:
                            visible.append(target)
                        break
        if len(visible) != 1:
            raise RuntimeError('visible_page_unconfirmed')
        return visible[0]
