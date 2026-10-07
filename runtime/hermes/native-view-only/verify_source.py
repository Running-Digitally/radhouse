"""Verify the exact upstream or patched source without network access or edits."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--patched", action="store_true")
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    lock = json.loads((directory / "source-lock.json").read_text())
    expected_phase = "after_sha256" if args.patched else "before_sha256"
    patch = directory.parent / "native-view-only.patch"
    if digest(patch) != lock["patch_sha256"]:
        raise SystemExit("native patch checksum mismatch")
    checks = {path: values[expected_phase] for path, values in lock["files"].items()}
    checks.update({"cli/Cargo.lock": lock["cargo_lock_sha256"],
                   "cli/Cargo.toml": lock["cargo_toml_sha256"]})
    for relative, expected in checks.items():
        path = args.root / relative
        if not path.is_file() or digest(path) != expected:
            raise SystemExit(f"native source checksum mismatch: {relative}")
    print(f"Verified {len(checks)} native source files and patch ({expected_phase}).")


if __name__ == "__main__":
    main()
