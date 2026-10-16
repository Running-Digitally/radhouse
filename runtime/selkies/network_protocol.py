"""Private browser-worker transport. No model-facing operations or payload logging."""
import json
import os
from pathlib import Path
import socket
import stat
import struct

MAX_MESSAGE = 16384


class Unavailable(ValueError):
    """A request was not sent; this attempt cannot have launched a child."""


class Uncertain(ValueError):
    """A sent request has no confirmed outcome; retain its ownership."""


class Rejected(ValueError):
    """The authenticated worker positively rejected this launch attempt."""


def credentials(sock):
    return struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))


def managed_socket(path):
    """Only a root-created /run directory, privately owned by another service."""
    path = Path(path)
    if not path.is_absolute() or path.parent.parent != Path('/run'):
        raise Unavailable('browser_worker_socket_unverified')
    root = path.parent.parent.lstat()
    parent = path.parent.lstat()
    endpoint = path.lstat()
    if (not stat.S_ISDIR(root.st_mode) or root.st_uid != 0 or root.st_mode & 0o022
            or not stat.S_ISDIR(parent.st_mode) or parent.st_mode & 0o022
            or parent.st_uid in {0, os.getuid()} or parent.st_gid != os.getgid()
            or not stat.S_ISSOCK(endpoint.st_mode) or endpoint.st_uid != parent.st_uid
            or endpoint.st_gid != parent.st_gid or endpoint.st_mode & 0o007):
        raise Unavailable('browser_worker_socket_unverified')
    return parent.st_uid


def connect(path, timeout=15):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        uid = managed_socket(path)
        sock.settimeout(timeout)
        sock.connect(str(path))
        pid, peer_uid, _ = credentials(sock)
        if pid <= 0 or peer_uid != uid:
            raise Unavailable('browser_worker_peer_unverified')
        return sock
    except (OSError, ValueError):
        sock.close()
        raise Unavailable('browser_worker_unavailable') from None


def request(path, body, timeout=20):
    raw = json.dumps(body, separators=(',', ':')).encode() + b'\n'
    if len(raw) > MAX_MESSAGE:
        raise Rejected('browser_worker_request_invalid')
    sock = connect(path, timeout)
    with sock:
        try:
            sock.sendall(raw)
            data = bytearray()
            while b'\n' not in data:
                chunk = sock.recv(min(4096, MAX_MESSAGE + 1 - len(data)))
                if not chunk:
                    raise Uncertain('browser_worker_ack_unconfirmed')
                data.extend(chunk)
                if len(data) > MAX_MESSAGE:
                    raise Uncertain('browser_worker_ack_unconfirmed')
            line, remainder = bytes(data).split(b'\n', 1)
            if remainder:
                raise Uncertain('browser_worker_ack_unconfirmed')
            value = json.loads(line)
            if type(value) is not dict or value.get('schema') != 'radhouse.browser-worker.v1':
                raise Uncertain('browser_worker_ack_unconfirmed')
            return value
        except (OSError, ValueError) as error:
            if isinstance(error, Uncertain):
                raise
            raise Uncertain('browser_worker_ack_unconfirmed') from None


def notify_ready():
    endpoint = os.environ.get('NOTIFY_SOCKET')
    if not endpoint:
        return
    if endpoint.startswith('@'):
        endpoint = '\0' + endpoint[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.connect(endpoint)
        sock.sendall(b'READY=1')
