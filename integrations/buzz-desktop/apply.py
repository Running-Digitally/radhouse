#!/usr/bin/env python3
"""Check or apply this maintained patch to an exact, clean Buzz source checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    package = Path(__file__).resolve().parent
    manifest = json.loads((package / "manifest.json").read_text())
    patch = package / manifest["patch"]
    if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest["patch_sha256"]:
        raise SystemExit("Patch digest mismatch; stopped.")
    def git(*arguments):
        return subprocess.check_output(["git", "-C", str(args.checkout), *arguments], text=True).strip()
    if git("rev-parse", "HEAD") != manifest["upstream_commit"]:
        raise SystemExit("Upstream commit mismatch; stopped.")
    if git("status", "--porcelain"):
        raise SystemExit("Checkout has changes; stopped.")
    git("apply", "--check", str(patch))
    if args.apply:
        git("apply", str(patch))
    print(json.dumps({"result": "applied" if args.apply else "checked",
                      "upstream_commit": manifest["upstream_commit"],
                      "patch_sha256": manifest["patch_sha256"]}))


if __name__ == "__main__":
    main()
