"""Own and clean an isolated PostgreSQL/Redis/relay protocol qualification.

The S3 byte store and model execution are synthetic. All Buzz HTTP protocol,
signature, membership, media and channel handlers are the pinned real relay.
"""

import importlib.util
import json
import os
from pathlib import Path
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import subprocess
import sys
import time
from urllib.parse import quote

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from coincurve import PrivateKey

root = Path(__file__).resolve().parents[2]
if len(sys.argv) != 2:
    raise SystemExit(
        "Usage: python tests/qualification/run_buzz.py /path/to/qualified/buzz"
    )
buzz = Path(sys.argv[1]).resolve()
expected = "092c6a7277698bd373ccbc1d008fc1507094ae74"
subprocess.run(
    [
        "git",
        "-C",
        str(buzz),
        "diff",
        "--exit-code",
        expected,
        "--",
        "crates",
        "Cargo.toml",
        "Cargo.lock",
    ],
    check=True,
    stdout=subprocess.DEVNULL,
)
sys.path.insert(0, str(root))
spec = importlib.util.spec_from_file_location("fixture", root / "scripts/vs0.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
run = module.Run()
redis_id = None
process = None
result = None
object_server = None


def port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


# Only the backing object store is synthetic. Buzz executes its real upload,
# authenticated read, membership, integrity and tenant routing code.
class ObjectStore(BaseHTTPRequestHandler):
    objects = {}

    def log_message(self, *_):
        pass

    def do_PUT(self):
        data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.objects[self.path] = (
            data,
            self.headers.get("Content-Type", "application/octet-stream"),
        )
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.send_header("ETag", '"fixture-etag"')
        self.end_headers()

    def read(self, head=False):
        saved = self.objects.get(self.path)
        if saved is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data, mime = saved
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("ETag", '"fixture-etag"')
        self.end_headers()
        if not head:
            self.wfile.write(data)

    def do_GET(self):
        self.read()

    def do_HEAD(self):
        self.read(True)

    def do_DELETE(self):
        self.objects.pop(self.path, None)
        self.send_response(204)
        self.end_headers()


try:
    run.preflight()
    run.start()
    redis_image = (
        "sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2"
    )
    redis_id = run.docker(
        "create",
        "--name",
        "radhouse-buzz-redis-" + run.run_id,
        "--label",
        f"{module.LABEL}={run.run_id}",
        "--memory",
        "128m",
        "--memory-swap",
        "128m",
        "--cpus",
        "0.5",
        "--pids-limit",
        "64",
        "--tmpfs",
        "/data:rw,noexec,nosuid,size=64m",
        "--publish",
        "127.0.0.1::6379",
        redis_image,
        "redis-server",
        "--save",
        "",
        "--appendonly",
        "no",
    ).stdout.strip()
    run.manifest["buzz_redis_container_id"] = redis_id
    run.manifest["buzz_redis_image"] = redis_image
    run.save()
    run.docker("start", redis_id)
    redis_info = json.loads(run.docker("inspect", redis_id).stdout)[0]
    assert redis_info["Config"]["Labels"][module.LABEL] == run.run_id
    redis_port = redis_info["NetworkSettings"]["Ports"]["6379/tcp"][0]["HostPort"]
    options = conninfo_to_dict(run.env["RADHOUSE_VS0_OWNER_DSN"])
    database = "buzz_fixture_" + run.run_id
    assert run.inspect_owned()["Id"] == run.manifest["container_id"]
    with psycopg.connect(run.env["RADHOUSE_VS0_OWNER_DSN"], autocommit=True) as db:
        db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    url = f"postgresql://{quote(options['user'], safe='')}:{quote(options['password'], safe='')}@127.0.0.1:{options['port']}/{database}?sslmode=disable"
    owner, authority = PrivateKey(), PrivateKey()
    api_port = port()
    origin = f"http://127.0.0.1:{api_port}"
    object_server = ThreadingHTTPServer(("127.0.0.1", 0), ObjectStore)
    Thread(target=object_server.serve_forever, daemon=True).start()
    process_env = {
        "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
        "HOME": str(run.output),
        "RUST_LOG": "warn",
        "DATABASE_URL": url,
        "REDIS_URL": f"redis://127.0.0.1:{redis_port}",
        "BUZZ_BIND_ADDR": f"127.0.0.1:{api_port}",
        "BUZZ_HEALTH_PORT": str(port()),
        "BUZZ_METRICS_PORT": str(port()),
        "RELAY_URL": origin.replace("http:", "ws:"),
        "BUZZ_RELAY_PRIVATE_KEY": authority.secret.hex(),
        "RELAY_OWNER_PUBKEY": owner.public_key_xonly.format().hex(),
        "BUZZ_REQUIRE_RELAY_MEMBERSHIP": "true",
        "BUZZ_ALLOW_NIP_OA_AUTH": "true",
        "BUZZ_GIT_CONFORMANCE_PROBE": "false",
        "BUZZ_REQUIRE_AUTH_TOKEN": "true",
        "BUZZ_AUTO_MIGRATE": "true",
        "BUZZ_S3_ENDPOINT": f"http://127.0.0.1:{object_server.server_port}",
        "BUZZ_S3_ACCESS_KEY": "synthetic-fixture",
        "BUZZ_S3_SECRET_KEY": "synthetic-fixture",
        "BUZZ_MEDIA_BASE_URL": origin + "/media",
        "BUZZ_RATE_LIMIT_HUMAN_MESSAGES_PER_MIN": "1000",
        "BUZZ_RATE_LIMIT_HUMAN_API_CALLS_PER_MIN": "2000",
        "BUZZ_RATE_LIMIT_AGENT_STANDARD_API_CALLS_PER_MIN": "2000",
    }
    log = open(run.output / "buzz-relay.log", "w")
    process = subprocess.Popen(
        [str(buzz / "target/debug/buzz-relay")],
        cwd=run.output,
        env=process_env,
        stdout=log,
        stderr=log,
    )
    ready = time.monotonic() + 60
    while True:
        if process.poll() is not None:
            raise RuntimeError("relay stopped; inspect sanitized fixture log")
        try:
            if (
                httpx.get(origin + "/_liveness", trust_env=False, timeout=1).status_code
                == 200
            ):
                break
        except httpx.HTTPError:
            pass
        if time.monotonic() > ready:
            raise RuntimeError("relay readiness timeout")
        time.sleep(0.2)
    run.env.update(
        RADHOUSE_OWNED_BUZZ_ORIGIN=origin,
        RADHOUSE_OWNED_BUZZ_OWNER_KEY=owner.secret.hex(),
        RADHOUSE_OWNED_BUZZ_RELAY_KEY=authority.public_key_xonly.format().hex(),
    )
    result = run.command(
        [
            sys.executable,
            "-m",
            "pytest",
            "-qs",
            "--tb=short",
            "tests/qualification/buzz_protocol.py",
        ],
        env=run.env,
        accepted=(0, 1, 2, 3, 4, 5),
    )
    output = result.stdout + result.stderr
    for value in [
        url,
        options["password"],
        owner.secret.hex(),
        authority.secret.hex(),
        run.env["RADHOUSE_VS0_DSN"],
        run.env["RADHOUSE_VS0_OWNER_DSN"],
    ]:
        output = output.replace(value, "<synthetic fixture credential>")
    print(output)
    if "Side effect failed" in (run.output / "buzz-relay.log").read_text():
        raise RuntimeError("real relay rejected a profile side effect")
    run.manifest["buzz_protocol"] = "passed" if result.returncode == 0 else "failed"
finally:
    if process is not None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()
        data = (run.output / "buzz-relay.log").read_text()
        for value in (
            url,
            options["password"],
            owner.secret.hex(),
            authority.secret.hex(),
        ):
            data = data.replace(value, "<synthetic fixture credential>")
        (run.output / "buzz-relay.log").write_text(data)
    if redis_id:
        info = json.loads(run.docker("inspect", redis_id).stdout)[0]
        if info["Config"]["Labels"].get(module.LABEL) == run.run_id:
            run.docker("rm", "--force", redis_id)
    if object_server:
        object_server.shutdown()
        object_server.server_close()
    run.cleanup()
    print("MANIFEST", run.manifest_path, "CLEANUP", run.manifest.get("cleanup"))
sys.exit(result.returncode if result else 1)
