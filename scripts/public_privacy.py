#!/usr/bin/env python3
"""Inspect publishable source and asset metadata without printing matched values."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import zlib


PERSONAL_PATH = re.compile(
    rb"/(?:Users/[A-Za-z0-9_.-]+|home/(?!radhouse(?:bot)?(?:[/\x00\s\"']|$))[A-Za-z0-9_.-]+)"
    rb"(?=[/\x00\s\"']|$)")
SECRET = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|"
                    rb"(?:ghp_|github_pat_|sk_live_|sk-proj-)[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}")
PNG = b"\x89PNG\r\n\x1a\n"
TEXT_CHUNKS = {b"tEXt", b"zTXt", b"iTXt"}
MAX_FILE = 64 * 1024 * 1024


def png_chunks(raw):
    if not raw.startswith(PNG):
        raise ValueError("invalid_png")
    offset = len(PNG)
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise ValueError("invalid_png")
        length = struct.unpack(">I", raw[offset:offset + 4])[0]
        end = offset + 12 + length
        if end > len(raw):
            raise ValueError("invalid_png")
        kind, data = raw[offset + 4:offset + 8], raw[offset + 8:end - 4]
        if zlib.crc32(kind + data) != struct.unpack(">I", raw[end - 4:end])[0]:
            raise ValueError("invalid_png_crc")
        yield kind, data, raw[offset:end]
        offset = end
        if kind == b"IEND":
            if offset != len(raw):
                raise ValueError("invalid_png_trailing_data")
            return
    raise ValueError("missing_png_end")


def _inflate(raw, wbits=zlib.MAX_WBITS):
    decoder = zlib.decompressobj(wbits)
    result = decoder.decompress(raw, MAX_FILE + 1)
    if len(result) > MAX_FILE or not decoder.eof or decoder.unused_data:
        raise ValueError("metadata_decompression_invalid")
    return result


def metadata(raw, suffix):
    if raw.startswith(PNG):
        parts = []
        for kind, data, _ in png_chunks(raw):
            if kind == b"tEXt" or kind == b"eXIf":
                parts.append(data)
            elif kind == b"zTXt":
                keyword, body = data.split(b"\0", 1)
                if body[:1] != b"\0":
                    raise ValueError("invalid_png_text")
                parts.append(keyword + b"\0" + _inflate(body[1:]))
            elif kind == b"iTXt":
                keyword, body = data.split(b"\0", 1)
                if len(body) < 2 or body[0] not in (0, 1) or body[1] != 0:
                    raise ValueError("invalid_png_text")
                _, _, text = body[2:].split(b"\0", 2)
                parts.append(keyword + b"\0" + (_inflate(text) if body[0] else text))
        return b"\n".join(parts)
    if suffix == ".blend" and raw.startswith(b"\x28\xb5\x2f\xfd"):
        try:
            from compression import zstd
        except ImportError:
            raise ValueError("blender_scan_requires_python314") from None
        parts, size, remaining = [], 0, raw
        while remaining:
            decoder = zstd.ZstdDecompressor()
            try:
                part = decoder.decompress(remaining, MAX_FILE - size + 1)
            except zstd.ZstdError:
                raise ValueError("blender_decompression_invalid") from None
            size += len(part)
            if size > MAX_FILE or not decoder.eof or decoder.unused_data == remaining:
                raise ValueError("blender_decompression_invalid")
            parts.append(part)
            remaining = decoder.unused_data
        return b"".join(parts)
    if suffix == ".blend" and raw.startswith(b"\x1f\x8b"):
        return _inflate(raw, 31)
    if suffix == ".blend" and not raw.startswith(b"BLENDER"):
        raise ValueError("unknown_blender_format")
    return raw


def inspect_bytes(raw, suffix, deny_literals=()):
    content = metadata(raw, suffix)
    findings = []
    for category, pattern in (("personal_path", PERSONAL_PATH), ("credential_signature", SECRET)):
        for match in pattern.finditer(content):
            findings.append({"category": category, "line": content[:match.start()].count(b"\n") + 1})
    folded = content.lower()
    for value in deny_literals:
        needle = value.encode("utf-8").lower()
        if needle and needle in folded:
            findings.append({"category": "private_identifier", "line": folded[:folded.index(needle)].count(b"\n") + 1})
    return findings


def scan(root, deny_literals=()):
    names = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    findings = []
    for name in sorted(set(names.decode("utf-8").split("\0")) - {""}):
        path = root / name
        if path.is_symlink() or not path.is_file():
            findings.append({"path": name, "category": "unscannable_entry"})
            continue
        if path.stat().st_size > MAX_FILE:
            findings.append({"path": name, "category": "file_exceeds_scan_budget"})
            continue
        try:
            findings.extend({"path": name, **result} for result in inspect_bytes(path.read_bytes(), path.suffix, deny_literals))
        except (ValueError, zlib.error, OSError):
            findings.append({"path": name, "category": "metadata_scan_failed"})
    return findings


def strip_png_text(path):
    """Remove textual PNG export metadata; preserve every image-data byte."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("invalid_png_source")
    chunks = list(png_chunks(path.read_bytes()))
    path.write_bytes(PNG + b"".join(chunk for kind, _, chunk in chunks if kind not in TEXT_CHUNKS))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path.cwd())
    parser.add_argument("--private-policy", type=Path, help="Private JSON containing deny_literals; never committed")
    parser.add_argument("--strip-png-text", type=Path, help="Explicit metadata-only sanitation of one PNG")
    args = parser.parse_args(argv)
    try:
        if args.strip_png_text:
            strip_png_text(args.strip_png_text)
            print(json.dumps({"state": "png_text_removed", "pixels_changed": False}))
            return 0
        policy = json.loads(args.private_policy.read_text()) if args.private_policy else {}
        if type(policy) is not dict:
            raise ValueError("invalid_private_policy")
        values = policy.get("deny_literals", [])
        if type(values) is not list or any(type(value) is not str or not value for value in values):
            raise ValueError("invalid_private_policy")
        findings = scan(args.source.resolve(), values)
        print(json.dumps({"state": "findings" if findings else "passed", "findings": findings,
                          "scope": "working_tree_text_and_png_blender_metadata"}, indent=2))
        return 1 if findings else 0
    except (ValueError, OSError, subprocess.SubprocessError):
        print(json.dumps({"state": "failed", "error": "privacy_scan_unavailable"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
