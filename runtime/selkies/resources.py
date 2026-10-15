"""Container working-memory signal for the owned review browser."""
from pathlib import Path


def pressure(cgroup=None):
    """Exclude reclaimable file cache; notify before a hard cgroup OOM.

    Chromium's host memory signal need not reflect its smaller container limit.
    This is a reclamation hint, not a network or download limit. Standalone
    non-cgroup installations retain Chromium's ordinary memory handling.
    """
    try:
        if cgroup is None:
            cgroup = Path('/sys/fs/cgroup')
            # systemd services see the host's cgroup root, unlike containers.
            entries = Path('/proc/self/cgroup').read_text().splitlines()
            unified = next((line[3:] for line in entries if line.startswith('0::')), '/')
            relative = Path(unified.lstrip('/'))
            if '..' not in relative.parts and (cgroup/relative/'memory.max').is_file():
                cgroup = cgroup/relative
        limit = int((cgroup/'memory.max').read_text())
        current = int((cgroup/'memory.current').read_text())
        stats = dict(line.split() for line in (cgroup/'memory.stat').read_text().splitlines())
        working = max(0, current-int(stats['inactive_file']))
        return limit > 0 and working > min(1024**3, limit//4)
    except (OSError, ValueError, KeyError):
        return False
