"""Public egress must never become a hostname-based private-network tunnel."""
import importlib.util
from pathlib import Path
import socket
import unittest
from unittest.mock import AsyncMock, patch

spec=importlib.util.spec_from_file_location('public_proxy',Path(__file__).parents[1]/'runtime/selkies/public_proxy.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)


def resolve(*addresses):
    return lambda *args: [(socket.AF_INET,socket.SOCK_STREAM,6,'',(a,443)) for a in addresses]


class DestinationTests(unittest.TestCase):
    def test_real_web_ports_and_origin_form(self):
        self.assertEqual(p.endpoint('example.com:443',True),('example.com',443,'/'))
        self.assertEqual(p.endpoint('http://example.com/a?b=2'),('example.com',80,'/a?b=2'))
    def test_protocol_port_credentials_and_control_rejected(self):
        for value,connect in [('127.0.0.1:22',True),('[::1]:443',True),('example.com:443/x',True),('user:pw@example.com:443',True),('https://example.com/',False),('file:///etc/passwd',False),('http://example.com:8080/',False),('http://example.com/#x',False),('http://a\r\nb/',False)]:
            with self.subTest(value=value),self.assertRaises(p.Denied):p.endpoint(value,connect)
    def test_nonpublic_and_mixed_dns_answers_rejected(self):
        for address in ['127.0.0.1','192.168.100.200','10.1.2.3','172.20.0.1','169.254.169.254','100.64.0.1','0.0.0.0','224.0.0.1','198.18.0.1']:
            with self.subTest(address=address),self.assertRaises(p.Denied):p.public_addresses('site.example',443,resolve(address))
        with self.assertRaises(p.Denied):p.public_addresses('site.example',443,resolve('93.184.215.14','127.0.0.1'))
        with self.assertRaises(p.Denied):p.public_addresses('site.example',443,resolve())
        self.assertEqual(p.public_addresses('site.example',443,resolve('93.184.215.14')),['93.184.215.14'])
    def test_encoded_loopback_is_vetted_after_dns_normalization(self):
        host,port,_=p.endpoint('2130706433:443',True)
        with self.assertRaises(p.Denied):p.public_addresses(host,port)


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_dns_pin_numeric_socket_not_hostname(self):
        with patch.object(p,'public_addresses',return_value=['93.184.215.14']) as lookup,patch.object(p.asyncio,'open_connection',new=AsyncMock(return_value=('reader','writer'))) as connect:
            self.assertEqual(await p.connect_public('rebind.example',443),('reader','writer'))
            lookup.assert_called_once_with('rebind.example',443)
            connect.assert_awaited_once_with('93.184.215.14',443,family=socket.AF_INET)
    async def test_denied_dns_never_opens_connection(self):
        with patch.object(p,'public_addresses',side_effect=p.Denied('nonpublic')),patch.object(p.asyncio,'open_connection',new=AsyncMock()) as connect:
            with self.assertRaises(p.Denied):await p.connect_public('private.example',443)
            connect.assert_not_awaited()

class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_tunnels_only_after_public_check(self):
        async def backend(reader,writer):
            value=await reader.readexactly(4);writer.write(value);await writer.drain();writer.close()
        backend_server=await p.asyncio.start_server(backend,'127.0.0.1',0)
        async def permitted(host,port):
            self.assertEqual((host,port),('example.com',443))
            return await p.asyncio.open_connection('127.0.0.1',backend_server.sockets[0].getsockname()[1])
        proxy=p.Proxy(['127.0.0.0/8'])
        front=await p.asyncio.start_server(proxy.handle,'127.0.0.1',0)
        try:
            with patch.object(p,'connect_public',side_effect=permitted):
                reader,writer=await p.asyncio.open_connection('127.0.0.1',front.sockets[0].getsockname()[1])
                writer.write(b'CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n');await writer.drain()
                self.assertIn(b'200 Connection Established',await reader.readuntil(b'\r\n\r\n'))
                writer.write(b'ping');await writer.drain();self.assertEqual(await reader.readexactly(4),b'ping')
                writer.close();await writer.wait_closed()
        finally:
            front.close();backend_server.close();await front.wait_closed();await backend_server.wait_closed()
    async def test_ambiguous_request_cannot_open_destination(self):
        proxy=p.Proxy(['127.0.0.0/8']);front=await p.asyncio.start_server(proxy.handle,'127.0.0.1',0)
        try:
            with patch.object(p,'connect_public',new=AsyncMock()) as destination:
                reader,writer=await p.asyncio.open_connection('127.0.0.1',front.sockets[0].getsockname()[1])
                writer.write(b'CONNECT example.com:443 HTTP/1.1\r\nHost: example.com\r\nHost: duplicate\r\n\r\n');await writer.drain()
                self.assertIn(b'403 Forbidden',await reader.read());destination.assert_not_awaited();writer.close();await writer.wait_closed()
        finally:front.close();await front.wait_closed()

class TrustedSelectionTests(unittest.TestCase):
    def test_target_selection_uses_fixed_native_protocol_without_public_tool(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('owned_native',Path(__file__).parents[1]/'runtime/hermes/native_control.py')
        m=importlib.util.module_from_spec(spec)
        import sys
        sys.modules[spec.name]=m;spec.loader.exec_module(m)
        c=object.__new__(m.NativeControlChannel)
        c._submit=lambda *args:args
        target='A'*32
        self.assertEqual(c.submit_trusted_target('id',target),('id','trusted',[{'action':'tab_switch','tabId':target}]))
        for invalid in ('', '1', '../target', 1):
            with self.assertRaises(m.NativeRejected):c.submit_trusted_target('id',invalid)
        with self.assertRaises(m.NativeRejected):m.tool_command('tab_switch',{'tabId':target})
