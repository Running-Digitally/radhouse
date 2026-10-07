"""Fixed browser release lifecycle source. Running it on deployment-target requires a separate live gate.

No npm lifecycle scripts, model calls, new keys or permanent service. Network downloads
are official HTTPS metadata/artifacts; every promoted release is immutable and qualified.
"""
import argparse
import asyncio
import base64
from contextlib import suppress
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import signal
import shutil
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid
import zipfile

POLICY = Path("/etc/radhouse/builder-maintenance.json")
ROOT = Path("/opt/radhouse-browser")
_PROC_ROOT = Path("/proc")
CFT_METADATA = "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"
MAX_ARCHIVE = 512 * 1024 * 1024


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def root_bytes(path, limit=64 * 1024):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("root_source_unverified")
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError("root_source_unverified")
    return value


def policy(path):
    if Path(path) != POLICY:
        raise ValueError("maintenance_target_unverified")
    value = json.loads(root_bytes(path))
    machine_id = value.get("machine_id") if type(value) is dict else None
    if (type(machine_id) is not str or re.fullmatch(r"[a-f0-9]{32}", machine_id) is None
            or Path("/etc/machine-id").read_text().strip() != machine_id):
        raise ValueError("maintenance_target_unverified")
    if (value.get("schema") != "radhouse.builder-maintenance.v1"
            or value.get("browser_root") != str(ROOT) or value.get("browser_helper_identity") != "radhousebot"
            or value.get("browser_helper_sha256") != sha(__file__)
            or value.get("agent_browser_channel") != "reviewed"):
        raise ValueError("maintenance_policy_unverified")
    files = value.get("runtime_files_sha256")
    if (type(files) is not dict or not 1 <= len(files) <= 32
            or any(type(name) is not str or Path(name).is_absolute() or ".." in Path(name).parts
                   or type(digest) is not str or re.fullmatch(r"[a-f0-9]{64}", digest) is None for name, digest in files.items())
            or hashlib.sha256(canonical(files)).hexdigest() != value.get("runtime_sha256")):
        raise ValueError("maintenance_runtime_unverified")
    hermes = Path(value.get("hermes_root", ""))
    expected = Path("/opt/hermes/2237be355906fbe6065ce1815711eee52b2d646e")
    if hermes != expected or value.get("hermes_python") != str(expected / "venv/bin/python"):
        raise ValueError("maintenance_runtime_unverified")
    for name, digest in files.items():
        if sha(hermes / name) != digest:
            raise ValueError("maintenance_runtime_unverified")
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("artifact_redirect_unexpected")


def download(url, destination, maximum, *, integrity=None):
    # All URL values are constructed from fixed official roots and validated versions.
    client = build_opener(ProxyHandler({}), NoRedirect())
    count, digest = 0, hashlib.sha512()
    with client.open(Request(url, headers={"User-Agent": "Radhouse-browser-maintenance/1"}), timeout=30) as response, Path(destination).open("xb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            count += len(chunk)
            if count > maximum:
                raise ValueError("artifact_size_unexpected")
            digest.update(chunk)
            output.write(chunk)
    if integrity is not None and integrity != "sha512-" + base64.b64encode(digest.digest()).decode():
        raise ValueError("artifact_integrity_mismatch")
    return sha(destination)


def metadata(url, directory, name):
    target = directory / name
    download(url, target, 512 * 1024)
    return json.loads(target.read_bytes())


def stage(value):
    if os.geteuid() != 0:
        raise ValueError("maintenance_root_required")
    ROOT.mkdir(mode=0o755, parents=True, exist_ok=True)
    releases = ROOT / "releases"
    releases.mkdir(mode=0o755, exist_ok=True)
    if shutil.disk_usage(ROOT).free < 2 * 1024 ** 3:
        raise ValueError("browser_stage_space_unavailable")
    temporary = Path(tempfile.mkdtemp(prefix=".stage-", dir=releases))
    temporary.chmod(0o755)
    try:
        native = value.get("native_driver", {})
        required = {"version", "binary_path", "binary_sha256", "source_sha256", "patch_sha256", "npm_integrity"}
        if type(native) is not dict or set(native) != required:
            raise ValueError("native_driver_review_required")
        version = native.get("version")
        if type(version) is not str or re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
            raise ValueError("driver_version_unexpected")
        tar_url = f"https://registry.npmjs.org/agent-browser/-/agent-browser-{version}.tgz"
        integrity = native["npm_integrity"]
        source = Path(native["binary_path"])
        if (type(integrity) is not str or not integrity.startswith("sha512-")
                or not source.is_relative_to(ROOT / "native") or source.resolve() != source
                or source.name != "agent-browser"
                or any(type(native[key]) is not str or re.fullmatch(r"[a-f0-9]{64}", native[key]) is None
                       for key in ("binary_sha256", "source_sha256", "patch_sha256"))):
            raise ValueError("driver_source_unexpected")
        binary = temporary / "agent-browser"
        native_raw = root_bytes(source, 64 * 1024 * 1024)
        if hashlib.sha256(native_raw).hexdigest() != native["binary_sha256"]:
            raise ValueError("driver_source_unexpected")
        binary.write_bytes(native_raw)
        binary.chmod(0o755)
        cft = metadata(CFT_METADATA, temporary, "chromium-source.json")["channels"]["Stable"]
        chrome_version, revision = cft.get("version"), cft.get("revision")
        if (type(chrome_version) is not str or re.fullmatch(r"\d+\.\d+\.\d+\.\d+", chrome_version) is None
                or type(revision) is not str or not revision.isdigit()):
            raise ValueError("chromium_version_unexpected")
        url = f"https://storage.googleapis.com/chrome-for-testing-public/{chrome_version}/linux64/chrome-linux64.zip"
        if [item["url"] for item in cft["downloads"]["chrome"] if item.get("platform") == "linux64"] != [url]:
            raise ValueError("chromium_source_unexpected")
        zip_path = temporary / "chromium.zip"
        chrome_archive_sha = download(url, zip_path, MAX_ARCHIVE)
        with zipfile.ZipFile(zip_path) as archive:
            members = archive.infolist()
            if len(members) > 2048 or sum(member.file_size for member in members) > 1024 ** 3:
                raise ValueError("chromium_members_unexpected")
            seen = set()
            for member in members:
                parts = Path(member.filename).parts
                mode = member.external_attr >> 16
                if (not parts or parts[0] != "chrome-linux64" or ".." in parts or Path(member.filename).is_absolute()
                        or stat.S_ISLNK(mode) or member.filename in seen):
                    raise ValueError("chromium_member_unexpected")
                seen.add(member.filename)
                target = temporary / member.filename
                if member.is_dir():
                    target.mkdir(mode=0o755, parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
                    target.chmod(0o755 if mode & 0o111 else 0o644)  # Never restore setuid/setgid bits.
        chrome = temporary / "chrome-linux64/chrome"
        chrome.chmod(0o755)
        (temporary / "empty.json").write_text("{}\n")
        identity = {"agent_browser_version": version, "agent_browser_sha256": sha(binary),
                    "chromium_version": chrome_version, "chromium_revision": revision, "chromium_sha256": sha(chrome),
                    "runtime_sha256": value["runtime_sha256"]}
        release_id = hashlib.sha256(canonical(identity)).hexdigest()[:32]
        final = releases / release_id
        manifest = {"schema": "radhouse.browser-release.v1", **identity, "release_id": release_id,
            "agent_browser_path": str(final / "agent-browser"), "chromium_path": str(final / "chrome-linux64/chrome"),
            "empty_config_path": str(final / "empty.json"), "qualification_path": str(final / "qualification.json"),
            "agent_browser_integrity": integrity, "agent_browser_tarball_url": tar_url,
            "native_source_sha256": native["source_sha256"], "native_patch_sha256": native["patch_sha256"], "chromium_archive_url": url,
            "chromium_archive_sha256": chrome_archive_sha}
        (temporary / "manifest.json").write_bytes(canonical(manifest))
        for name in ("chromium.zip", "chromium-source.json"):
            (temporary / name).unlink()
        if final.exists():
            old = json.loads(root_bytes(final / "manifest.json"))
            if any(old.get(key) != item for key, item in manifest.items()):
                raise ValueError("browser_release_identity_conflict")
        else:
            os.rename(temporary, final)
        return {"state": "staged", "runtime_sha256": value["runtime_sha256"], "candidate": receipt(final)}
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def receipt(directory):
    return {"release_id": directory.name, "manifest_path": str(directory / "manifest.json"),
            "manifest_sha256": sha(directory / "manifest.json")}


def candidate(record, value):
    if type(record) is not dict or set(record) != {"release_id", "manifest_path", "manifest_sha256"}:
        raise ValueError("browser_receipt_invalid")
    identity = record["release_id"]
    if type(identity) is not str or re.fullmatch(r"[a-f0-9]{32}", identity) is None:
        raise ValueError("browser_receipt_invalid")
    directory = ROOT / "releases" / identity
    if record["manifest_path"] != str(directory / "manifest.json") or directory.is_symlink():
        raise ValueError("browser_receipt_invalid")
    raw = root_bytes(directory / "manifest.json")
    manifest = json.loads(raw)
    if hashlib.sha256(raw).hexdigest() != record["manifest_sha256"] or manifest.get("runtime_sha256") != value["runtime_sha256"]:
        raise ValueError("browser_receipt_invalid")
    for key, path in (("agent_browser", directory / "agent-browser"), ("chromium", directory / "chrome-linux64/chrome")):
        if manifest.get(key + "_path") != str(path) or path.is_symlink() or sha(path) != manifest.get(key + "_sha256"):
            raise ValueError("browser_artifact_unverified")
    if manifest.get("empty_config_path") != str(directory / "empty.json") or json.loads(root_bytes(directory / "empty.json")) != {}:
        raise ValueError("browser_configuration_unverified")
    return directory, manifest


def staged_candidate(record):
    item = record.get("candidate")
    if type(item) is dict and item.get("state") == "staged":
        return item.get("candidate")
    return item


def load_bridge(path):
    spec = importlib.util.spec_from_file_location("radhouse_hermes_bridge", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def owned_process_children(root):
    """A child belongs to its spawning thread, not necessarily the group leader."""
    children, threads = set(), 0
    for task in (root / "task").iterdir():
        threads += 1
        if threads > 128 or not task.name.isdigit():
            raise ValueError("browser_process_identity_unverified")
        try:
            with (task / "children").open() as stream:
                raw = stream.read(4097)
        except FileNotFoundError:
            continue  # A thread may exit during this bounded observation.
        if len(raw) > 4096:
            raise ValueError("browser_process_identity_unverified")
        for item in raw.split():
            if not item.isdigit() or int(item) <= 0:
                raise ValueError("browser_process_identity_unverified")
            children.add(int(item))
            if len(children) > 64:
                raise ValueError("browser_process_identity_unverified")
    return children


def sandbox_evidence(daemon_pid, chrome_path):
    """Read only bounded descendants of this exact daemon, no host process dump."""
    if sys.platform != "linux" or os.geteuid() == 0:
        return False
    pending, seen, renderers = [daemon_pid], set(), []
    try:
        daemon_ns = os.readlink(_PROC_ROOT / str(daemon_pid) / "ns/pid")
        while pending:
            pid = pending.pop()
            if pid in seen:
                continue
            seen.add(pid)
            if len(seen) > 64:
                return False
            root = _PROC_ROOT / str(pid)
            args = (root / "cmdline").read_bytes().split(b"\0")
            if any(argument in {b"--no-sandbox", b"--disable-setuid-sandbox", b"--disable-seccomp-filter-sandbox", b"--disable-namespace-sandbox"} for argument in args):
                return False
            status = dict(line.split(":", 1) for line in (root / "status").read_text().splitlines() if ":" in line)
            if int(status["Uid"].split()[0]) != os.geteuid():
                return False
            if b"--type=renderer" in args:
                if (Path(os.readlink(root / "exe")) != Path(chrome_path)
                        or status.get("Seccomp", "").strip() != "2" or status.get("NoNewPrivs", "").strip() != "1"
                        or os.readlink(root / "ns/pid") == daemon_ns):
                    return False
                renderers.append(pid)
            pending.extend(owned_process_children(root))
        return bool(renderers)
    except (OSError, KeyError, ValueError):
        return False


def owned_chrome_endpoint(daemon_pid, chrome_path):
    """Resolve only this daemon's exact owned Chrome; no discovery/port scanning."""
    pending, seen = [daemon_pid], set()
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        if len(seen) > 64:
            raise ValueError("browser_chrome_identity_unverified")
        root = _PROC_ROOT / str(pid)
        try:
            executable = Path(os.readlink(root / "exe"))
            args = (root / "cmdline").read_bytes().split(b"\0")
            if executable == Path(chrome_path) and not any(argument.startswith(b"--type=") for argument in args):
                status = dict(line.split(":", 1) for line in (root / "status").read_text().splitlines() if ":" in line)
                profiles = [argument.removeprefix(b"--user-data-dir=").decode() for argument in args if argument.startswith(b"--user-data-dir=")]
                if len(profiles) != 1 or int(status["Uid"].split()[0]) != os.geteuid():
                    raise ValueError("browser_chrome_identity_unverified")
                profile = Path(profiles[0])
                info = profile.lstat()
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                    raise ValueError("browser_chrome_identity_unverified")
                descriptor = os.open(profile / "DevToolsActivePort", os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
                        raise ValueError("browser_chrome_identity_unverified")
                    lines = stream.read(513).decode().splitlines()
                if (len(lines) != 2 or not lines[0].isdigit() or not 1024 <= int(lines[0]) <= 65535
                        or re.fullmatch(r"/devtools/browser/[a-f0-9-]{8,64}", lines[1]) is None):
                    raise ValueError("browser_chrome_identity_unverified")
                return "http://127.0.0.1:" + lines[0] + lines[1]
            pending.extend(owned_process_children(root))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue  # A transient helper process is not the owned Chrome assertion.
    raise ValueError("browser_chrome_identity_unverified")


def qualify_pair(manifest, *, bridge_path=None, require_sandbox=True, require_origin=True):
    """Disposable native seven-command/stream canary; callable by an owned Linux fixture.

    No model or credentials. An unsandboxed container can prove compatibility only;
    its result can never be promoted by the lifecycle verbs.
    """
    bridge = load_bridge(bridge_path or Path(__file__).with_name("bridge.py"))
    session = "h_" + uuid.uuid4().hex[:10]
    fixture = Path(tempfile.mkdtemp(prefix="radhouse-browser-canary-"))
    fixture.chmod(0o700)
    (fixture / "empty.json").write_text("{}\n")
    socket = fixture / ("agent-browser-" + session)
    socket.mkdir(mode=0o700)
    environment = {key: value for key, value in os.environ.items() if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}}
    environment.update(AGENT_BROWSER_SOCKET_DIR=str(socket), AGENT_BROWSER_IDLE_TIMEOUT_MS="30000", AGENT_BROWSER_ARGS="--disable-extensions")
    argv = [manifest["agent_browser_path"], "--config", str(fixture / "empty.json"), "--executable-path", manifest["chromium_path"], "--session", session, "--json"]
    def command(name, *arguments):
        completed = subprocess.run(argv + [name, "--", *arguments], stdin=subprocess.DEVNULL, capture_output=True,
                                   env=environment, timeout=45, check=False)
        if len(completed.stdout) > 128 * 1024 or completed.returncode != 0:
            raise ValueError("browser_native_canary_failed")
        result = json.loads(completed.stdout)
        if result.get("success") is not True:
            raise ValueError("browser_native_canary_failed")
        return result
    class Page(BaseHTTPRequestHandler):
        def do_GET(self):
            body = ("<html><title>Radhouse native canary</title><body style='height:2000px;background:" +
                    ("blue" if self.path == "/second" else "red") +
                    "'><label>Name<input aria-label='Name'></label><a href='/second'>Second</a>"
                    "<button onclick='clearInterval(window.animation);document.body.style.background=\"green\"'>Stop</button>"
                    "<script>window.animation=setInterval(()=>document.body.style.opacity=document.body.style.opacity==='0.9'?'1':'0.9',250)</script></body></html>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    relay = None
    try:
        command("open", f"http://127.0.0.1:{server.server_port}/")
        stream_path, pid_path = socket / (session + ".stream"), socket / (session + ".pid")
        deadline = time.monotonic() + 10
        while not stream_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        info = stream_path.stat()
        port, daemon_pid = int(stream_path.read_text().strip()), int(pid_path.read_text().strip())
        if info.st_uid != os.geteuid() or not 1024 <= port <= 65535:
            raise ValueError("browser_native_identity_failed")
        generation = hashlib.sha256(f"{session}:{info.st_ino}:{info.st_mtime_ns}".encode()).hexdigest()[:32]
        def current():
            if (not pid_path.exists() or int(pid_path.read_text().strip()) != daemon_pid
                    or stream_path.stat().st_ino != info.st_ino or stream_path.stat().st_mtime_ns != info.st_mtime_ns):
                return None
            return port, generation
        # A remote web page must not reach the native HTTP command surface, including
        # a different localhost port. This probes denial with a non-command body.
        client = build_opener(ProxyHandler({}), NoRedirect())
        origin_guard = True
        origins = ("https://example.com", "http://192.0.2.10", f"http://127.0.0.1:{port + 1}",
                   f"http://127.0.0.1:{port}", "", "null", "file://")
        for origin in origins:
            for endpoint, body in (("/api/command", b'{"command":"radhouse-origin-denial-canary"}'),
                                   ("/api/sessions", b'{"name":"invalid/session"}')):
                for method in ("GET", "POST", "OPTIONS"):
                    probe = Request(f"http://127.0.0.1:{port}" + endpoint, data=body if method == "POST" else None,
                                    method=method, headers={"Origin": origin, "Content-Type": "application/json"})
                    try:
                        response = client.open(probe, timeout=3)
                        response.close()
                        origin_guard = False
                    except HTTPError as error:
                        origin_guard = origin_guard and error.code in {403, 404, 405}
        for endpoint, body in (("/api/command", b'{"command":"radhouse-origin-denial-canary"}'),
                               ("/api/sessions", b'{"name":"invalid/session"}')):
            probe = Request(f"http://127.0.0.1:{port}" + endpoint, data=body, method="POST", headers={"Content-Type": "application/json"})
            try:
                response = client.open(probe, timeout=3)
                response.close()
                origin_guard = False
            except HTTPError as error:
                origin_guard = origin_guard and error.code in {403, 404, 405}
        view_only = False
        chrome_guard = False
        chrome_endpoint = owned_chrome_endpoint(daemon_pid, manifest["chromium_path"])
        async def exercise():
            nonlocal relay, origin_guard, view_only, chrome_guard
            import aiohttp
            async with aiohttp.ClientSession(trust_env=False) as client:
                chrome_guard = True
                # Browser-produced Origins are nonempty; an absent Origin is the
                # legitimate Unix-CLI program's CDP channel. Never send CDP data.
                for origin in [item for item in origins if item]:
                    try:
                        async with client.ws_connect(chrome_endpoint, headers={"Origin": origin}, timeout=3):
                            chrome_guard = False
                    except aiohttp.WSServerHandshakeError as error:
                        chrome_guard = chrome_guard and error.status == 403
                for origin in origins:
                    try:
                        async with client.ws_connect(f"http://127.0.0.1:{port}", headers={"Origin": origin}, timeout=3):
                            origin_guard = False  # Never send input while probing denial.
                    except aiohttp.WSServerHandshakeError as error:
                        origin_guard = origin_guard and error.status == 403
            relay = bridge.NativeRelay(session, port, generation, current=current)
            first = await relay.snapshot(True)
            snapshot = await asyncio.to_thread(command, "snapshot", "-i")
            text = snapshot.get("data", {}).get("snapshot", "")
            refs = {}
            for line in text.splitlines():
                found = re.search(r"\[ref=(e\d+)\]", line)
                if found:
                    for label in ("Name", "Second", "Stop"):
                        if label in line:
                            refs[label] = found.group(1)
            if set(refs) != {"Name", "Second", "Stop"}:
                raise ValueError("browser_native_reference_failed")
            await asyncio.to_thread(command, "fill", "@" + refs["Name"], "--config")
            value = await asyncio.to_thread(command, "get", "value", "@" + refs["Name"])
            if value.get("data", {}).get("value") != "--config":
                raise ValueError("browser_native_literal_argument_failed")
            # The no-Origin observer is program-only and still must never control
            # browser input, stream configuration or ACK pacing.
            async with aiohttp.ClientSession(trust_env=False) as observer:
                async with observer.ws_connect(f"http://127.0.0.1:{port}", timeout=3) as channel:
                    await channel.send_json({"type": "input_keyboard", "eventType": "char", "text": "intruder"})
                    await channel.send_bytes(b'{"type":"input_keyboard","eventType":"char","text":"intruder"}')
                    await channel.send_json({"type": "config", "pacing": "ack"})
                    await channel.send_json({"type": "ack", "seq": -1})
                    hashes = set()
                    deadline = asyncio.get_running_loop().time() + 3
                    while len(hashes) < 2 and asyncio.get_running_loop().time() < deadline:
                        try:
                            message = await channel.receive(timeout=max(0.01, deadline - asyncio.get_running_loop().time()))
                        except asyncio.TimeoutError:
                            break
                        if message.type == aiohttp.WSMsgType.TEXT:
                            item = json.loads(message.data)
                            if item.get("type") == "frame":
                                hashes.add(hashlib.sha256(item["data"].encode()).hexdigest())
                    after = await asyncio.to_thread(command, "get", "value", "@" + refs["Name"])
                    view_only = len(hashes) >= 2 and after.get("data", {}).get("value") == "--config"
            await asyncio.to_thread(command, "press", "Tab")
            await asyncio.to_thread(command, "scroll", "down", "100")
            await asyncio.to_thread(command, "click", "@" + refs["Second"])
            deadline = asyncio.get_running_loop().time() + 5
            second = await relay.snapshot(True)
            while (second["frame_id"] == first["frame_id"] or not second["url"].endswith("/second")) and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.1)
                second = await relay.snapshot(True)
            if second["frame_id"] == first["frame_id"] or not second["url"].endswith("/second"):
                raise ValueError("browser_native_frame_progression_failed")
            await asyncio.to_thread(command, "back")
            snapshot = await asyncio.to_thread(command, "snapshot", "-i")
            stop = next((re.search(r"\[ref=(e\d+)\]", line).group(1) for line in snapshot.get("data", {}).get("snapshot", "").splitlines()
                         if "Stop" in line and re.search(r"\[ref=(e\d+)\]", line)), None)
            if not stop:
                raise ValueError("browser_native_reference_failed")
            await asyncio.to_thread(command, "click", "@" + stop)
            await asyncio.sleep(0.5)
            stationary = await relay.snapshot(True)
            await asyncio.sleep(1.25)
            still = await relay.snapshot(True)
            if current() != (port, generation) or not stationary["jpeg"] or not still["jpeg"]:
                raise ValueError("browser_native_stationary_view_failed")
            relay.task.cancel()
            with suppress(asyncio.CancelledError): await relay.task
        asyncio.run(exercise())
        sandbox = sandbox_evidence(daemon_pid, manifest["chromium_path"])
        if require_origin and (not origin_guard or not view_only or not chrome_guard):
            raise ValueError("browser_native_origin_guard_failed")
        if require_sandbox and not sandbox:
            raise ValueError("browser_native_sandbox_unverified")
        return {"same_session_frame_progression": True, "stationary_frame_available": True,
            "sandbox_enabled": sandbox, "origin_guard_verified": origin_guard,
            "view_only_input_ignored": view_only,
            "chrome_control_guard_verified": chrome_guard,
            "agent_browser_version": manifest["agent_browser_version"], "agent_browser_sha256": sha(manifest["agent_browser_path"]),
            "chromium_sha256": sha(manifest["chromium_path"]), "runtime_sha256": manifest.get("runtime_sha256"),
            "checked_at": datetime.now(timezone.utc).isoformat()}
    finally:
        with suppress(Exception): command("close")
        server.shutdown()
        server.server_close()
        thread.join(2)
        shutil.rmtree(fixture)


def qualify(record, value):
    if os.geteuid() != pwd.getpwnam("radhousebot").pw_uid:
        raise ValueError("maintenance_bot_required")
    selected = staged_candidate(record)
    _, manifest = candidate(selected, value)
    proof = qualify_pair(manifest, bridge_path=Path(value["hermes_root"]) / "radhouse_hermes_bridge.py")
    return {"state": "qualified", **proof, "candidate": selected}


def current_receipt():
    link = ROOT / "current"
    if not link.exists():
        return None
    resolved = link.resolve(strict=True)
    if resolved.parent != ROOT / "releases" or re.fullmatch(r"[a-f0-9]{32}", resolved.name) is None:
        raise ValueError("browser_current_unverified")
    return receipt(resolved)


def switch(directory):
    temporary = ROOT / (".current-" + uuid.uuid4().hex)
    os.symlink(directory, temporary)
    os.replace(temporary, ROOT / "current")


def promote(record, value):
    if os.geteuid() != 0:
        raise ValueError("maintenance_root_required")
    selected = staged_candidate(record)
    directory, manifest = candidate(selected, value)
    proof = record.get("qualification", {})
    if (proof.get("state") != "qualified" or proof.get("same_session_frame_progression") is not True
            or proof.get("sandbox_enabled") is not True or proof.get("origin_guard_verified") is not True
            or proof.get("view_only_input_ignored") is not True
            or proof.get("chrome_control_guard_verified") is not True
            or any(proof.get(key) != manifest.get(key) for key in ("agent_browser_version", "agent_browser_sha256", "chromium_sha256", "runtime_sha256"))
            or proof.get("candidate") != selected):
        raise ValueError("browser_qualification_unverified")
    previous = current_receipt()
    existing = directory / "qualification.json"
    if existing.exists():
        old_raw = root_bytes(existing)
        old = json.loads(old_raw)
        if (manifest.get("sandbox_proof_sha256") != hashlib.sha256(old_raw).hexdigest()
                or any(old.get(key) != proof.get(key) for key in ("agent_browser_sha256", "chromium_sha256", "runtime_sha256",
                                                               "sandbox_enabled", "origin_guard_verified", "view_only_input_ignored", "chrome_control_guard_verified", "same_session_frame_progression"))):
            raise ValueError("browser_release_qualification_conflict")
    else:
        raw = canonical(proof)
        existing.write_bytes(raw)
        manifest["sandbox_proof_sha256"] = hashlib.sha256(raw).hexdigest()
        (directory / "manifest.json").write_bytes(canonical(manifest))
    switch(directory)
    return {"state": "promoted", "runtime_sha256": value["runtime_sha256"], "previous": previous, "current": receipt(directory)}


def qualification_output(command, payload, timeout=180):
    """Observe a bot canary without interrupting its native browser cleanup.

    A missed deadline or termination request makes qualification uncertain. Keep
    owning the child until it finishes its finally block, then report failure so
    maintenance remains fenced. Never kill runuser or its browser descendants.
    """
    interrupted = False
    expired = False
    handlers = {}
    child = None

    def interrupt(_signum, _frame):
        nonlocal interrupted
        interrupted = True

    with tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as stdout:
        stdin.write(payload)
        stdin.seek(0)
        try:
            if threading.current_thread() is threading.main_thread():
                for sig in (signal.SIGINT, signal.SIGTERM):
                    handlers[sig] = signal.signal(sig, interrupt)
            child = subprocess.Popen(command, stdin=stdin, stdout=stdout, stderr=subprocess.DEVNULL)
            try:
                child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                expired = True
            except BaseException:
                interrupted = True
            finally:
                # Reap directly: failed Popen polling/wait diagnostics must not
                # abandon the qualifier or its still-owned browser descendants.
                while child.returncode is None:
                    try:
                        pid, status = os.waitpid(child.pid, 0)
                        if pid:
                            child.returncode = os.waitstatus_to_exitcode(status)
                    except ChildProcessError:
                        break  # Externally reaped: completion outcome is unknown.
                    except BaseException:
                        interrupted = True
                        with suppress(BaseException):
                            time.sleep(0.01)
            if expired or interrupted:
                raise ValueError("browser_qualification_observation_interrupted")
            stdout.seek(0)
            data = stdout.read(64 * 1024 + 1)
            if child.returncode != 0 or len(data) > 64 * 1024:
                raise ValueError("browser_current_qualification_failed")
            return data
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)


def verify(record, value):
    if os.geteuid() != 0:
        raise ValueError("maintenance_root_required")
    current = current_receipt()
    if current is None:
        raise ValueError("browser_current_unverified")
    candidate(current, value)
    # A real bot-identity canary is rerun after native package changes/reboot.
    command = ["/usr/sbin/runuser", "-u", "radhousebot", "--", value["hermes_python"], "-B", "-I", str(ROOT / "bootstrap.py"),
               "maintenance-qualify", "--policy", str(POLICY)]
    proof = json.loads(qualification_output(command, canonical({"candidate": current})))
    if proof.get("state") != "qualified" or proof.get("sandbox_enabled") is not True:
        raise ValueError("browser_current_qualification_failed")
    return {"state": "verified", "runtime_sha256": value["runtime_sha256"], "current": current,
            "same_session_frame_progression": True, "qualification": proof}


def rollback(record, value):
    if os.geteuid() != 0:
        raise ValueError("maintenance_root_required")
    previous = record.get("browser", {}).get("previous") or record.get("previous")
    if previous is None:
        raise ValueError("browser_rollback_source_unavailable")
    directory, _ = candidate(previous, value)
    switch(directory)
    return {"state": "rolled_back", "runtime_sha256": value["runtime_sha256"], "current": previous}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("verb", choices=("maintenance-stage", "maintenance-qualify", "maintenance-promote", "maintenance-verify", "maintenance-rollback"))
    parser.add_argument("--policy", required=True)
    arguments = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024:
            raise ValueError("maintenance_input_invalid")
        record = json.loads(raw or b"{}")
        if type(record) is not dict:
            raise ValueError("maintenance_input_invalid")
        value = policy(arguments.policy)
        handlers = {"maintenance-stage": lambda: stage(value), "maintenance-qualify": lambda: qualify(record, value),
                    "maintenance-promote": lambda: promote(record, value), "maintenance-verify": lambda: verify(record, value),
                    "maintenance-rollback": lambda: rollback(record, value)}
        print(json.dumps(handlers[arguments.verb](), sort_keys=True))
    except Exception as error:
        # No third-party/native stderr, URL content, process argv or root policy values.
        code = str(error) if isinstance(error, ValueError) and re.fullmatch(r"[a-z_]{1,80}", str(error)) else "browser_maintenance_failed"
        print(json.dumps({"state": "unavailable", "error": code}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
