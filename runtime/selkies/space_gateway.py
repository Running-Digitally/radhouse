"""TLS gateway to one configured SPACE browser port, outside the guest.

Only this host service holds the SPACE API credential. It can renew the fixed
port attachment; it exposes no management, command, file or destination API.
Browser mutations are forwarded once and never retried after ambiguous failure.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import sqlite3
import stat
import importlib.util
import time
from urllib.parse import urlsplit
from uuid import uuid4

from aiohttp import web, ClientSession, ClientTimeout, WSMsgType

MAX_BODY = 64 * 1024
MAX_FRAME = 8 * 1024 * 1024
MAX_ASSET = 16 * 1024 * 1024

_spec = importlib.util.spec_from_file_location('gateway_browser_protocol', Path(__file__).with_name('space_protocol.py'))
protocol = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(protocol)


class LaunchJournal:
    """Execution receipts only; controller authorization remains outside this host.

    Reserve before forwarding start, including attempts whose replies are lost.
    The fixed host recovery procedure may mark an old sandbox's rows retired
    only after proving its execution ended. This service cannot do that itself.
    """
    def __init__(self, path, sandbox):
        parent = path.parent.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or parent.st_mode & 0o077:
            raise ValueError('private_launch_journal_required')
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ValueError('private_launch_journal_required')
        finally:
            os.close(descriptor)
        self.database = sqlite3.connect(path)
        self.database.execute('CREATE TABLE IF NOT EXISTS launches (id TEXT PRIMARY KEY, sandbox TEXT NOT NULL, retired INTEGER NOT NULL DEFAULT 0 CHECK(retired IN (0,1)))')
        self.database.commit()
        self.sandbox = sandbox

    def admit(self, envelope):
        identity, operation = envelope['launch_id'], envelope['op']
        row = self.database.execute('SELECT sandbox, retired FROM launches WHERE id=?', (identity,)).fetchone()
        if operation == 'start':
            if row is not None:
                raise protocol.Rejected('previous_browser_unresolved')
            with self.database:
                self.database.execute('INSERT INTO launches(id,sandbox) VALUES (?,?)', (identity,self.sandbox))
        elif row is not None and row[1] == 1 and operation in {'status', 'stop'}:
            return {**{k:envelope[k] for k in ('schema','launch_id','request_id','sequence')},
                    'data':{'state':'retired','connected':[],'faulted':False}}
        elif row != (self.sandbox, 0):
            raise protocol.Rejected('stale_browser_request')
        return None

    def active(self, identity):
        return self.database.execute('SELECT sandbox,retired FROM launches WHERE id=?', (identity,)).fetchone() == (self.sandbox, 0)


def private_file(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in {0, os.geteuid()}
                or info.st_mode & 0o027):
            raise ValueError('private_gateway_configuration_required')
        raw = stream.read(MAX_BODY + 1)
    if len(raw) > MAX_BODY:
        raise ValueError('gateway_configuration_too_large')
    return raw


def loopback_origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1'
            or parsed.port is None or not 1 <= parsed.port <= 65535 or parsed.username or parsed.password
            or parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
        raise ValueError('local_space_origin_required')
    return value.rstrip('/')


class Attachment:
    def __init__(self, config):
        self.api = loopback_origin(config['api_origin'])
        self.data = loopback_origin(config['data_origin'])
        self.sandbox = config['sandbox_id']
        if re.fullmatch(r'sbx_[a-f0-9-]{36}', self.sandbox) is None:
            raise ValueError('invalid_sandbox_identity')
        self.port = config['port']
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError('invalid_browser_port')
        self.api_token = private_file(config['api_credential_path']).decode().strip()
        self.path = Path(config['attachment_state_path'])
        self.state = json.loads(private_file(self.path))
        self.current = None
        self.lock = asyncio.Lock()

    def save(self):
        temporary = self.path.with_suffix('.new')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(self.state, stream)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, self.path)
        descriptor = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    async def get(self, http):
        async with self.lock:
            if self.current and self.current['expires_at'] - time.time() > 45:
                return dict(self.current)
            if self.state.get('pending'):
                raise ValueError('attachment_creation_unconfirmed')
            # The pinned SPACE implementation renews attach tokens when the
            # acknowledged create key is reused. This is an explicit renewal,
            # never a replay of a browser operation or sandbox creation.
            rotating = time.time() - self.state['created_at'] >= 23 * 3600
            if rotating:
                self.state['pending'] = 'radhouse-browser-' + uuid4().hex
                self.save()
            key = self.state['pending'] if rotating else self.state['key']
            headers = {'Authorization': 'Bearer ' + self.api_token, 'Idempotency-Key': key}
            async with http.post(self.api + '/v1/sandboxes/' + self.sandbox + '/port-sessions',
                    headers=headers, json={'port': self.port, 'protocol': 'http'},
                    allow_redirects=False, timeout=ClientTimeout(total=15)) as response:
                if response.status != 201:
                    raise ValueError('attachment_unconfirmed')
                chunks, size = [], 0
                async for chunk in response.content.iter_chunked(8192):
                    size += len(chunk)
                    if size > MAX_BODY:
                        raise ValueError('attachment_unconfirmed')
                    chunks.append(chunk)
                raw = b''.join(chunks)
                value = json.loads(raw)
            sid = value.get('id')
            attach = value.get('attach', {})
            if (type(sid) is not str or re.fullmatch(r'port_[a-f0-9-]{36}', sid) is None
                    or not rotating and sid != self.state['session_id']
                    or value.get('sandbox_id') != self.sandbox or value.get('kind') != 'port'
                    or value.get('target_port') != self.port or value.get('target_protocol') != 'http'
                    or value.get('scopes') != ['port:connect']
                    or value.get('state') not in {'pending', 'attaching', 'open', 'reconnecting'}):
                raise ValueError('attachment_identity_unconfirmed')
            path = '/v1/sessions/' + sid + '/proxy'
            if (attach.get('url') not in {path, self.data + path}
                    or 'authorization_header' not in attach.get('token_transport', [])
                    or attach.get('events_url') is not None):
                raise ValueError('attachment_destination_unconfirmed')
            token = attach.get('token')
            expiry = datetime.fromisoformat(attach['expires_at'].replace('Z', '+00:00'))
            if (type(token) is not str or not 1 <= len(token) <= 4096 or token == self.api_token
                    or any(not 0x21 <= ord(c) <= 0x7e for c in token)
                    or expiry.tzinfo is None or expiry <= datetime.now(timezone.utc)):
                raise ValueError('attachment_token_unconfirmed')
            if rotating:
                self.state = {'session_id': sid, 'key': key, 'created_at': time.time()}
                self.save()
            self.current = {'url': self.data + path, 'token': token, 'expires_at': expiry.timestamp()}
            return dict(self.current)


class Gateway:
    def __init__(self, config):
        self.attachment = Attachment(config)
        self.credential = private_file(config['browser_credential_path']).strip()
        if re.fullmatch(rb'[A-Za-z0-9_-]{43,128}', self.credential) is None:
            raise ValueError('invalid_browser_credential')
        self.clients = {str(ipaddress.ip_address(value)) for value in config['clients']}
        self.pipes = set()
        self.http = None
        self.journal = LaunchJournal(self.attachment.path.parent / 'launches.sqlite3', self.attachment.sandbox)

    async def serve(self, request):
        peer = request.transport.get_extra_info('peername')
        if (not peer or peer[0] not in self.clients or not hmac.compare_digest(
                request.headers.get('X-Radhouse-Browser-Service', '').encode(), self.credential)):
            return web.Response(status=403)
        # Match decoded path and reject all queries and path escape forms.
        path = request.path
        if request.query_string or '..' in path or '\\' in path or '%' in path:
            return web.Response(status=403)
        is_ws = request.headers.get('Upgrade', '').lower() == 'websocket'
        control = request.method == 'POST' and path == '/v1/request' and not is_ws
        cdp = request.method == 'GET' and path == '/v1/cdp' and is_ws
        viewer = request.method == 'GET' and path.startswith('/chat/browser/stream/')
        if not (control or cdp or viewer):
            return web.Response(status=403)
        if viewer:
            tail = path.removeprefix('/chat/browser/stream/')
            if ('/api/' in '/'+tail and tail not in {'api/status', 'api/health', 'api/websockets'}
                    or is_ws and tail != 'api/websockets'):
                return web.Response(status=403)
        if is_ws and len(self.pipes) >= 32:
            return web.Response(status=429)
        try:
            body = await request.read() if control else None
            if control:
                try:
                    envelope = protocol.request(json.loads(body))
                    retired = self.journal.admit(envelope)
                except (ValueError, TypeError, KeyError, protocol.Rejected):
                    return web.json_response({'error':'browser_request_rejected'}, status=409)
                if retired is not None:
                    return web.json_response(retired, headers={'Cache-Control':'no-store'})
            elif not self.journal.active(request.headers.get('X-Radhouse-Browser-Launch', '')):
                return web.Response(status=409)
            attach = await self.attachment.get(self.http)
            headers = {name: request.headers[name] for name in (
                'X-Radhouse-Browser-Service', 'X-Radhouse-Browser-Launch', 'X-Radhouse-Stream-Token') if name in request.headers}
            headers['Authorization'] = 'Bearer ' + attach['token']
            url = attach['url'] + path
            if is_ws:
                protocols = tuple(p.strip() for p in request.headers.get('Sec-WebSocket-Protocol', '').split(',') if p.strip())
                async with self.http.ws_connect(url, headers=headers, protocols=protocols, max_msg_size=MAX_FRAME) as remote:
                    downstream = web.WebSocketResponse(protocols=('selkies',) if viewer else (), max_msg_size=MAX_FRAME)
                    await downstream.prepare(request)
                    self.pipes.add(downstream)
                    async def copy(source, target):
                        async for message in source:
                            if message.type == WSMsgType.BINARY:
                                await target.send_bytes(message.data)
                            elif message.type == WSMsgType.TEXT and viewer:
                                await target.send_str(message.data)
                            else:
                                break
                    tasks = [asyncio.create_task(copy(downstream, remote)), asyncio.create_task(copy(remote, downstream))]
                    try:
                        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        await downstream.close()
                        self.pipes.discard(downstream)
                    return downstream
            if control:
                headers['Content-Type'] = 'application/json'
            # One request only. A timeout propagates uncertainty to the controller.
            async with self.http.request(request.method, url, headers=headers, data=body,
                    allow_redirects=False, timeout=ClientTimeout(total=50 if control else 15)) as response:
                chunks, size = [], 0
                async for chunk in response.content.iter_chunked(65536):
                    size += len(chunk)
                    if size > (MAX_BODY if control else MAX_ASSET):
                        raise ValueError('browser_response_limit')
                    chunks.append(chunk)
                return web.Response(status=response.status, body=b''.join(chunks), headers={
                    'Content-Type': response.headers.get('Content-Type', 'application/octet-stream'),
                    'Cache-Control': 'no-store'})
        except Exception:
            return web.json_response({'error': 'browser_outcome_unconfirmed'}, status=503)

    def application(self):
        app = web.Application(client_max_size=MAX_BODY)
        async def lifetime(app):
            self.http = ClientSession(trust_env=False, timeout=ClientTimeout(total=None, connect=5))
            try:
                yield
            finally:
                await asyncio.gather(*(p.close(code=1001) for p in list(self.pipes)))
                await self.http.close()
                self.journal.database.close()
        app.cleanup_ctx.append(lifetime)
        app.router.add_route('*', '/{path:.*}', self.serve)
        return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configuration', required=True)
    args = parser.parse_args()
    config = json.loads(private_file(args.configuration))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(config['certificate_path'], config['private_key_path'])
    web.run_app(Gateway(config).application(), host=config['bind'], port=config['listen_port'],
        ssl_context=context, access_log=None, print=None)


if __name__ == '__main__':
    main()
