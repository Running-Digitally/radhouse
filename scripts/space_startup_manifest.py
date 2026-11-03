"""Reconcile a reviewed browser release with its complete next-start source pins.

The approval JSON supplies the exact old manifest hash and before/after digests.
This never learns or accepts arbitrary live drift. Run after staging the reviewed
sources and before declaring the release healthy; retain the emitted backup.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat


def digest(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('regular_source_required')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reconcile(root, approval, *, apply=False):
    root = Path(root)
    path = root / 'startup-manifest.json'
    if digest(path) != approval['manifest_sha256']:
        raise ValueError('manifest_changed')
    original = path.read_bytes()
    manifest = json.loads(original)
    for name, pins in approval['files'].items():
        if Path(name).name != name or name in {'.', '..', 'startup-manifest.json'}:
            raise ValueError('invalid_source_name')
        if manifest['sources'].get(name) != pins['before'] or digest(root / name) != pins['after']:
            raise ValueError('reviewed_source_mismatch')
        manifest['sources'][name] = pins['after']
    for name, expected in manifest['sources'].items():
        if Path(name).name != name or digest(root / name) != expected:
            raise ValueError('startup_source_changed')
    for name, expected in manifest.get('external_sources', {}).items():
        if not Path(name).is_absolute() or digest(Path(name)) != expected:
            raise ValueError('recovery_dependency_changed')
    result = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    if apply:
        backup = path.with_name('startup-manifest.before-' + approval['manifest_sha256'] + '.json')
        with backup.open('xb') as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        temporary = path.with_suffix('.release-new')
        with temporary.open('xb') as stream:
            os.fchmod(stream.fileno(), stat.S_IMODE(path.stat().st_mode))
            stream.write(result)
            stream.flush()
            os.fsync(stream.fileno())
        # Refuse a concurrent release instead of overwriting its manifest.
        if digest(path) != approval['manifest_sha256']:
            raise ValueError('manifest_changed')
        temporary.replace(path)
        descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return {'sha256': hashlib.sha256(result).hexdigest(), 'source_count': len(manifest['sources']),
            'applied': apply}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('approval', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(reconcile(args.root, json.loads(args.approval.read_text()), apply=args.apply)))


if __name__ == '__main__':
    main()
