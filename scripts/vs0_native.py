#!/usr/bin/env python3
"""Optional owned native Postgres proof; does not replace pinned Docker qualification.

RADHOUSE_VS0_NATIVE_BIN=/absolute/postgres/bin python scripts/vs0_native.py verify
Creates a new random cluster; never contacts an existing server. Keeps a sanitized
manifest, removes only its own data directory after a confirmed stop.
"""
from pathlib import Path
import hashlib
import os
import secrets
import shlex
import subprocess
import shutil
import socket
import stat
import sys

from vs0 import Run, FixtureError, ROOT, main


class NativeRun(Run):
    def preflight(self):
        if any(os.environ.get(key) for key in (
            'PGHOST', 'PGHOSTADDR', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSWORD',
            'PGSERVICE', 'PGSERVICEFILE', 'PGOPTIONS',
        )):
            raise FixtureError('unset PostgreSQL overrides before creating the fixture')
        requested = Path(os.environ.get('RADHOUSE_VS0_NATIVE_BIN', ''))
        if not requested.is_absolute():
            raise FixtureError('absolute native Postgres binary directory required')
        self.bin = requested.resolve()
        for name in ('initdb', 'pg_ctl', 'postgres'):
            if not (self.bin / name).is_file():
                raise FixtureError('explicit absolute native Postgres binary directory required')
        if shutil.disk_usage(ROOT).free < 2 * 1024**3:
            raise FixtureError('fixture needs 2 GiB free disk')
        self.output.mkdir(parents=True, exist_ok=False, mode=0o700)
        self.cluster = self.output / 'data'
        self.socket_dir = self.output / 'socket'
        self.socket_dir.mkdir(mode=0o700)
        self.manifest.update(
            backend='native', native_cluster_id=self.run_id,
            data_directory=str(self.cluster), python=sys.version.split()[0],
            source_commit=self.command(['git', 'rev-parse', 'HEAD']).stdout.strip(),
            postgres_version=self.command([str(self.bin / 'postgres'), '--version']).stdout.strip(),
            postgres_binary_sha256=hashlib.sha256((self.bin / 'postgres').read_bytes()).hexdigest(),
            dependency_lock_sha256=hashlib.sha256((ROOT / 'uv.lock').read_bytes()).hexdigest(),
        )
        self.save()

    def start(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        password = secrets.token_urlsafe(32)
        pw = self.output / 'password'
        pw.write_text(password)
        pw.chmod(0o600)
        try:
            self.command([str(self.bin / 'initdb'), '-D', str(self.cluster), '-U', 'fixture_owner',
                          '--auth-local=trust', '--auth-host=scram-sha-256', '--pwfile', str(pw)])
        finally:
            pw.unlink(missing_ok=True)
        (self.cluster / 'radhouse-fixture-id').write_text(self.run_id)
        with socket.socket() as endpoint:
            endpoint.bind(('127.0.0.1', 0))
            port = endpoint.getsockname()[1]
        # A port race refuses startup. No fallback connection to another server.
        self.command([str(self.bin / 'pg_ctl'), '-D', str(self.cluster), '-l', str(self.output / 'postgres.log'),
                      '-o', shlex.join(['-h', '127.0.0.1', '-p', str(port), '-k', str(self.socket_dir)]), '-w', 'start'], timeout=30)
        pid = int((self.cluster / 'postmaster.pid').read_text().splitlines()[0])
        self.manifest.update(postmaster_pid=pid, port_loopback_only=True)
        self.save()
        base = dict(host='127.0.0.1', hostaddr='127.0.0.1', port=port, user='fixture_owner',
                    password=password, sslmode='disable', connect_timeout=3)
        with psycopg.connect(make_conninfo(dbname='postgres', **base), autocommit=True) as connection:
            connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(self.manifest['database'])))
        self.initialize(make_conninfo(dbname=self.manifest['database'], **base), port)

    def cleanup(self):
        if not self.output.exists():
            return
        retained = []
        if self.cluster.exists():
            marker = self.cluster / 'radhouse-fixture-id'
            owned = (marker.is_file() and marker.read_text() == self.run_id
                     and self.cluster.resolve() == self.output.resolve() / 'data'
                     and self.cluster.stat().st_uid == os.getuid()
                     and not stat.S_IMODE(self.cluster.stat().st_mode) & 0o077)
            if not owned:
                retained.append('cluster: ownership mismatch')
            else:
                try:
                    if (self.cluster / 'postmaster.pid').exists():
                        stopped = subprocess.run([str(self.bin / 'pg_ctl'), '-D', str(self.cluster), '-w', '-m', 'fast', 'stop'], capture_output=True, timeout=30)
                        if stopped.returncode != 0:
                            raise FixtureError('cluster stop failed')
                    if (self.cluster / 'postmaster.pid').exists():
                        raise FixtureError('cluster stop unconfirmed')
                    shutil.rmtree(self.cluster)
                except (FixtureError, OSError, subprocess.TimeoutExpired):
                    retained.append('cluster: stop unconfirmed')
        for name in ('postgres.log', 'target.sqlite3', 'target.sqlite3-wal', 'target.sqlite3-shm', 'target.sqlite3-journal'):
            (self.output / name).unlink(missing_ok=True)
        self.manifest.update(cleanup='residual resources' if retained else 'complete', residual_resources=retained)
        self.save()
        if retained:
            print('RESIDUAL: ' + '; '.join(retained))


if __name__ == '__main__':
    raise SystemExit(main(NativeRun))
