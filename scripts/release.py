#!/usr/bin/env python3
"""Portable source packets and an attended, private, static-web release lane."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import http.client
import io
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import ssl
import stat
import subprocess
import sys
import tarfile
import time
from urllib.parse import urlsplit

SCHEMA = "radhouse.release.v1"
STATIC = "src/radhouse/chat/static/"
UNIT = "radhouse-api.service"
MAX_FILE = 16 * 1024 * 1024
MAX_PACKET = 128 * 1024 * 1024
TERMINAL = ("completed", "failed", "cancelled", "interrupted")
HEX40 = re.compile(r"[a-f0-9]{40}")
HEX64 = re.compile(r"[a-f0-9]{64}")
PROFILE_KEYS = frozenset({
    "RADHOUSE_RELEASE_ROOT", "RADHOUSE_EVIDENCE_ROOT", "RADHOUSE_API_UNIT_FILE",
    "RADHOUSE_BASELINE_REVISION", "RADHOUSE_API_UNIT_SHA256", "RADHOUSE_MACHINE_ID_FILE",
    "RADHOUSE_MACHINE_ID_SHA256", "RADHOUSE_SERVICE_USER", "RADHOUSE_SERVICE_GROUP",
    "RADHOUSE_SERVICE_UID", "RADHOUSE_SQLITE_FILE", "RADHOUSE_SQLITE_SCHEMA_SHA256",
    "RADHOUSE_ORIGINALS_DIR", "RADHOUSE_HTTPS_ORIGIN", "RADHOUSE_TLS_CA_FILE",
    "RADHOUSE_CONTROLS_FILE", "RADHOUSE_CONTROLS_SHA256", "RADHOUSE_PRIVATE_IDENTIFIERS_FILE",
    "RADHOUSE_RETAINED_FILES_FILE", "RADHOUSE_RETAINED_FILES_SHA256",
})
REQUIRED = PROFILE_KEYS - {"RADHOUSE_PRIVATE_IDENTIFIERS_FILE", "RADHOUSE_RETAINED_FILES_FILE", "RADHOUSE_RETAINED_FILES_SHA256"}


class Refusal(ValueError):
    """A fixed label safe to print; never include private settings or exception text."""


class Retryable(Refusal):
    """A diagnosed service or HTTPS failure; explicit bounded retry is permitted."""


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def utcnow():
    return datetime.now(timezone.utc)


def safe_name(name):
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and ".." not in p.parts and str(p) == name


def ancestors(path):
    """Never follow a link in configuration, artifact, release or evidence paths."""
    path = Path(os.path.abspath(path))
    for p in reversed(path.parents):
        if p.is_symlink() or not p.is_dir():
            raise Refusal("path_ancestor_custody_failed")
    return path


def read_file(path, *, private=False, owner=None, maximum=MAX_FILE):
    path = ancestors(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or owner is not None and before.st_uid != owner
                or before.st_mode & 0o022 or private and stat.S_IMODE(before.st_mode) != 0o600):
            raise Refusal("file_custody_failed")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    current = path.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if len(raw) > maximum or identity(before) != identity(after) or identity(before) != identity(current):
        raise Refusal("file_changed_or_too_large")
    return raw


def atomic(path, raw, mode=0o600):
    path = ancestors(path)
    temporary = path.with_name(".release-" + os.urandom(12).hex())
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists() or path.is_symlink():
            read_file(path, maximum=MAX_PACKET)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def private_directory(path):
    path = ancestors(path)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise Refusal("private_directory_required")
    return path


def git(source, *args):
    result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(source), *args],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30)
    if result.returncode or len(result.stdout) > MAX_PACKET:
        raise Refusal("git_source_verification_failed")
    return result.stdout


def exact_source(source, revision, baseline):
    if not HEX40.fullmatch(revision) or not HEX40.fullmatch(baseline) or revision == baseline:
        raise Refusal("exact_distinct_source_and_baseline_required")
    if git(source, "rev-parse", "HEAD").decode().strip() != revision:
        raise Refusal("source_head_mismatch")
    if git(source, "status", "--porcelain", "--untracked-files=normal").strip():
        raise Refusal("source_checkout_must_be_clean")
    git(source, "merge-base", "--is-ancestor", baseline, revision)


def source_files(source, revision):
    files = {}
    for entry in git(source, "ls-tree", "-rz", revision, "--", "src/radhouse/").split(b"\0"):
        if not entry:
            continue
        declaration, raw_name = entry.split(b"\t", 1)
        mode, kind, _ = declaration.split()
        name = raw_name.decode()
        if mode not in {b"100644", b"100755"} or kind != b"blob" or not safe_name(name):
            raise Refusal("source_member_refused")
        raw = git(source, "show", revision + ":" + name)
        if len(raw) > MAX_FILE:
            raise Refusal("source_member_too_large")
        files[name] = raw
    if not files:
        raise Refusal("first_party_source_missing")
    return files


def privacy_check(raw, private_identifiers=()):
    """Conservative packaging guard, not a replacement for repository/history audit."""
    if any(item and item.encode() in raw for item in private_identifiers):
        raise Refusal("private_identifier_in_public_source")
    text = raw.decode("utf-8", errors="ignore")
    if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bAKIA[A-Z0-9]{16}\b|\bgh[pousr]_[A-Za-z0-9]{30,}", text):
        raise Refusal("credential_in_public_source")
    if re.search(r"/(?:Users|home)/[A-Za-z][A-Za-z0-9_.-]*/", text):
        raise Refusal("personal_path_in_public_source")
    if re.search(r"(?:https?://|[\"'])[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.(?:lan|internal)[/:\"']", text):
        raise Refusal("private_hostname_in_public_source")
    for match in re.finditer(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", text):
        try:
            address = ipaddress.ip_address(match.group())
        except ValueError:
            continue
        # These standard policy ranges describe Internet address classes, not an installation.
        if any(match.group() == network and text[match.end():].startswith(suffix)
               for network, suffix in (("10.0.0.0", "/8"), ("172.16.0.0", "/12"), ("192.168.0.0", "/16"))):
            continue
        if address.is_private and not address.is_loopback and address not in ipaddress.ip_network("192.0.2.0/24") and address not in ipaddress.ip_network("198.51.100.0/24") and address not in ipaddress.ip_network("203.0.113.0/24"):
            raise Refusal("private_address_in_public_source")


def static_route(name):
    if not name.startswith(STATIC):
        return None
    name = name.removeprefix(STATIC)
    direct = {"chat.js", "chat.css", "format.js", "browser-view.js", "browser-view.css", "navigation.js", "navigation.css", "library.js"}
    workspace = {"about-you.js", "about-you.css", "owner-terminal.js", "owner-terminal.css", "inference-controls.js", "inference-controls.css", "agent-profile.js", "agent-profile.css", "agent-portrait.js"}
    if name == "index.html":
        return "/"
    if name in direct:
        return "/" + name
    if name in workspace or name == "agent-profile/catalog.json":
        return "/workspace-assets/" + name
    if re.fullmatch(r"agent-profile/portraits/[a-z][a-z0-9-]*\.webp", name) or name in {"agent-profile/echo/neutral.png", "agent-profile/echo/a-curious.mp4", "agent-profile/echo/b-thoughtful.mp4", "agent-profile/echo/c-playful.mp4"}:
        return "/workspace-assets/" + name
    if name in {"vendor/xterm/xterm.js", "vendor/xterm/xterm.css", "vendor/xterm/addon-fit.js"}:
        return "/workspace-vendor/xterm/" + name.rsplit("/", 1)[1]
    return None


def plan(source, revision, baseline):
    exact_source(source, revision, baseline)
    changes = git(source, "diff", "--name-only", "-z", baseline, revision).decode().split("\0")
    changes = sorted(name for name in changes if name)
    application = [name for name in changes if name.startswith(("src/", "runtime/", "deploy/", "web/"))
                   or name in {"pyproject.toml", "uv.lock"}]
    supported = bool(application) and all(static_route(name) and not name.startswith(STATIC + "vendor/") for name in application)
    lane = "static-web" if supported else "separate-qualification-required"
    return {"source_revision": revision, "baseline_revision": baseline, "lane": lane,
            "apply_supported": supported, "changed_files": changes,
            "next": "prepare_exact_qualified_packet" if supported else "qualify_application_native_schema_or_dependency_changes_separately",
            "network_calls": 0}


def tar_bytes(files):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, raw in sorted(files.items()):
            item = tarfile.TarInfo(name)
            item.mode, item.uid, item.gid, item.mtime, item.size = 0o644, 0, 0, 0, len(raw)
            archive.addfile(item, io.BytesIO(raw))
    return output.getvalue()


def prepare(source, revision, baseline, qualification, qualification_pin, output, private_identifiers=()):
    result = plan(source, revision, baseline)
    proof_raw = read_file(qualification)
    proof = json.loads(proof_raw)
    if (sha(proof_raw) != qualification_pin or proof.get("source_revision") != revision
            or proof.get("state") != "qualified" or proof.get("lane") != result["lane"]
            or not proof.get("checks") or any(c.get("passed") is not True for c in proof["checks"])):
        raise Refusal("exact_passing_qualification_required")
    # Qualification names are copied; descriptions, logs and local paths stay private.
    for check in proof["checks"]:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", check.get("name", "")):
            raise Refusal("qualification_name_invalid")
    files, before = source_files(source, revision), source_files(source, baseline)
    for raw in files.values():
        privacy_check(raw, private_identifiers)
    payload = tar_bytes(files)
    manifest = {"schema": SCHEMA, **result, "source_tree": git(source, "rev-parse", revision + "^{tree}").decode().strip(),
                "files_sha256": {n: sha(v) for n, v in sorted(files.items())},
                "baseline_files_sha256": {n: sha(v) for n, v in sorted(before.items())},
                "archive_sha256": sha(payload), "helper_sha256": sha(Path(__file__).read_bytes()),
                "qualification_sha256": qualification_pin, "checks": [c["name"] for c in proof["checks"]],
                "native_restart": False, "provider_calls": 0, "database_restore": False, "automatic_rollback": False}
    manifest_raw = encoded(manifest)
    privacy_check(manifest_raw, private_identifiers)
    if output.exists() or output.is_symlink():
        raise Refusal("packet_output_must_be_exclusive")
    ancestors(output)
    output.mkdir(mode=0o700)
    atomic(output / "source.tar", payload)
    atomic(output / "manifest.json", manifest_raw)
    return {"state": "prepared", "lane": result["lane"], "apply_supported": result["apply_supported"],
            "source_revision": revision, "manifest_sha256": sha(manifest_raw), "archive_sha256": sha(payload)}


def load_packet(packet, pin):
    raw = read_file(packet / "manifest.json")
    manifest = json.loads(raw)
    if sha(raw) != pin or manifest.get("schema") != SCHEMA or manifest.get("helper_sha256") != sha(Path(__file__).read_bytes()):
        raise Refusal("exact_manifest_and_helper_required")
    for field in ("source_revision", "baseline_revision"):
        if not HEX40.fullmatch(manifest.get(field, "")):
            raise Refusal("manifest_revision_invalid")
    for field in ("files_sha256", "baseline_files_sha256"):
        mapping = manifest.get(field, {})
        if not mapping or any(not safe_name(n) or not n.startswith("src/radhouse/") or not HEX64.fullmatch(h) for n, h in mapping.items()):
            raise Refusal("manifest_source_scope_invalid")
    raw = read_file(packet / "source.tar", maximum=MAX_PACKET)
    if sha(raw) != manifest.get("archive_sha256"):
        raise Refusal("archive_digest_mismatch")
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for item in archive:
            if (not item.isfile() or not safe_name(item.name) or item.name in files or item.size > MAX_FILE
                    or item.uid or item.gid or item.mode != 0o644 or item.mtime != 0):
                raise Refusal("archive_member_refused")
            files[item.name] = archive.extractfile(item).read()
    if {n: sha(v) for n, v in files.items()} != manifest["files_sha256"]:
        raise Refusal("archive_inventory_mismatch")
    return manifest, files


def load_profile(path):
    raw = read_file(path, private=True, owner=os.getuid())
    profile = {}
    for line in raw.decode().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise Refusal("profile_syntax_invalid")
        key, value = line.split("=", 1)
        if key not in PROFILE_KEYS or key in profile or not value or "REPLACE_" in value or any(c in value for c in "\r\n\0"):
            raise Refusal("profile_key_or_value_invalid")
        profile[key] = value
    if not REQUIRED <= profile.keys():
        raise Refusal("profile_incomplete")
    for key, value in profile.items():
        if key.endswith(("_FILE", "_DIR", "_ROOT")) and (not Path(value).is_absolute() or ".." in Path(value).parts):
            raise Refusal("profile_absolute_paths_required")
        if key.endswith("SHA256") and not HEX64.fullmatch(value):
            raise Refusal("profile_digest_invalid")
    if not HEX40.fullmatch(profile["RADHOUSE_BASELINE_REVISION"]):
        raise Refusal("profile_baseline_invalid")
    if not profile["RADHOUSE_SERVICE_UID"].isdigit() or int(profile["RADHOUSE_SERVICE_UID"]) == 0:
        raise Refusal("unprivileged_service_uid_required")
    for key in ("RADHOUSE_SERVICE_USER", "RADHOUSE_SERVICE_GROUP"):
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", profile[key]):
            raise Refusal("service_identity_invalid")
    if Path(profile["RADHOUSE_API_UNIT_FILE"]).name != UNIT:
        raise Refusal("api_unit_only")
    url = urlsplit(profile["RADHOUSE_HTTPS_ORIGIN"])
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment:
        raise Refusal("https_origin_required")
    roots = [Path(profile[k]) for k in ("RADHOUSE_RELEASE_ROOT", "RADHOUSE_EVIDENCE_ROOT", "RADHOUSE_ORIGINALS_DIR")]
    if any(a == b or a.is_relative_to(b) or b.is_relative_to(a) for i, a in enumerate(roots) for b in roots[i + 1:]):
        raise Refusal("profile_roots_must_be_separate")
    if ("RADHOUSE_RETAINED_FILES_FILE" in profile) != ("RADHOUSE_RETAINED_FILES_SHA256" in profile):
        raise Refusal("retained_files_reference_and_digest_required")
    return profile, sha(raw)


def retained_files(profile):
    """Retain an already-qualified vendor tree; never install or update dependencies."""
    if "RADHOUSE_RETAINED_FILES_FILE" not in profile:
        return {}
    raw = read_file(profile["RADHOUSE_RETAINED_FILES_FILE"], private=True, owner=os.getuid())
    if sha(raw) != profile["RADHOUSE_RETAINED_FILES_SHA256"]:
        raise Refusal("retained_runtime_manifest_drift")
    mapping = json.loads(raw)
    if (not isinstance(mapping, dict) or not mapping
            or any(not safe_name(n) or not n.startswith("vendor/") or not HEX64.fullmatch(h) for n, h in mapping.items())):
        raise Refusal("retained_runtime_scope_invalid")
    return mapping


def authority_template(manifest, manifest_pin, profile_pin):
    return {"schema": "radhouse.release-authority.v1", "state": "pending-owner-go",
            "manifest_sha256": manifest_pin, "profile_sha256": profile_pin,
            "source_revision": manifest["source_revision"], "baseline_revision": manifest["baseline_revision"],
            "approved_at": None, "expires_at": None, "decision_locator": None, "max_attempts": 2,
            "native_restart": False, "provider_calls": 0, "database_restore": False, "automatic_rollback": False}


def authority(path, pin, manifest, manifest_pin, profile_pin):
    raw = read_file(path, private=True, owner=os.getuid())
    value = json.loads(raw)
    expected = authority_template(manifest, manifest_pin, profile_pin)
    if sha(raw) != pin or value.get("state") != "explicit-owner-go" or not value.get("decision_locator"):
        raise Refusal("exact_explicit_owner_authority_required")
    for key in ("schema", "manifest_sha256", "profile_sha256", "source_revision", "baseline_revision",
                "native_restart", "provider_calls", "database_restore", "automatic_rollback"):
        if value.get(key) != expected[key]:
            raise Refusal("authority_scope_mismatch")
    if type(value.get("max_attempts")) is not int or not 1 <= value["max_attempts"] <= 3:
        raise Refusal("authority_attempt_limit_invalid")
    try:
        approved, expires = (datetime.fromisoformat(value[k]) for k in ("approved_at", "expires_at"))
        if approved.tzinfo is None or expires.tzinfo is None or not approved <= utcnow() < expires or not 0 < (expires - approved).total_seconds() <= 5400:
            raise ValueError()
    except (TypeError, KeyError, ValueError):
        raise Refusal("authority_expired_or_invalid") from None
    return value


def require_supported(manifest):
    before, after = manifest["baseline_files_sha256"], manifest["files_sha256"]
    changes = {n for n in before.keys() | after.keys() if before.get(n) != after.get(n)}
    if (manifest.get("apply_supported") is not True or manifest.get("lane") != "static-web" or not changes
            or not all(static_route(n) and not n.startswith(STATIC + "vendor/") for n in changes)
            or not all(manifest.get(k) is False for k in ("native_restart", "database_restore", "automatic_rollback"))
            or manifest.get("provider_calls") != 0):
        raise Refusal("static_web_lane_only_separate_qualification_required")


def inventory(profile):
    data = Path(profile["RADHOUSE_SQLITE_FILE"])
    uid = int(profile["RADHOUSE_SERVICE_UID"])
    read_file(data, private=True, owner=uid, maximum=MAX_PACKET)
    before = data.lstat()
    connection = sqlite3.connect(data.as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise Refusal("database_integrity_failed")
        schema = [list(row) for row in connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]
        schema_hash = sha(encoded({"version": connection.execute("PRAGMA user_version").fetchone()[0], "objects": schema}))
        if schema_hash != profile["RADHOUSE_SQLITE_SCHEMA_SHA256"]:
            raise Refusal("database_schema_drift")
        tables = {}
        for _, name, _, _ in schema:
            if not re.fullmatch(r"[a-z_][a-z_0-9]*", name):
                raise Refusal("database_object_name_invalid")
        for name, in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            digest, count = hashlib.sha256(), 0
            for row in connection.execute('SELECT * FROM "' + name + '" ORDER BY rowid'):
                count += 1
                digest.update(encoded([(type(v).__name__, sha(v if isinstance(v, bytes) else repr(v).encode())) for v in row]))
            tables[name] = {"count": count, "sha256": digest.hexdigest()}
        work = {"prepared": 0, "busy": 0}
        rows = connection.execute("SELECT status,run_id,first_dispatch_at,retry_until,error FROM turns WHERE status NOT IN (?,?,?,?) OR error='reply_dispatch_uncertain'", TERMINAL)
        for status_value, run, first, retry, error in rows:
            if status_value == "awaiting_dispatch" and run is None and first is None and retry == 0 and error != "reply_dispatch_uncertain":
                work["prepared"] += 1
            else:
                work["busy"] += 1
    finally:
        connection.close()
    if (before.st_dev, before.st_ino) != (data.lstat().st_dev, data.lstat().st_ino):
        raise Refusal("database_identity_changed")
    originals = Path(profile["RADHOUSE_ORIGINALS_DIR"])
    ancestors(originals / "placeholder")
    info = originals.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
        raise Refusal("originals_directory_custody_failed")
    digest, count = hashlib.sha256(), 0
    for p in sorted(originals.iterdir()):
        if p.name.startswith("upload-"):
            raise Retryable("active_upload_requires_quiescence")
        raw = read_file(p, private=True, owner=uid, maximum=MAX_PACKET)
        digest.update(encoded([sha(p.name.encode()), len(raw), sha(raw)]))
        count += 1
    return {"schema_sha256": schema_hash, "tables": tables, "work": work,
            "originals": {"count": count, "sha256": digest.hexdigest()}}


def quiet(facts):
    if facts["work"]["busy"]:
        raise Retryable("active_or_uncertain_owner_work_requires_quiescence")


def retention(before, after):
    if before != after:
        raise Refusal("owner_retention_changed_no_restore")


def tree(root, mapping):
    found = {}
    ancestors(root / "placeholder")
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise Refusal("release_directory_custody_failed")
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs:
            p = Path(directory) / name
            info = p.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise Refusal("release_directory_custody_failed")
        for name in names:
            p = Path(directory) / name
            relative = p.relative_to(root).as_posix()
            if relative not in mapping:
                raise Refusal("release_unknown_member")
            found[relative] = sha(read_file(p, owner=os.getuid()))
    if found != mapping:
        raise Refusal("release_source_drift")


class Host:
    """Fixed systemd and read-only HTTPS operations; no arbitrary command interface."""
    def __init__(self, profile):
        self.profile = profile

    def identity(self):
        if sys.platform != "linux" or os.getuid() != 0:
            raise Refusal("server_local_linux_root_required")
        for key in ("RADHOUSE_RELEASE_ROOT", "RADHOUSE_EVIDENCE_ROOT"):
            p = Path(self.profile[key])
            ancestors(p / "placeholder")
            for parent in (p, *p.parents):
                info = parent.lstat()
                if info.st_uid != 0 or info.st_mode & 0o022:
                    raise Refusal("server_path_custody_failed")
        import pwd
        try:
            if pwd.getpwnam(self.profile["RADHOUSE_SERVICE_USER"]).pw_uid != int(self.profile["RADHOUSE_SERVICE_UID"]):
                raise Refusal("service_uid_mismatch")
        except KeyError:
            raise Refusal("service_identity_not_present") from None
        raw = read_file(self.profile["RADHOUSE_MACHINE_ID_FILE"], owner=0)
        if sha(raw) != self.profile["RADHOUSE_MACHINE_ID_SHA256"]:
            raise Refusal("target_machine_mismatch")

    def controls(self):
        raw = read_file(self.profile["RADHOUSE_CONTROLS_FILE"], private=True, owner=os.getuid())
        if sha(raw) != self.profile["RADHOUSE_CONTROLS_SHA256"]:
            raise Refusal("private_control_manifest_drift")
        value = json.loads(raw)
        if not value or not isinstance(value, list):
            raise Refusal("private_control_pins_required")
        ca_pinned = False
        for item in value:
            if set(item) != {"path", "sha256", "uid", "mode"} or not Path(item["path"]).is_absolute() or not HEX64.fullmatch(item["sha256"]):
                raise Refusal("private_control_pin_invalid")
            p = Path(item["path"])
            if p == Path(self.profile["RADHOUSE_API_UNIT_FILE"]):
                raise Refusal("api_unit_not_a_fixed_control")
            raw = read_file(p, owner=item["uid"])
            if sha(raw) != item["sha256"] or stat.S_IMODE(p.lstat().st_mode) != int(item["mode"], 8):
                raise Refusal("private_control_drift")
            ca_pinned |= p == Path(self.profile["RADHOUSE_TLS_CA_FILE"])
        if not ca_pinned:
            raise Refusal("tls_ca_pin_required")

    def _systemctl(self, arguments):
        result = subprocess.run(["/usr/bin/systemctl", *arguments], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=45,
                                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C"})
        if result.returncode or len(result.stdout) > 64 * 1024:
            raise Retryable("systemd_operation_failed_forward_diagnosis_required")
        return result.stdout.decode()

    def service(self, expected=None):
        raw = self._systemctl(["show", UNIT, "-pActiveState", "-pMainPID", "-pUser", "-pGroup", "-pNoNewPrivileges", "-pControlGroup"])
        value = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
        if (value.get("User") != self.profile["RADHOUSE_SERVICE_USER"] or value.get("Group") != self.profile["RADHOUSE_SERVICE_GROUP"]
                or value.get("NoNewPrivileges") != "yes"):
            raise Refusal("service_identity_drift")
        if expected == "stopped":
            if value.get("ActiveState") not in {"inactive", "failed"} or value.get("MainPID") != "0":
                raise Refusal("service_stop_unverified")
            cgroup = value.get("ControlGroup")
            if cgroup not in {"", "/system.slice/" + UNIT}:
                raise Refusal("service_cgroup_drift")
            events = Path("/sys/fs/cgroup/system.slice") / UNIT / "cgroup.events"
            if events.exists() and "populated 0" not in read_file(events).decode():
                raise Refusal("service_cgroup_not_empty")
        if expected == "active" and (value.get("ActiveState") != "active" or not value.get("MainPID", "").isdigit() or value["MainPID"] == "0"):
            raise Retryable("api_service_not_active")
        return value.get("ActiveState", "unknown")

    def stop(self):
        self._systemctl(["stop", UNIT])
        self.service("stopped")

    def start(self):
        self._systemctl(["daemon-reload"])
        self._systemctl(["start", UNIT])

    def get(self, path):
        url = urlsplit(self.profile["RADHOUSE_HTTPS_ORIGIN"])
        context = ssl.create_default_context(cafile=self.profile["RADHOUSE_TLS_CA_FILE"])
        connection = http.client.HTTPSConnection(url.hostname, url.port or 443, context=context, timeout=8)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            raw = response.read(MAX_FILE + 1)
            if len(raw) > MAX_FILE:
                raise Refusal("https_response_too_large")
            return response.status, raw
        except (OSError, http.client.HTTPException):
            raise Retryable("trusted_https_request_failed") from None
        finally:
            connection.close()

    def verify(self, manifest):
        deadline = time.monotonic() + 30
        while True:
            try:
                self.service("active")
                status, raw = self.get("/healthz")
                if status != 200 or json.loads(raw) != {"status": "ready", "scope": "web"}:
                    raise Retryable("https_health_not_ready")
                break
            except Retryable:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.25)
        for route in ("/settings", "/chat/history", "/chat/agent-profile"):
            if self.get(route)[0] not in {401, 403}:
                raise Refusal("unauthenticated_access_not_denied")
        routes = {route: name for name in manifest["files_sha256"] if (route := static_route(name))}
        for route, member in routes.items():
            status, raw = self.get(route)
            if status != 200 or sha(raw) != manifest["files_sha256"].get(member):
                raise Refusal("served_asset_integrity_failed")
        return {"trusted_https": True, "authentication_denied": True, "verified_assets": len(routes), "provider_calls": 0}


def candidate_unit(raw, manifest, profile):
    baseline = profile["RADHOUSE_BASELINE_REVISION"]
    root = Path(profile["RADHOUSE_RELEASE_ROOT"])
    old = str(root / baseline).encode()
    marker = ("Environment=RADHOUSE_RELEASE_COMMIT=" + baseline).encode()
    if old + b"/.venv/" in raw:
        raise Refusal("standing_interpreter_must_be_outside_source_release")
    if sha(raw) != profile["RADHOUSE_API_UNIT_SHA256"] or old not in raw or raw.count(marker) != 1:
        raise Refusal("baseline_api_unit_contract_failed")
    return raw.replace(old, str(root / manifest["source_revision"]).encode()).replace(marker,
        ("Environment=RADHOUSE_RELEASE_COMMIT=" + manifest["source_revision"]).encode())


def snapshot(profile, path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    source = sqlite3.connect(Path(profile["RADHOUSE_SQLITE_FILE"]).as_uri() + "?mode=ro", uri=True)
    destination = sqlite3.connect(path)
    try:
        source.backup(destination)
        if destination.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise Refusal("snapshot_integrity_failed")
    finally:
        destination.close()
        source.close()
    return sha(read_file(path, private=True, owner=os.getuid(), maximum=MAX_PACKET))


@contextmanager
def release_lock(evidence):
    fd = os.open(evidence / "release.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise Refusal("release_lock_custody_failed")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refusal("another_release_is_running") from None
        yield
    finally:
        os.close(fd)


def operate(verb, packet, pin, profile_path, authority_path=None, authority_pin=None, retry_reason=None, host_type=Host):
    manifest, files = load_packet(packet, pin)
    require_supported(manifest)
    profile, profile_pin = load_profile(profile_path)
    if profile["RADHOUSE_BASELINE_REVISION"] != manifest["baseline_revision"]:
        raise Refusal("profile_baseline_mismatch")
    host = host_type(profile)
    host.identity()
    host.controls()
    retained = retained_files(profile)
    baseline_mapping = {**manifest["baseline_files_sha256"], **retained}
    candidate_mapping = {**manifest["files_sha256"], **retained}
    evidence_root = private_directory(Path(profile["RADHOUSE_EVIDENCE_ROOT"]))
    evidence = evidence_root / pin
    if verb == "status":
        state = json.loads(read_file(evidence / "journal.json", private=True)) if evidence.exists() else {"phase": "not-applied", "attempts": 0}
        return {"phase": state["phase"], "attempts": state["attempts"], "service": host.service(),
                "source_revision": manifest["source_revision"], "private_settings": "redacted", "network_calls": 0}
    approved = authority(authority_path, authority_pin, manifest, pin, profile_pin)
    if not evidence.exists():
        evidence.mkdir(mode=0o700)
    private_directory(evidence)
    with release_lock(evidence_root):
        journal = evidence / "journal.json"
        state = json.loads(read_file(journal, private=True)) if journal.exists() else {"phase": "prepared", "attempts": 0, "manifest_sha256": pin, "profile_sha256": profile_pin}
        if state.get("manifest_sha256") != pin or state.get("profile_sha256") != profile_pin or state.get("integrity_stop"):
            raise Refusal("prior_drift_requires_explicit_reconciliation")
        if verb == "apply" and state["phase"] == "verified":
            # A journal is historical evidence, not a fresh runtime/integrity proof.
            verb = "verify"
        if verb == "apply" and state["attempts"]:
            if state.get("retryable") is not True or not retry_reason or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", retry_reason):
                raise Refusal("diagnosed_explicit_retry_required")
        if verb == "apply" and state["attempts"] >= approved["max_attempts"]:
            raise Refusal("approved_attempt_limit_reached")
        receipt = {"schema": "radhouse.release-receipt.v1", "operation": verb, "source_revision": manifest["source_revision"],
                   "manifest_sha256": pin, "profile_sha256": profile_pin, "authority_sha256": authority_pin,
                   "started_at": utcnow().isoformat(), "state": "started", "automatic_rollback": False, "database_restore": False,
                   "native_restart": False, "provider_calls": 0, "retry_reason": retry_reason}
        receipt_path = evidence / (utcnow().strftime("%Y%m%dT%H%M%S%fZ") + "-" + verb + ".json")
        atomic(receipt_path, encoded(receipt))

        def save(phase):
            state["phase"] = phase
            atomic(journal, encoded(state))

        def live():
            authority(authority_path, authority_pin, manifest, pin, profile_pin)
            host.identity()
            host.controls()

        try:
            unit_path = Path(profile["RADHOUSE_API_UNIT_FILE"])
            unit = read_file(unit_path, owner=os.getuid())
            before_path = evidence / "baseline-api.service"
            baseline_unit = read_file(before_path, private=True) if before_path.exists() else unit
            candidate = candidate_unit(baseline_unit, manifest, profile)
            current = sha(unit)
            if current not in {sha(baseline_unit), sha(candidate)}:
                raise Refusal("api_unit_drift")
            root = Path(profile["RADHOUSE_RELEASE_ROOT"])
            tree(root / (manifest["baseline_revision"] if current == sha(baseline_unit) else manifest["source_revision"]),
                 baseline_mapping if current == sha(baseline_unit) else candidate_mapping)
            if verb == "apply":
                # Count attempts before preflight; refusals never stop active owner work.
                state["attempts"] += 1
                state["retryable"] = False
                save("preflight-started")
                quiet(inventory(profile))
                save("preflight-complete")
                release = root / manifest["source_revision"]
                if release.exists() or release.is_symlink():
                    tree(release, candidate_mapping)
                else:
                    live()
                    release.mkdir(mode=0o755)
                    retained_payload = {n: read_file(root / manifest["baseline_revision"] / n, owner=os.getuid()) for n in retained}
                    if {n: sha(v) for n, v in retained_payload.items()} != retained:
                        raise Refusal("retained_runtime_source_drift")
                    for name, raw in {**files, **retained_payload}.items():
                        parent = release / PurePosixPath(name).parent
                        parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                        atomic(release / name, raw, 0o644)
                    tree(release, candidate_mapping)
                save("staged")
                live()
                host.stop()
                save("api-stopped")
                before = inventory(profile)
                quiet(before)
                # A retry may not rebaseline away data loss from a previous attempt.
                if "owner_before" in state:
                    retention(state["owner_before"], before)
                else:
                    state["owner_before"] = before
                if not before_path.exists():
                    atomic(before_path, baseline_unit)
                snapshot_pin = snapshot(profile, evidence / ("snapshot-" + str(state["attempts"]) + ".sqlite3"))
                retention(before, inventory(profile))
                state["snapshot_sha256"] = snapshot_pin
                save("snapshot-verified")
                live()
                atomic(unit_path, candidate, 0o644)
                save("candidate-published")
                live()
                host.start()
                save("candidate-started")
            elif "owner_before" not in state or not state.get("snapshot_sha256") or current != sha(candidate):
                raise Refusal("prior_apply_retention_proof_required")
            live()
            tree(root / manifest["source_revision"], candidate_mapping)
            result = host.verify(manifest)
            retention(state["owner_before"], inventory(profile))
            save("verified")
            receipt.update(state="verified", result=result, completed_at=utcnow().isoformat(), phase=state["phase"])
            atomic(receipt_path, encoded(receipt))
            return {"state": "verified", "source_revision": manifest["source_revision"], "receipt_sha256": sha(encoded(receipt)), "private_settings": "redacted"}
        except Exception as error:
            reason = str(error) if isinstance(error, Refusal) else "unexpected_failure_requires_reconciliation"
            state["retryable"] = isinstance(error, Retryable)
            if not state["retryable"]:
                state["integrity_stop"] = reason
            save(state["phase"])
            receipt.update(state="failed", reason=reason, phase=state["phase"], retryable=state["retryable"], completed_at=utcnow().isoformat())
            atomic(receipt_path, encoded(receipt))
            # Retain selected code, snapshot and all data. Never restore or auto rollback.
            return {"state": "failed", "reason": reason, "retryable": state["retryable"], "receipt_sha256": sha(encoded(receipt)), "private_settings": "redacted"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-profile", help="create private placeholders; never overwrite")
    init.add_argument("--output", type=Path, default=Path(".env"))
    for name in ("plan", "prepare"):
        p = commands.add_parser(name)
        p.add_argument("--source", type=Path, default=Path("."))
        p.add_argument("--revision", required=True)
        p.add_argument("--baseline", required=True)
        if name == "prepare":
            p.add_argument("--qualification", type=Path, required=True)
            p.add_argument("--qualification-sha256", required=True)
            p.add_argument("--output", type=Path, required=True)
            p.add_argument("--private-identifiers-file", type=Path)
    for name in ("check", "authority-template", "status", "apply", "verify"):
        p = commands.add_parser(name)
        p.add_argument("--packet", type=Path, required=True)
        p.add_argument("--manifest-sha256", required=True)
        p.add_argument("--profile", type=Path, required=name != "check")
        if name == "authority-template":
            p.add_argument("--output", type=Path, required=True)
        if name in {"apply", "verify"}:
            p.add_argument("--authority", type=Path, required=True)
            p.add_argument("--authority-sha256", required=True)
        if name == "apply":
            p.add_argument("--retry-reason")
    args = parser.parse_args(argv)
    try:
        if args.command == "init-profile":
            example = Path(__file__).resolve().parents[1] / ".env.example"
            ancestors(args.output)
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(example.read_bytes())
            result = {"state": "private_placeholders_created", "mode": "0600"}
        elif args.command == "plan":
            result = plan(args.source, args.revision, args.baseline)
        elif args.command == "prepare":
            identifiers = read_file(args.private_identifiers_file, private=True, owner=os.getuid()).decode().splitlines() if args.private_identifiers_file else ()
            result = prepare(args.source, args.revision, args.baseline, args.qualification, args.qualification_sha256, args.output, identifiers)
        elif args.command in {"check", "authority-template"}:
            manifest, _ = load_packet(args.packet, args.manifest_sha256)
            profile_pin = None
            if args.profile:
                profile, profile_pin = load_profile(args.profile)
                if profile["RADHOUSE_BASELINE_REVISION"] != manifest["baseline_revision"]:
                    raise Refusal("profile_baseline_mismatch")
            if args.command == "authority-template":
                require_supported(manifest)
                if args.output.exists() or args.output.is_symlink():
                    raise Refusal("authority_output_must_be_exclusive")
                atomic(args.output, encoded(authority_template(manifest, args.manifest_sha256, profile_pin)))
                result = {"state": "pending-owner-go", "private_settings": "redacted"}
            else:
                result = {"state": "checked", "source_revision": manifest["source_revision"], "lane": manifest["lane"],
                          "apply_supported": manifest["apply_supported"], "private_settings": "redacted", "network_calls": 0}
        else:
            result = operate(args.command, args.packet, args.manifest_sha256, args.profile,
                             getattr(args, "authority", None), getattr(args, "authority_sha256", None), getattr(args, "retry_reason", None))
        print(json.dumps(result, sort_keys=True))
        return 1 if result.get("state") == "failed" else 0
    except Exception as error:
        label = str(error) if isinstance(error, Refusal) else "operation_refused_check_private_inputs"
        print(json.dumps({"state": "refused", "reason": label, "private_settings": "redacted"}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
