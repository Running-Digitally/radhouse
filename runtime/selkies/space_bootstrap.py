"""Fixed systemd bootstrap for the browser-only SPACE guest.

The unit must use KillMode=control-group and a dedicated cgroup. On restart,
prove that this bootstrap and its ancestors are the only remaining members
before reconciling old browser launch records. No general command interface.
"""
import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess

ROOT = Path('/opt/radhouse-browser-root')
CGROUP = '/system.slice/radhouse-space-browser.service'
UID = 1000


def verify_empty_service(proc=Path('/proc'), cgroups=Path('/sys/fs/cgroup')):
    own = (proc / 'self/cgroup').read_text().splitlines()
    if own != ['0::' + CGROUP]:
        raise RuntimeError('dedicated_browser_cgroup_required')
    ancestors, current = set(), os.getpid()
    for _ in range(32):
        if current <= 1:
            break
        ancestors.add(current)
        status = dict(line.split(':', 1) for line in (proc / str(current) / 'status').read_text().splitlines() if ':' in line)
        current = int(status['PPid'])
    else:
        raise RuntimeError('browser_ancestry_unconfirmed')
    group = cgroups / CGROUP.lstrip('/')
    if any(path.is_dir() for path in group.iterdir()):
        raise RuntimeError('browser_child_cgroup_unconfirmed')
    members = {int(value) for value in (group / 'cgroup.procs').read_text().split()}
    if os.getpid() not in members or not members <= ancestors:
        raise RuntimeError('previous_browser_processes_remain')


def reconcile(state):
    database = state / 'launches.sqlite3'
    if not database.exists():
        return
    info = database.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != UID or info.st_mode & 0o077:
        raise RuntimeError('private_browser_database_required')
    with sqlite3.connect(database) as connection:
        rows = connection.execute('SELECT id, state FROM launches').fetchall()
        for identity, _ in rows:
            if re.fullmatch(r'[a-f0-9]{32}', identity) is None:
                raise RuntimeError('browser_identity_unconfirmed')
            directory = state / identity
            if directory.exists() or directory.is_symlink():
                info = directory.lstat()
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != UID:
                    raise RuntimeError('private_browser_generation_required')
                shutil.rmtree(directory)
        connection.execute("UPDATE launches SET state='retired' WHERE state!='retired'")
    # Counts only: no URLs, credentials, input or profile content in the journal.
    print(json.dumps({'browser_startup_reconciled': True,
                      'retired_launches': sum(value != 'retired' for _, value in rows)}), flush=True)


def main():
    if os.geteuid() != 0 or os.uname().machine != 'x86_64':
        raise RuntimeError('guest_bootstrap_platform_required')
    os.umask(0o077)
    verify_empty_service()
    reconcile(ROOT / 'state/browser')
    subprocess.run(['mount', '--make-rprivate', '/'], check=True)
    subprocess.run(['mount', '--bind', str(ROOT), str(ROOT)], check=True)
    for name in ('proc', 'dev', 'sys'):
        (ROOT / name).mkdir(exist_ok=True)
    subprocess.run(['mount', '-t', 'proc', 'proc', str(ROOT / 'proc')], check=True)
    subprocess.run(['mount', '--rbind', '/dev', str(ROOT / 'dev')], check=True)
    subprocess.run(['mount', '--make-rslave', str(ROOT / 'dev')], check=True)
    subprocess.run(['mount', '-t', 'sysfs', '-o', 'ro', 'sysfs', str(ROOT / 'sys')], check=True)
    os.chdir(ROOT)
    Path('.oldroot').mkdir(exist_ok=True)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.syscall(155, ctypes.c_char_p(b'.'), ctypes.c_char_p(b'.oldroot')) != 0:
        raise OSError(ctypes.get_errno(), 'browser_pivot_failed')
    os.chdir('/')
    if libc.umount2(ctypes.c_char_p(b'/.oldroot'), 2) != 0:
        raise OSError(ctypes.get_errno(), 'browser_oldroot_detach_failed')
    os.rmdir('/.oldroot')
    os.setgroups([]); os.setgid(UID); os.setuid(UID)
    os.chdir('/opt/candidate')
    os.execv('/usr/local/bin/python', ['python', '-P', 'runtime/selkies/space_guest.py',
        '--state', '/state/browser', '--proxy', os.environ['RADHOUSE_PUBLIC_PROXY'],
        '--credential-file', '/state/browser-credential'])


if __name__ == '__main__':
    main()
