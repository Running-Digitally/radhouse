"""Metadata and identifiers are checked without releasing matched values."""
import importlib.util
import gzip
import json
from pathlib import Path
import struct
import subprocess
import zlib

import pytest


spec = importlib.util.spec_from_file_location("public_privacy", Path(__file__).resolve().parents[1] / "scripts/public_privacy.py")
privacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(privacy)


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def test_png_metadata_is_removed_without_changing_image_bytes(tmp_path):
    path = tmp_path / "render.png"
    raw = privacy.PNG + chunk(b"IHDR", b"image-header") + chunk(b"tEXt", b"File\0/Users/" + b"private-owner/build/source.blend") \
        + chunk(b"IDAT", b"unchanged-image-bytes") + chunk(b"IEND", b"")
    path.write_bytes(raw)
    assert privacy.inspect_bytes(raw, ".png")[0]["category"] == "personal_path"
    privacy.strip_png_text(path)
    original_pixels = [data for kind, data, _ in privacy.png_chunks(raw) if kind == b"IDAT"]
    new_pixels = [data for kind, data, _ in privacy.png_chunks(path.read_bytes()) if kind == b"IDAT"]
    assert original_pixels == new_pixels
    assert privacy.inspect_bytes(path.read_bytes(), ".png") == []


@pytest.mark.parametrize("kind,data", [
    (b"zTXt", b"File\0\0" + zlib.compress(b"/Users/" + b"private-owner/source")),
    (b"iTXt", b"File\0\1\0\0\0" + zlib.compress(b"/Users/" + b"private-owner/source")),
])
def test_compressed_png_metadata_is_inspected(kind, data):
    raw = privacy.PNG + chunk(kind, data) + chunk(b"IEND", b"")
    assert privacy.inspect_bytes(raw, ".png")[0]["category"] == "personal_path"


def test_private_denylist_findings_are_redacted():
    result = privacy.inspect_bytes(b"target=deployment-private.invalid", ".md", ["deployment-private.invalid"])
    assert result == [{"category": "private_identifier", "line": 1}]
    assert "deployment-private" not in json.dumps(result)


def test_scan_includes_new_files_and_excludes_ignored_profile(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".env").write_text("TARGET=deployment-private.invalid\n")
    (tmp_path / "new.md").write_text("deployment-private.invalid\n")
    findings = privacy.scan(tmp_path, ["deployment-private.invalid"])
    assert [result["path"] for result in findings] == ["new.md"]


def test_blender_compressed_metadata_is_inspected():
    from compression import zstd
    raw = zstd.compress(b"BLENDER" + b"\0/Users/" + b"private-owner/build/source.blend\0")
    assert privacy.inspect_bytes(raw, ".blend")[0]["category"] == "personal_path"


def test_png_corruption_cannot_pass_metadata_scan():
    raw = privacy.PNG + chunk(b"tEXt", b"safe")[:-1] + b"\0"
    with pytest.raises(ValueError):
        privacy.inspect_bytes(raw, ".png")


def test_gzip_blender_metadata_is_inspected():
    raw = gzip.compress(b"BLENDER" + b"\0/Users/" + b"private-owner/build/source.blend\0")
    assert privacy.inspect_bytes(raw, ".blend")[0]["category"] == "personal_path"


@pytest.mark.parametrize("raw", [b"\x28\xb5\x2f\xfdinvalid", b"unsupported-compressed-content"])
def test_unscannable_blender_cannot_pass(raw):
    with pytest.raises(ValueError):
        privacy.inspect_bytes(raw, ".blend")


def test_blender_trailing_content_cannot_bypass_the_scan():
    from compression import zstd
    raw = zstd.compress(b"BLENDER") + b"hidden-trailing-content"
    with pytest.raises(ValueError):
        privacy.inspect_bytes(raw, ".blend")


def test_all_blender_frames_include_standalone_personal_directories():
    from compression import zstd
    raw = zstd.compress(b"BLENDER-first-frame") + zstd.compress(b"\0/Users/" + b"private-owner\0")
    assert privacy.inspect_bytes(raw, ".blend")[0]["category"] == "personal_path"
