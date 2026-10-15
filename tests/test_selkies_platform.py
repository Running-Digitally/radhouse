"""Privacy revocation must win a native snapshot already in flight."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.test_browser_control import control

spec=importlib.util.spec_from_file_location('platform_under_test',Path(__file__).parents[1]/'runtime/selkies/platform.py')
platform=importlib.util.module_from_spec(spec)
spec.loader.exec_module(platform)


def test_private_waits_for_and_discards_inflight_observation(tmp_path):
    async def scenario():
        c=control.BrowserController(tmp_path/'control.sqlite3',maintenance_held=lambda:False)
        identity=control.BrowserIdentity('conversation','session','generation')
        run=control.RunBinding('old-run','session','old-dispatch')
        owner=control.OwnerBinding('alice','a'*64,1,'tab')
        state=c.bind_browser(identity,run,'alice')
        state=c.request_takeover(identity,owner,'take',revision=state.revision,auth_expires_at=10**10)
        state=c.confirm_takeover(identity,state.revision,control.FenceObservation(identity,state.takeover_after,True))
        state=c.observation_mode(identity,owner,state.lease.lease_id,state.revision,'observe')
        p=platform.Platform.__new__(platform.Platform)
        p.bridge=SimpleNamespace(_controller=c)
        p.owned=SimpleNamespace(identity=identity)
        p.boundary=SimpleNamespace(input_lock=asyncio.Lock(),transition_lock=asyncio.Lock())
        context=SimpleNamespace(run_id='observer',dispatch_key='observer-dispatch')
        p.observers={(context.run_id,context.dispatch_key):(owner,state.lease.lease_id,state.lease.observation_epoch)}
        capture_started=asyncio.Event();finish_capture=asyncio.Event()
        async def snapshot():
            capture_started.set();await finish_capture.wait()
            return {'secret':'must never be returned'}
        p.snapshot=snapshot
        read=asyncio.create_task(p.observation(context))
        await capture_started.wait()
        private=asyncio.create_task(p.visibility(owner,{'lease_id':state.lease.lease_id,'revision':state.revision,'mode':'private'}))
        await asyncio.sleep(0)
        assert c.state(identity).lease.observation_mode=='private'
        assert not private.done()
        finish_capture.set()
        with pytest.raises(control.ControlRejected,match='browser_observation_denied'):
            await read
        assert (await private).lease.observation_mode=='private'
        with pytest.raises(control.ControlRejected): await p.observation(context)
    asyncio.run(scenario())


def test_real_uvicorn_websocket_upgrade_and_binary_transfer():
    """TestClient alone cannot detect an absent production WS server backend."""
    import socket
    import aiohttp
    import uvicorn
    async def scenario():
        payload=b'qualified-video-packet'*16000
        async def app(scope,receive,send):
            assert scope['type']=='websocket'
            assert (await receive())['type']=='websocket.connect'
            await send({'type':'websocket.accept','subprotocol':'selkies'})
            assert (await receive())['text']=='START_VIDEO'
            await send({'type':'websocket.send','bytes':payload})
            await send({'type':'websocket.close','code':1000})
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(5)
        server=uvicorn.Server(uvicorn.Config(app,ws='wsproto',lifespan='off',log_config=None,access_log=False))
        task=asyncio.create_task(server.serve(sockets=[listener]))
        try:
            for _ in range(100):
                if server.started:break
                await asyncio.sleep(.01)
            assert server.started
            async with aiohttp.ClientSession() as client:
                async with client.ws_connect('http://127.0.0.1:'+str(listener.getsockname()[1]),protocols=['selkies']) as ws:
                    assert ws.protocol=='selkies'
                    await ws.send_str('START_VIDEO')
                    message=await ws.receive(timeout=3)
                    assert message.type==aiohttp.WSMsgType.BINARY and message.data==payload
        finally:
            server.should_exit=True
            await task
            listener.close()
    asyncio.run(scenario())


def test_actual_authenticated_relay_through_uvicorn_wsproto():
    """ASGI owns subprotocols; wsproto removes their original HTTP header."""
    import base64,hashlib,socket
    import aiohttp
    from aiohttp import web
    from fastapi import FastAPI
    import uvicorn
    from radhouse.chat.browser_transport import install_stream_routes
    from tests.test_minimal_chat import SyntheticAuth
    async def scenario():
        token='x'*43;payload=b'qualified-frame'*20000;calls=[]
        async def native(request):
            assert request.headers['Authorization']=='Bearer synthetic-service'
            assert not request.cookies
            owner=__import__('json').loads(request.headers['X-Radhouse-Stream-Owner'])
            assert owner['auth_session_digest']==hashlib.sha256(b'synthetic-cookie').hexdigest()
            calls.append(True)
            ws=web.WebSocketResponse(protocols=['selkies']);await ws.prepare(request)
            await ws.send_str('AUTH_SUCCESS,synthetic');await ws.send_bytes(payload)
            async for message in ws:pass
            return ws
        upstream=web.Application();upstream.router.add_get('/v1/browser-stream/api/websockets',native)
        runner=web.AppRunner(upstream,access_log=None);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        endpoint='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])+'/'
        browser=SimpleNamespace(hermes=SimpleNamespace(_runs=SimpleNamespace(_client=SimpleNamespace(base_url=endpoint,headers={'Authorization':'Bearer synthetic-service'}))))
        app=FastAPI();install_stream_routes(app,SyntheticAuth(),SimpleNamespace(authorize=lambda session:None),browser)
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(5)
        server=uvicorn.Server(uvicorn.Config(app,ws='wsproto',lifespan='off',log_config=None,access_log=False))
        task=asyncio.create_task(server.serve(sockets=[listener]))
        try:
            for _ in range(100):
                if server.started:break
                await asyncio.sleep(.01)
            origin='http://127.0.0.1:'+str(listener.getsockname()[1])
            protocol='selkies.token.'+base64.urlsafe_b64encode(token.encode()).decode().rstrip('=')
            async with aiohttp.ClientSession(cookies={'radhouse_session':'synthetic-cookie'}) as client:
                async with client.ws_connect(origin+'/chat/browser/stream/api/websockets',headers={'Origin':origin},protocols=['selkies',protocol]) as ws:
                    assert ws.protocol=='selkies'
                    assert (await ws.receive(timeout=3)).data=='AUTH_SUCCESS,synthetic'
                    message=await ws.receive(timeout=3)
                    assert message.type==aiohttp.WSMsgType.BINARY and message.data==payload
            assert calls==[True]
        finally:
            server.should_exit=True;await task;listener.close();await runner.cleanup()
    asyncio.run(scenario())


@pytest.mark.parametrize('flag',['observation_only','return_to_agent'])
def test_dispatch_client_forwards_typed_takeover_flags(flag):
    import httpx,json
    from radhouse.integrations.hermes import HermesRunsClient
    calls=[]
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(202,headers={'Idempotency-Replayed':'false'},json={'run_id':'run-1','status':'started','replayed':False})
    owner={'principal_id':'alice','conversation_id':'conversation'}
    context={'generation':'generation','revision':1,'lease_id':'lease','owner':{**owner,'auth_session_digest':'a'*64,'binding_revision':1,'tab_id':'tab'},'auth_expires_at':10**10,flag:True}
    with HermesRunsClient('http://127.0.0.1','synthetic-service',transport=httpx.MockTransport(respond)) as client:
        client.start_or_attach(input_text='Synthetic takeover check',session_id='session',dispatch_key='dispatch',disable_tools=False,
            allowed_tools=('browser_navigate','browser_snapshot'),browser_owner=owner,browser_context=context)
    assert calls[0]['browser_context']==context


@pytest.mark.parametrize('flags',[{'observation_only':1},{'return_to_agent':'yes'},{'observation_only':True,'return_to_agent':True}])
def test_dispatch_client_rejects_invalid_takeover_flags_before_network(flags):
    import httpx
    from radhouse.integrations.hermes import HermesRunsClient
    calls=[]
    with HermesRunsClient('http://127.0.0.1','synthetic-service',transport=httpx.MockTransport(lambda request:calls.append(request))) as client:
        with pytest.raises(ValueError,match='invalid_hermes_browser_context'):
            client.start_or_attach(input_text='Synthetic check',session_id='session',dispatch_key='dispatch',disable_tools=False,
                allowed_tools=('browser_navigate','browser_snapshot'),browser_owner={'principal_id':'alice','conversation_id':'conversation'},
                browser_context={'generation':'generation','revision':1,'lease_id':'lease','owner':{},'auth_expires_at':10**10,**flags})
    assert not calls


def test_dead_browser_watcher_revokes_without_a_human_lease(monkeypatch):
    async def scenario():
        events=[]
        async def publish():events.append('revoke')
        async def drain():events.append('drain')
        p=platform.Platform.__new__(platform.Platform)
        p.owned=SimpleNamespace(identity='identity')
        p.bridge=SimpleNamespace(_controller=SimpleNamespace(state=lambda identity:SimpleNamespace(lease=None),pause=lambda *args:pytest.fail('no human lease to pause')))
        p.boundary=SimpleNamespace(_blocked=False,input_token='old',provision=publish,_drain=drain)
        p.stopped=False
        monkeypatch.setattr(platform,'_chrome',None)
        monkeypatch.setattr(platform,'retire',lambda:events.append('retire'))
        await p.watch()
        assert p.stopped and p.boundary._blocked and p.boundary.input_token is None
        assert events==['revoke','drain','retire']
    asyncio.run(scenario())
