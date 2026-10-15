"""Public-only HTTP/CONNECT egress. Numeric destination stays DNS-pinned.

TLS is opaque end to end. No URLs, credentials, headers or payloads are logged.
The browser's internal network has no direct route; this is its only egress.
"""
import argparse
import asyncio
import contextlib
import ipaddress
import re
import socket
from urllib.parse import urlsplit

MAX_CONNECTIONS = 128


class Denied(ValueError):
    pass


def endpoint(target, connect=False):
    if any(ord(c) <= 32 or ord(c) == 127 for c in target):
        raise Denied('control_character')
    p = urlsplit('//'+target if connect else target)
    try:
        port = p.port if p.port is not None else (443 if connect else 80)
    except ValueError:
        raise Denied('port') from None
    host = p.hostname
    if (not host or not re.fullmatch(r'[A-Za-z0-9.-]{1,253}', host)
            or p.username is not None or p.password is not None or p.fragment
            or port not in ({443} if connect else {80})
            or (connect and (p.path or p.query))
            or (not connect and p.scheme != 'http')):
        raise Denied('destination')
    return host, port, (p.path or '/')+('?' + p.query if p.query else '')


def public_addresses(host, port, resolver=socket.getaddrinfo):
    rows = resolver(host, port, socket.AF_INET, socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(r[4][0] for r in rows))
    if not addresses or any(not ipaddress.ip_address(a).is_global or ipaddress.ip_address(a).is_multicast or ipaddress.ip_address(a).is_reserved for a in addresses):
        raise Denied('non_public_destination')
    return addresses


async def connect_public(host, port):
    addresses = await asyncio.wait_for(asyncio.to_thread(public_addresses, host, port), 8)
    for address in addresses:
        try:
            # Never re-resolve the hostname after vetting. Rebinding cannot
            # change this numeric connection into a private-address request.
            return await asyncio.wait_for(asyncio.open_connection(address, port, family=socket.AF_INET), 8)
        except (OSError, asyncio.TimeoutError):
            continue
    raise OSError('public_destination_unreachable')


async def relay(reader, writer):
    while chunk := await asyncio.wait_for(reader.read(65536), 120):
        writer.write(chunk)
        await asyncio.wait_for(writer.drain(), 15)
    # A completed upload is not a completed response. Propagate a TCP half-close
    # and let the reverse relay finish instead of truncating its later bytes.
    if writer.can_write_eof():
        writer.write_eof()
        await asyncio.wait_for(writer.drain(), 15)


class Proxy:
    def __init__(self, clients):
        self.clients = [ipaddress.ip_network(c) for c in clients]
        self.connections = 0

    async def handle(self, reader, writer):
        upstream = None
        tasks = []
        peer = writer.get_extra_info('peername')
        if not peer or not any(ipaddress.ip_address(peer[0]) in n for n in self.clients) or self.connections >= MAX_CONNECTIONS:
            writer.close()
            return
        self.connections += 1
        try:
            raw = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 10)
            if len(raw) > 32768:
                raise Denied('header_limit')
            lines = raw.decode('latin1').split('\r\n')
            method, target, version = lines[0].split(' ')
            if version != 'HTTP/1.1' or not re.fullmatch('[A-Z]{1,16}', method):
                raise Denied('request')
            fields = []
            for line in lines[1:-2]:
                name, value = line.split(':', 1)
                name, value = name.strip().lower(), value.strip()
                if not re.fullmatch('[a-z0-9-]+', name) or any(ord(c) < 32 and c != '\t' or ord(c) == 127 for c in value):
                    raise Denied('header')
                fields.append((name,value))
            if len({n for n,_ in fields}) != len(fields):
                raise Denied('ambiguous_header')
            host, port, path = endpoint(target, method == 'CONNECT')
            remote, upstream = await connect_public(host, port)
            if method == 'CONNECT':
                writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                await writer.drain()
            else:
                # Public numeric socket stays fixed for the entire connection.
                # Request pipelining cannot retarget it to a private service.
                fields = [(n,v) for n,v in fields if n not in {'proxy-authorization','proxy-connection','host','connection'}]
                fields += [('host',host),('connection','close')]
                upstream.write((f'{method} {path} HTTP/1.1\r\n'+''.join(f'{n}: {v}\r\n' for n,v in fields)+'\r\n').encode('latin1'))
                await upstream.drain()
            tasks = [asyncio.create_task(relay(reader, upstream)),asyncio.create_task(relay(remote,writer))]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        except (Denied, ValueError, UnicodeError, OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            with contextlib.suppress(OSError):
                writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                await writer.drain()
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if upstream:
                upstream.close()
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
            self.connections -= 1


async def main(args):
    proxy = Proxy(args.client)
    async with await asyncio.start_server(proxy.handle,args.listen,args.port,limit=32768) as server:
        await server.serve_forever()


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--listen',default='127.0.0.1')
    p.add_argument('--port',type=int,default=18082)
    p.add_argument('--client',action='append',required=True)
    asyncio.run(main(p.parse_args()))
