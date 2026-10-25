"""Operator-owned admission barrier; no worker or public API may release it."""
from contextlib import contextmanager
import argparse
import fcntl
import json
import os
from pathlib import Path
import stat
import time
from uuid import UUID

from radhouse.domain.tasks import Rejected


class DispatchGate:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else None

    def _lock(self):
        directory = self.directory
        if not directory.is_absolute() or directory.is_symlink():
            raise ValueError("invalid_control_directory")
        info = directory.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
            raise ValueError("invalid_control_directory")
        fd = os.open(directory / "admission.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            lock = os.fstat(fd)
            if not stat.S_ISREG(lock.st_mode) or lock.st_uid != info.st_uid or lock.st_mode & 0o022:
                raise ValueError("invalid_control_lock")
        except BaseException:
            os.close(fd)
            raise
        return fd

    def held(self):
        if self.directory is None:
            return False
        try:
            fd = self._lock()
            os.close(fd)
            # Any marker, even a broken link or malformed file, holds admission.
            return os.path.lexists(self.directory / "hold.json")
        except (OSError, ValueError):
            return True

    @contextmanager
    def admission(self):
        if self.directory is None:
            yield
            return
        fd = None
        try:
            try:
                fd = self._lock()
                # Refuse while an operator is changing the hold; do not block a
                # web worker or race the exclusive barrier's acknowledgement.
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                if self.held():
                    raise ValueError("held")
            except (OSError, ValueError):
                raise Rejected("assistant_maintenance", 503) from None
            yield
        finally:
            if fd is not None:
                os.close(fd)

    def change(self, cycle, *, release=False, timeout=60):
        """Only the directory's owner can mutate it. No expiry or force release."""
        if str(UUID(cycle)) != cycle:
            raise ValueError("invalid_cycle")
        fd = self._lock()
        try:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ValueError("admission_still_inflight") from None
                    time.sleep(0.05)
            marker = self.directory / "hold.json"
            current = None
            if os.path.lexists(marker):
                hfd = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(hfd) as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != self.directory.stat().st_uid or info.st_mode & 0o022:
                        raise ValueError("invalid_hold")
                    current = json.loads(stream.read(4097))
                if current != {"schema": "radhouse.worker-hold.v1", "cycle": cycle}:
                    raise ValueError("hold_identity_mismatch")
            if release:
                if current is None:
                    raise ValueError("hold_missing")
                marker.unlink()
            elif current is None:
                # Exclusive lock prevents readers crossing publication. fsync
                # both file and directory before reporting the barrier acquired.
                hfd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
                with os.fdopen(hfd, "w") as stream:
                    json.dump({"schema": "radhouse.worker-hold.v1", "cycle": cycle}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
            dfd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        finally:
            os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("action", choices=("init", "hold", "release", "status"))
    parser.add_argument("--cycle")
    args = parser.parse_args()
    if args.action == "init":
        args.directory.mkdir(mode=0o755, parents=False, exist_ok=False)
        fd = os.open(args.directory / "admission.lock", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        os.close(fd)
    gate = DispatchGate(args.directory)
    if args.action in {"hold", "release"}:
        if not args.cycle:
            parser.error("--cycle required")
        gate.change(args.cycle, release=args.action == "release")
    print(json.dumps({"held": gate.held()}))


if __name__ == "__main__":
    main()
