import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import time

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

spec = importlib.util.spec_from_file_location('space_gateway_test',
    Path(__file__).parents[1] / 'runtime/selkies/space_gateway.py')
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)
SID = 'sbx_00000000-0000-0000-0000-000000000001'
PORT = 'port_00000000-0000-0000-0000-000000000002'


def envelope(sequence, operation=None, identity='a' * 32):
    return {'schema':gateway.protocol.SCHEMA,'launch_id':identity,'request_id':'f'*32,
            'sequence':sequence,'op':operation or ('start' if sequence == 1 else 'status'),'body':{}}



def private(path, text):
    path.write_text(text); path.chmod(0o600)
    return str(path)


def test_fixed_gateway_renews_attachment_without_replaying_browser_request(tmp_path):
    async def scenario():
        events = []
        bad_identity = [False]
        async def attachment(request):
            assert request.headers['Authorization'] == 'Bearer synthetic-native-api-key'
            assert await request.json() == {'port': 8080, 'protocol': 'http'}
            events.append(('attach', request.headers['Idempotency-Key']))
            sid = PORT if not bad_identity[0] else PORT[:-1] + '3'
            payload = json.dumps({'id': sid, 'sandbox_id': SID, 'kind': 'port',
                'target_port': 8080, 'target_protocol': 'http', 'scopes': ['port:connect'], 'state': 'open',
                'attach': {'url': '/v1/sessions/' + sid + '/proxy', 'token': 'synthetic-attachment-key',
                    'events_url': None, 'token_transport': ['authorization_header'],
                    'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}}).encode()
            # Real HTTP bodies can arrive in fragments. One read(n) is not a
            # complete response, even for a small acknowledged attachment.
            response = web.StreamResponse(status=201, headers={'Content-Type': 'application/json'})
            await response.prepare(request)
            await response.write(payload[:13])
            await asyncio.sleep(.01)
            await response.write(payload[13:])
            await response.write_eof()
            return response
        async def browser(request):
            # The guest never sees a native API credential or caller Authorization.
            assert request.headers['Authorization'] == 'Bearer synthetic-attachment-key'
            assert request.headers['X-Radhouse-Browser-Service'] == 's' * 43
            assert request.headers['X-Radhouse-Browser-Launch'] == 'a' * 32
            events.append(('browser', await request.json()))
            return web.json_response({'synthetic': True})
        app = web.Application()
        app.router.add_post('/v1/sandboxes/' + SID + '/port-sessions', attachment)
        app.router.add_post('/v1/sessions/' + PORT + '/proxy/v1/request', browser)
        async with TestServer(app) as upstream:
            origin = str(upstream.make_url('/'))
            config = {'api_origin': origin, 'data_origin': origin, 'sandbox_id': SID, 'port':8080,
                'api_credential_path': private(tmp_path / 'api-key', 'synthetic-native-api-key'),
                'browser_credential_path': private(tmp_path / 'browser-key', 's' * 43),
                'attachment_state_path': private(tmp_path / 'attachment.json', json.dumps({
                    'session_id': PORT, 'key': 'acknowledged-create-key', 'created_at': time.time()})),
                'clients': ['127.0.0.1']}
            service = gateway.Gateway(config)
            headers = {'X-Radhouse-Browser-Service': 's' * 43,
                'X-Radhouse-Browser-Launch': 'a' * 32, 'Authorization': 'Bearer caller-token-not-forwarded'}
            async with TestClient(TestServer(service.application())) as client:
                response = await client.post('/v1/request', json=envelope(1))
                assert response.status == 403 and not events
                for path in ('/v1/sandboxes', '/v1/exec', '/chat/browser/stream/api/exec', '/v1/request?target=elsewhere'):
                    assert (await client.post(path, headers=headers, json={})).status == 403
                assert not events
                assert (await client.post('/v1/request', headers=headers, json=envelope(1))).status == 200
                assert (await client.post('/v1/request', headers=headers, json=envelope(2))).status == 200
                assert events == [('attach', 'acknowledged-create-key'), ('browser', envelope(1)), ('browser', envelope(2))]
                service.attachment.current['expires_at'] = time.time() + 10
                assert (await client.post('/v1/request', headers=headers, json=envelope(3))).status == 200
                assert events[-2:] == [('attach', 'acknowledged-create-key'), ('browser', envelope(3))]
                service.attachment.current['expires_at'] = time.time()
                bad_identity[0] = True
                assert (await client.post('/v1/request', headers=headers, json=envelope(4))).status == 503
                assert events[-1] == ('attach', 'acknowledged-create-key')
    asyncio.run(scenario())


def test_pending_new_attachment_requires_reconciliation(tmp_path):
    async def scenario():
        class UnusedHTTP:
            def post(self, *args, **kwargs):
                raise AssertionError('An uncertain creation must not be replayed')
        config = {'api_origin':'http://127.0.0.1:18080', 'data_origin':'http://127.0.0.1:8090',
            'sandbox_id':SID, 'port':8080,
            'api_credential_path':private(tmp_path / 'key', 'synthetic-native-api-key'),
            'attachment_state_path':private(tmp_path / 'state', json.dumps({'pending':'new-unconfirmed-key'}))}
        attachment = gateway.Attachment(config)
        try:
            await attachment.get(UnusedHTTP())
        except ValueError as error:
            assert str(error) == 'attachment_creation_unconfirmed'
        else:
            raise AssertionError('uncertain creation admitted')
    asyncio.run(scenario())


def test_host_retirement_receipt_survives_gateway_replacement(tmp_path):
    import pytest
    path = tmp_path / 'launches.sqlite3'
    old = gateway.LaunchJournal(path, SID)
    assert old.admit(envelope(1)) is None
    old.database.close()  # Lose the reply and restart the gateway.
    replacement = gateway.LaunchJournal(path, SID[:-1] + '9')
    with pytest.raises(gateway.protocol.Rejected):
        replacement.admit(envelope(2, 'stop'))
    with pytest.raises(gateway.protocol.Rejected):
        replacement.admit(envelope(3, 'start'))
    assert not replacement.active('a' * 32)
    # Represents the fixed operator procedure, after positive old-VM retirement.
    with replacement.database:
        replacement.database.execute('UPDATE launches SET retired=1 WHERE sandbox=?', (SID,))
    for operation in ('status', 'stop'):
        receipt = replacement.admit(envelope(4, operation))
        assert receipt['data']['state'] == 'retired'
        assert receipt['launch_id'] == 'a' * 32
    with pytest.raises(gateway.protocol.Rejected):
        replacement.admit(envelope(5, 'start'))
    assert replacement.admit(envelope(1, identity='b' * 32)) is None
    assert replacement.active('b' * 32)
    assert not replacement.active('a' * 32)
    replacement.database.close()
