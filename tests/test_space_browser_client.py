import asyncio
import datetime
import importlib.util
import ipaddress
from pathlib import Path
import ssl

import pytest

from tests.test_space_browser_guest import guest, make, IDENTITY

spec = importlib.util.spec_from_file_location("space_client_test",
    Path(__file__).parents[1] / "runtime/selkies/space_client.py")
client_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client_module)
p = guest.protocol


def certificates(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic-browser-service")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256()))
    ca, private = tmp_path / "ca.pem", tmp_path / "key.pem"
    ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private.chmod(0o600)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(ca, private)
    credential = tmp_path / "credential"
    credential.write_text("s" * 43)
    credential.chmod(0o600)
    return context, ca, credential


def configured(origin, ca, credential):
    return client_module.Client({"kind": "space-browser-v1", "origin": origin,
        "ca_path": str(ca), "credential_path": str(credential)}, lambda path, size: path.read_bytes())


def test_real_tls_binding_wrong_credentials_and_response_identity(tmp_path):
    from aiohttp import web
    from aiohttp.test_utils import TestServer
    async def scenario():
        context, ca, credential = certificates(tmp_path)
        service = make(tmp_path)
        server = TestServer(service.application(), scheme="https")
        await server.start_server(ssl=context)
        try:
            client = configured(str(server.make_url("/")), ca, credential)
            assert (await client.call("start"))["state"] == "running"
            wrong = configured(client.origin, ca, credential)
            wrong.headers["X-Radhouse-Browser-Service"] = "x" * 43
            with pytest.raises(p.Rejected):
                await wrong.call("status")
            assert (await client.call("stop"))["state"] == "retired"
            assert (await client.call("status"))["state"] == "retired"
        finally:
            await server.close()

        async def mismatched(request):
            value = await request.json()
            return web.json_response({**{k: value[k] for k in ("schema", "launch_id", "sequence")},
                "request_id": "0" * 32, "data": {"state": "retired"}})
        app = web.Application()
        app.router.add_post("/v1/request", mismatched)
        server = TestServer(app, scheme="https")
        await server.start_server(ssl=context)
        try:
            client = configured(str(server.make_url("/")), ca, credential)
            with pytest.raises(p.Uncertain, match="response_unconfirmed"):
                await client.call("stop")
        finally:
            await server.close()
    asyncio.run(scenario())


def test_tls_tunnel_transfers_native_protocol_bytes_and_closes(tmp_path):
    from aiohttp.test_utils import TestServer
    async def scenario():
        context, ca, credential = certificates(tmp_path)
        service = make(tmp_path)
        await service.start(IDENTITY)
        async def echo(reader, writer):
            try:
                while raw := await reader.read(65536):
                    writer.write(raw)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        local = await asyncio.start_server(echo, "127.0.0.1", 0)
        service.endpoint = "http://127.0.0.1:" + str(local.sockets[0].getsockname()[1])
        server = TestServer(service.application(), scheme="https")
        await server.start_server(ssl=context)
        tunnel = None
        try:
            client = configured(str(server.make_url("/")), ca, credential)
            client.launch_id = IDENTITY
            tunnel = await asyncio.to_thread(client_module.Tunnel, client)
            reader, writer = await asyncio.open_connection("127.0.0.1", tunnel.port)
            payload = b"HTTP/1.1 synthetic-native-frame\x00\xff"
            writer.write(payload)
            await writer.drain()
            assert await asyncio.wait_for(reader.readexactly(len(payload)), 3) == payload
            await service.revoke()
            assert await asyncio.wait_for(reader.read(), 3) == b""
            writer.close()
            await writer.wait_closed()
        finally:
            if tunnel:
                await asyncio.to_thread(tunnel.close)
                assert not tunnel.thread.is_alive()
            await server.close()
            local.close()
            await local.wait_closed()
    asyncio.run(scenario())


@pytest.mark.parametrize("origin", ["http://browser.test", "https://a:b@browser.test", "https://browser.test/other",
    "https://browser.test?target=elsewhere", "https://browser.test#part", "https://browser.test\\evil"])
def test_caller_cannot_select_a_proxy_destination(tmp_path, origin):
    _, ca, credential = certificates(tmp_path)
    with pytest.raises(p.Rejected):
        configured(origin, ca, credential)


def test_world_readable_service_credential_is_refused(tmp_path):
    _, ca, credential = certificates(tmp_path)
    credential.chmod(0o644)
    with pytest.raises(p.Rejected):
        configured("https://browser.test", ca, credential)


def test_retirement_reconciliation_reads_receipt_without_repeating_stop():
    class ReceiptClient:
        def __init__(self):
            self.operations = []
            self.state = 'running'
        def request(self, operation, **kwargs):
            self.operations.append(operation)
            return {'state': self.state}
    client = ReceiptClient()
    chrome = client_module.RemoteChrome(client)
    assert not chrome.reconcile_retirement() and chrome.poll() is None
    client.state = 'retired'
    assert chrome.reconcile_retirement() and chrome.poll() == 0
    assert client.operations == ['status', 'status']
