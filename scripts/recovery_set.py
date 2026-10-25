#!/usr/bin/env python3
"""Seal/verify quiesced component exports; never import over a running service.

Native state is exported/imported by Hermes. This tool packages the remaining
contract, records exclusions and checks every byte before isolated extraction.
Plans and outputs are private operator files, never HTTP or model input.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile

ROLES = {"hermes", "chat", "originals", "authentication", "configuration", "workspace", "runtime"}
SCHEMA = "radhouse.recovery-set.v1"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def regular(path):
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("regular_file_required")


def private(path, directory=False):
    info = path.lstat()
    if (path.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077
            or (not stat.S_ISDIR(info.st_mode) if directory else not stat.S_ISREG(info.st_mode))):
        raise ValueError("private_custody_required")


def safe(name):
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and str(path) == name


def write_json(path, value):
    with open(path, "x", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def seal(plan, output):
    if (plan.get("schema") != SCHEMA or plan.get("writers_stopped") is not True
            or set(plan.get("sources", {})) != ROLES
            or not plan.get("exclusions") or not plan.get("native_export_complete") is True
            or any(not re.fullmatch(r"[a-f0-9]{40}", plan.get(k, "")) for k in ("hermes_commit", "web_commit"))):
        raise ValueError("incomplete_recovery_plan")
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    private(output, directory=True)
    manifest = {key: plan[key] for key in ("schema", "writers_stopped", "native_export_complete",
                "hermes_commit", "web_commit", "exclusions")}
    manifest["components"] = {}
    # An incomplete directory has no manifest and must never be advertised as
    # restorable. The caller retains it for diagnosis; it cannot be overwritten.
    for role, source_name in sorted(plan["sources"].items()):
        source = Path(source_name)
        if not source.is_absolute() or source.is_symlink():
            raise ValueError("invalid_source")
        target = output / (role + (".tar.gz" if source.is_dir() else ".payload"))
        if source.is_dir():
            with tarfile.open(target, "x:gz", dereference=False) as archive:
                def accept(member):
                    if not (member.isfile() or member.isdir()) or not safe(member.name):
                        raise ValueError("source_link_or_special_file")
                    member.uid = member.gid = 0
                    member.uname = member.gname = ""
                    # Keep runnable workspace tools runnable, without restoring
                    # group/other access or privileged setuid/setgid bits.
                    member.mode = 0o700 if member.isdir() else 0o600 | (member.mode & 0o100)
                    return member
                archive.add(source, arcname=role, filter=accept)
            kind = "tree"
        else:
            regular(source)
            shutil.copyfile(source, target, follow_symlinks=False)
            kind = "file"
        os.chmod(target, 0o600)
        with target.open("rb") as stream:
            os.fsync(stream.fileno())
        manifest["components"][role] = {"file": target.name, "kind": kind,
            "size": target.stat().st_size, "sha256": digest(target)}
    write_json(output / "manifest.json", manifest)
    dfd = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
    return verify(output)


def verify(directory, *, expected_manifest=None, expected_hermes=None, expected_web=None):
    private(directory, directory=True)
    private(directory / "manifest.json")
    if expected_manifest is not None and digest(directory / "manifest.json") != expected_manifest:
        raise ValueError("recovery_manifest_identity_mismatch")
    manifest = json.loads((directory / "manifest.json").read_text())
    if (manifest.get("schema") != SCHEMA or set(manifest.get("components", {})) != ROLES
            or manifest.get("writers_stopped") is not True or manifest.get("native_export_complete") is not True
            or not manifest.get("exclusions")
            or any(not re.fullmatch(r"[a-f0-9]{40}", manifest.get(k, "")) for k in ("hermes_commit", "web_commit"))):
        raise ValueError("invalid_recovery_manifest")
    if ((expected_hermes is not None and manifest["hermes_commit"] != expected_hermes)
            or (expected_web is not None and manifest["web_commit"] != expected_web)):
        raise ValueError("recovery_source_incompatible")
    expected = {"manifest.json"}
    for role, item in manifest["components"].items():
        if item.get("kind") not in {"file", "tree"}:
            raise ValueError("invalid_component_kind")
        name = role + (".tar.gz" if item["kind"] == "tree" else ".payload")
        if item.get("file") != name:
            raise ValueError("invalid_component_name")
        expected.add(name)
        path = directory / name
        private(path)
        if path.stat().st_size != item["size"] or digest(path) != item["sha256"]:
            raise ValueError("component_digest_mismatch")
        if item["kind"] == "tree":
            with tarfile.open(path, "r:gz") as archive:
                seen = set()
                for member in archive:
                    if (not safe(member.name) or member.name.split("/")[0] != role
                            or not (member.isfile() or member.isdir()) or member.name in seen):
                        raise ValueError("unsafe_component_member")
                    seen.add(member.name)
    if {p.name for p in directory.iterdir()} != expected:
        raise ValueError("unexpected_recovery_payload")
    return manifest


def extract(directory, output, *, expected_manifest, expected_hermes, expected_web):
    if any(not value for value in (expected_manifest, expected_hermes, expected_web)):
        raise ValueError("trusted_restore_identity_required")
    manifest = verify(directory, expected_manifest=expected_manifest,
                      expected_hermes=expected_hermes, expected_web=expected_web)
    # Deliberately no --force or live destination support.
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    for role, item in manifest["components"].items():
        source = directory / item["file"]
        if item["kind"] == "tree":
            with tarfile.open(source, "r:gz") as archive:
                archive.extractall(output, filter="data")
        else:
            shutil.copyfile(source, output / (role + ".payload"))
            os.chmod(output / (role + ".payload"), 0o600)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seal", "verify", "extract"))
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-manifest")
    parser.add_argument("--expected-hermes")
    parser.add_argument("--expected-web")
    args = parser.parse_args()
    if args.action != "verify" and args.output is None:
        parser.error("--output required")
    os.umask(0o077)
    if args.action == "seal":
        private(args.source)
        result = seal(json.loads(args.source.read_text()), args.output)
    elif args.action == "extract":
        result = extract(args.source, args.output, expected_manifest=args.expected_manifest,
                         expected_hermes=args.expected_hermes, expected_web=args.expected_web)
    else:
        result = verify(args.source, expected_manifest=args.expected_manifest,
                        expected_hermes=args.expected_hermes, expected_web=args.expected_web)
    print(json.dumps({"state": "verified", "components": sorted(result["components"]),
                      "manifest_sha256": digest((args.output if args.action == "seal" else args.source) / "manifest.json")}))


if __name__ == "__main__":
    main()
