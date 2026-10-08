"""Exact rebased predecessor contracts for the pinned Hermes source closure.

No fuzzy patching: both source states have whole-file SHA256 pins. A new output
contains the same eight deployed narrowing/durability contracts, deliberately
rebased onto v0.21.6 while retaining its upstream fixes.
"""

import ast
import hashlib
import json
from pathlib import Path

PACKAGE = Path(__file__).parent
MANIFEST_SHA256 = "87f72154111b25d6b1c9b42a9d1663c143707b203063cb9ec582334fda4c0af6"
PATCH_SHA256 = "2cad258a83e082aa95d4e5919e105d8f0901d6779f54bb2750e47ae81d26dbb8"


def render(root):
    root = Path(root)
    manifest = (PACKAGE / "base-runtime-manifest.json").read_bytes()
    if hashlib.sha256(manifest).hexdigest() != MANIFEST_SHA256:
        raise ValueError("hermes_base_manifest_changed")
    pins = json.loads(manifest)
    patch = (PACKAGE / "base-runtime.patch").read_bytes()
    if hashlib.sha256(patch).hexdigest() != PATCH_SHA256:
        raise ValueError("hermes_base_patch_changed")
    raw = {
        name: (root / name).read_bytes() if (root / name).exists() else None
        for name in pins
    }
    digest = lambda data: hashlib.sha256(data).hexdigest() if data is not None else None
    before = all(
        digest(raw[name]) == pin["before_sha256"] for name, pin in pins.items()
    )
    after = all(digest(raw[name]) == pin["after_sha256"] for name, pin in pins.items())
    if not before and not after:
        raise ValueError("hermes_base_source_mismatch")
    result = {name: (value or b"").decode() for name, value in raw.items()}
    if before:
        current, lines = None, []

        def apply():
            if current is None or not lines:
                return
            old = "".join(line[1:] for line in lines if line[:1] in {" ", "-"})
            new = "".join(line[1:] for line in lines if line[:1] in {" ", "+"})
            if old:
                if result[current].count(old) != 1:
                    raise ValueError("hermes_base_context_mismatch")
                result[current] = result[current].replace(old, new, 1)
            elif result[current]:
                raise ValueError("hermes_base_context_mismatch")
            else:
                result[current] = new

        for line in patch.decode().splitlines(keepends=True):
            if line.startswith("--- "):
                apply()
                current = line[6:].strip() if line.startswith("--- a/") else None
                lines = []
                if current is not None and current not in pins:
                    raise ValueError("hermes_base_scope_mismatch")
            elif line.startswith("+++ b/"):
                name = line[6:].strip()
                if name not in pins or current is not None and name != current:
                    raise ValueError("hermes_base_scope_mismatch")
                current = name
            elif line.startswith("@@"):
                apply()
                lines = []
            elif line[:1] in {" ", "+", "-"}:
                lines.append(line)
        apply()
    for name, value in result.items():
        if hashlib.sha256(value.encode()).hexdigest() != pins[name]["after_sha256"]:
            raise ValueError("hermes_base_output_mismatch")
        ast.parse(value)
    return result
