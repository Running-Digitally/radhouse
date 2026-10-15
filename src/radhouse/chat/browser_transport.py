"""Authenticated fixed-path stream relay; application cookies never leave VM220."""
import asyncio
import base64
import hashlib
import json
import re
from types import SimpleNamespace
from urllib.parse import urlsplit

from fastapi import Request, WebSocket
from fastapi.responses import Response
from radhouse.domain.tasks import Rejected

PREFIX = '/chat/browser/stream/'
MAX_ASSET = 16 * 1024 * 1024


def install_stream_routes(app, auth, service, browser):
    def authenticate(request):
        session = auth.session(request)
        service.authorize(session)
        return session

    def target(tail):
        # No redirects, arbitrary host, query, traversal or generic upstream API.
        if (not tail or '..' in tail or '\\' in tail or '%' in tail or tail.startswith('/')
                or any(ord(c)<32 for c in tail)
                or tail.startswith('api/') and tail not in {'api/status','api/health','api/websockets'}):
            raise Rejected('browser_stream_unavailable',404)
        client = browser.hermes._runs._client
        return str(client.base_url)+'v1/browser-stream/'+tail, client.headers['Authorization']

    def owner_headers(session):
        return {'X-Radhouse-Stream-Owner':json.dumps({
            'principal_id':session.principal_id,'conversation_id':session.conversation_id,
            'auth_session_digest':hashlib.sha256(session.token.encode()).hexdigest(),
            'binding_revision':session.binding_revision},separators=(',',':'))}

    @app.get(PREFIX+'{tail:path}')
    async def asset(tail: str, request: Request):
        import aiohttp
        before = await asyncio.to_thread(authenticate,request)
        if request.headers.get('sec-fetch-site') not in {None,'same-origin','none'}:
            raise Rejected('request_origin_denied',403)
        url, authorization = target(tail)
        headers = {'Authorization':authorization,**owner_headers(before)}
        token = request.headers.get('Authorization','').removeprefix('Bearer ') or request.cookies.get('selkies_token','')
        if re.fullmatch(r'[A-Za-z0-9_-]{32,128}',token):
            headers['X-Radhouse-Stream-Token'] = token
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15),trust_env=False) as client:
            async with client.get(url,headers=headers,allow_redirects=False) as upstream:
                chunks=[];size=0
                async for chunk in upstream.content.iter_chunked(64*1024):
                    size+=len(chunk)
                    if size>MAX_ASSET:
                        raise Rejected('browser_stream_unavailable',503)
                    chunks.append(chunk)
                body=b''.join(chunks)
                after = await asyncio.to_thread(authenticate,request)
                if (before.token,before.principal_id,before.conversation_id,before.binding_revision) != (after.token,after.principal_id,after.conversation_id,after.binding_revision):
                    raise Rejected('browser_binding_changed',409)
                return Response(body,status_code=upstream.status,headers={'Content-Type':upstream.headers.get('Content-Type','application/octet-stream')})

    @app.websocket(PREFIX+'api/websockets')
    async def socket(ws: WebSocket):
        import aiohttp
        from aiohttp import WSMsgType
        # LocalAuth accepts ordinary Request metadata. A WebSocket has no HTTP
        # method; treat the initial cookie lookup as GET and check Origin here.
        request = SimpleNamespace(method='GET',cookies=ws.cookies,headers=ws.headers)
        try:
            expected = getattr(auth,'_expected_origin',None)
            parsed = urlsplit(str(ws.url))
            origin = expected or ('https' if parsed.scheme=='wss' else 'http')+'://'+parsed.netloc
            if ws.headers.get('origin') != origin:
                raise Rejected('request_origin_denied',403)
            before = await asyncio.to_thread(authenticate,request)
            url, authorization = target('api/websockets')
            protocols = [p.strip() for p in ws.headers.get('sec-websocket-protocol','').split(',')]
            carried = [p for p in protocols if p.startswith('selkies.token.')]
            if len(protocols)!=2 or 'selkies' not in protocols or len(carried)!=1 or not re.fullmatch(r'selkies\.token\.[A-Za-z0-9_-]{40,180}',carried[0]):
                raise Rejected('browser_stream_unavailable',403)
            encoded = carried[0].removeprefix('selkies.token.')
            token = base64.b64decode(encoded+'='*(-len(encoded)%4),altchars=b'-_',validate=True).decode()
            if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',token):
                raise Rejected('browser_stream_unavailable',403)
            headers = {'Authorization':authorization,**owner_headers(before)}
        except (Rejected,ValueError,UnicodeError):
            await ws.close(code=1008)
            return
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None,connect=5),trust_env=False) as client:
            try:
                async with client.ws_connect(url,headers=headers,protocols=protocols,max_msg_size=8*1024*1024) as upstream:
                    await ws.accept(subprotocol="selkies")
                    async def to_native():
                        while True:
                            message = await ws.receive()
                            if message['type']=='websocket.disconnect': return
                            if message.get('text') is not None:
                                if len(message['text'])>128*1024: return
                                await upstream.send_str(message['text'])
                            elif message.get('bytes') is not None:
                                if len(message['bytes'])>128*1024: return
                                await upstream.send_bytes(message['bytes'])
                    async def to_owner():
                        async for message in upstream:
                            if message.type==WSMsgType.TEXT: await ws.send_text(message.data)
                            elif message.type==WSMsgType.BINARY: await ws.send_bytes(message.data)
                            else: return
                    async def session_watch():
                        while True:
                            await asyncio.sleep(3)
                            after = await asyncio.to_thread(authenticate,request)
                            if (before.token,before.principal_id,before.conversation_id,before.binding_revision) != (after.token,after.principal_id,after.conversation_id,after.binding_revision):
                                return
                    tasks = [asyncio.create_task(to_native()),asyncio.create_task(to_owner()),asyncio.create_task(session_watch())]
                    try: await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        for task in tasks: task.cancel()
                        await asyncio.gather(*tasks,return_exceptions=True)
            except (aiohttp.ClientError,RuntimeError):
                pass
            finally:
                try: await ws.close(code=1008)
                except RuntimeError: pass
