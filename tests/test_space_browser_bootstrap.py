"""Recovery requires process-death evidence and never adopts stale browser grants."""
import importlib.util
import os
from pathlib import Path
import sqlite3

import pytest

spec = importlib.util.spec_from_file_location('space_bootstrap_test',
    Path(__file__).parents[1] / 'runtime/selkies/space_bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def test_dedicated_cgroup_refuses_surviving_browser_process(tmp_path):
    proc, groups = tmp_path / 'proc', tmp_path / 'groups'
    (proc / 'self').mkdir(parents=True)
    (proc / 'self/cgroup').write_text('0::' + bootstrap.CGROUP + '\n')
    (proc / str(os.getpid())).mkdir()
    (proc / str(os.getpid()) / 'status').write_text('PPid:\t1\n')
    group = groups / bootstrap.CGROUP.lstrip('/')
    group.mkdir(parents=True)
    (group / 'cgroup.procs').write_text(str(os.getpid()) + '\n987654\n')
    with pytest.raises(RuntimeError, match='previous_browser_processes_remain'):
        bootstrap.verify_empty_service(proc, groups)
    (group / 'cgroup.procs').write_text(str(os.getpid()) + '\n')
    bootstrap.verify_empty_service(proc, groups)
    (group / 'child').mkdir()
    with pytest.raises(RuntimeError, match='browser_child_cgroup_unconfirmed'):
        bootstrap.verify_empty_service(proc, groups)


def test_recovery_retires_old_identity_and_removes_only_ephemeral_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, 'UID', os.getuid())
    path = tmp_path / 'launches.sqlite3'
    identity = 'a' * 32
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE launches (id TEXT PRIMARY KEY, state TEXT NOT NULL)')
        connection.execute('INSERT INTO launches VALUES (?, ?)', (identity, 'running'))
    path.chmod(0o600)
    (tmp_path / identity).mkdir(mode=0o700)
    (tmp_path / identity / 'synthetic-cookie').write_text('synthetic')
    unrelated = tmp_path / 'unrelated'
    unrelated.write_text('keep')
    bootstrap.reconcile(tmp_path)
    assert not (tmp_path / identity).exists() and unrelated.read_text() == 'keep'
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT state FROM launches').fetchone() == ('retired',)


def test_recovery_refuses_symlink_and_preserves_unresolved_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, 'UID', os.getuid())
    state = tmp_path / 'state'; state.mkdir()
    target = tmp_path / 'retained'; target.mkdir()
    identity = 'b' * 32
    with sqlite3.connect(state / 'launches.sqlite3') as connection:
        connection.execute('CREATE TABLE launches (id TEXT PRIMARY KEY, state TEXT NOT NULL)')
        connection.execute('INSERT INTO launches VALUES (?, ?)', (identity, 'running'))
    (state / 'launches.sqlite3').chmod(0o600)
    (state / identity).symlink_to(target)
    with pytest.raises(RuntimeError, match='private_browser_generation_required'):
        bootstrap.reconcile(state)
    assert target.is_dir()
    with sqlite3.connect(state / 'launches.sqlite3') as connection:
        assert connection.execute('SELECT state FROM launches').fetchone() == ('running',)
