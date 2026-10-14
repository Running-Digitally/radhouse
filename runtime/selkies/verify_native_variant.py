"""Check the private native variant after the ordinary boundary source gate."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--patched', action='store_true')
    args = parser.parse_args()
    here = Path(__file__).parent
    lock = json.loads((here/'native-page-only-lock.json').read_text())
    if digest(here/'native-page-only.patch') != lock['variant_patch_sha256']:
        raise SystemExit('native_variant_patch_mismatch')
    if digest(here.parent/'hermes/native-view-only.patch') != lock['base_boundary_patch_sha256']:
        raise SystemExit('native_boundary_patch_mismatch')
    field = 'after_sha256' if args.patched else 'before_sha256'
    for name, values in lock['files'].items():
        if digest(args.source/name) != values[field]:
            raise SystemExit('native_variant_source_mismatch:'+name)
    if digest(args.source/'cli/Cargo.lock') != lock['cargo_lock_sha256']:
        raise SystemExit('native_variant_cargo_lock_mismatch')
    if digest(args.source/'cli/Cargo.toml') != lock['cargo_toml_sha256']:
        raise SystemExit('native_variant_cargo_manifest_mismatch')
    print('Verified private native variant source and patch.')


if __name__ == '__main__':
    main()
