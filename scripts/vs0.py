#!/usr/bin/env python3
"""One bounded local PostgreSQL fixture: uv run python scripts/vs0.py verify|demo."""
from __future__ import annotations

import argparse
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import shutil
import stat
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Official registry index read with docker buildx imagetools inspect on 2026-09-11.
# Source: https://hub.docker.com/_/postgres
IMAGE_TAG = "postgres:18.6-bookworm"
PINNED_IMAGE = IMAGE_TAG + "@sha256:1c59e2c3c818eaa0f0628f695b36e7c9e362d6b219b36a54a32df645cbd7e1af"
LABEL = "org.radhouse.vs0.run-id"
LIMIT_SECONDS = 900


class FixtureError(Exception):
    pass


class PrerequisiteError(FixtureError):
    pass


class Run:
    def __init__(self):
        self.deadline = time.monotonic() + LIMIT_SECONDS
        self.run_id = uuid4().hex
        self.output = ROOT / ".vs0" / self.run_id
        self.manifest_path = self.output / "manifest.json"
        self.context = ""
        self.manifest = {"run_id": self.run_id, "database": f"radhouse_vs0_{self.run_id}",
                         "container_name": f"radhouse-vs0-{self.run_id}",
                         "volume_name": f"radhouse-vs0-{self.run_id}", "cleanup": "pending"}
        self.env = os.environ.copy()

    def remaining(self) -> float:
        value = self.deadline - time.monotonic()
        if value <= 0:
            raise FixtureError("VS0 reached its 15-minute execution limit")
        return value

    def command(self, args: list[str], *, env=None, accepted=(0,), timeout=None) -> subprocess.CompletedProcess:
        try:
            result = subprocess.run(args, cwd=ROOT, env=env or self.env, text=True, capture_output=True,
                                    timeout=min(self.remaining(), timeout or LIMIT_SECONDS))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FixtureError(f"local {Path(args[0]).name} command unavailable or timed out") from exc
        if result.returncode not in accepted:
            # Vendor output may contain connection strings or environment values.
            raise FixtureError(f"local {Path(args[0]).name} command failed (exit {result.returncode}); no proof recorded")
        return result

    def docker(self, *args: str, **kwargs):
        return self.command(["docker", "--context", self.context, *args], **kwargs)

    def save(self):
        self.manifest_path.write_text(json.dumps(self.manifest, indent=2) + "\n")

    def preflight(self):
        forbidden = ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "DOCKER_API_VERSION")
        if any(os.environ.get(key) for key in forbidden):
            raise FixtureError("unset Docker endpoint/context/TLS/API overrides; VS0 requires the configured local Unix-socket context")
        if any(os.environ.get(key) for key in ("PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS")):
            raise FixtureError("unset PostgreSQL endpoint/service/options overrides before running the owned VS0 fixture")
        if shutil.disk_usage(ROOT).free < 2 * 1024**3:
            raise FixtureError("VS0 needs at least 2 GiB free local disk before fixture creation")
        self.context = self.command(["docker", "context", "show"], timeout=10).stdout.strip()
        metadata = json.loads(self.command(["docker", "context", "inspect", self.context], timeout=10).stdout)
        endpoint = metadata[0]["Endpoints"]["docker"]["Host"]
        if not endpoint.startswith("unix://"):
            raise FixtureError("VS0 refuses remote Docker contexts; select a local Unix-socket context")
        try:
            if not stat.S_ISSOCK(Path(endpoint[7:]).stat().st_mode):
                raise FixtureError("configured local Docker endpoint is not a Unix socket")
        except FileNotFoundError as exc:
            raise PrerequisiteError("local Docker daemon is stopped; start the intended local daemon explicitly, then rerun") from exc
        try:
            self.docker("info", "--format", "{{json .ServerVersion}}", timeout=15)
        except FixtureError as exc:
            raise PrerequisiteError("local Docker daemon is unavailable; no container launched and integration proof remains unverified") from exc
        image = PINNED_IMAGE
        if os.environ.get("RADHOUSE_VS0_POSTGRES_IMAGE", image) != image:
            raise FixtureError("VS0 refuses an image override that differs from its reviewed immutable pin")
        self.output.mkdir(parents=True, exist_ok=False)
        self.manifest.update(image=image, python=sys.version.split()[0], command_limit_seconds=LIMIT_SECONDS,
                             local_socket_verified=True, minimum_free_disk_bytes=2 * 1024**3,
                             source_commit=self.command(["git", "rev-parse", "HEAD"]).stdout.strip(),
                             dependency_lock_sha256=hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest())
        source = hashlib.sha256()
        for base in (ROOT / "src", ROOT / "tests", ROOT / "scripts", ROOT / "deploy" / "dev"):
            for path in sorted(base.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    source.update(str(path.relative_to(ROOT)).encode())
                    source.update(path.read_bytes())
        self.manifest["source_sha256"] = source.hexdigest()
        self.save()

    def inspect_owned(self):
        target = self.manifest.get("container_id", self.manifest["container_name"])
        result = self.docker("inspect", target, accepted=(0, 1), timeout=15)
        if result.returncode:
            return None
        info = json.loads(result.stdout)[0]
        if info["Config"].get("Labels", {}).get(LABEL) != self.run_id:
            raise FixtureError("container ownership mismatch; resource retained")
        return info

    def start(self):
        import psycopg
        from psycopg.conninfo import make_conninfo
        from psycopg import sql

        self.docker("pull", self.manifest["image"])
        image = json.loads(self.docker("image", "inspect", self.manifest["image"]).stdout)[0]
        digest = self.manifest["image"].split("@", 1)[1]
        if not any(item.endswith("@" + digest) for item in image.get("RepoDigests", [])):
            raise FixtureError("local image does not match the requested immutable registry digest")
        self.manifest["image_id"] = image["Id"]
        volume_name = self.manifest["volume_name"]
        existing = self.docker("volume", "ls", "--filter", f"name={volume_name}", "--format", "{{.Name}}").stdout.splitlines()
        if volume_name in existing:
            self.manifest["volume_preexisting"] = True
            self.save()
            raise FixtureError("generated fixture volume already exists; retained without reuse")
        self.docker("volume", "create", "--label", f"{LABEL}={self.run_id}", volume_name)
        volume = json.loads(self.docker("volume", "inspect", volume_name).stdout)
        if len(volume) != 1 or volume[0].get("Name") != volume_name or volume[0].get("Labels", {}).get(LABEL) != self.run_id:
            raise FixtureError("new fixture volume ownership mismatch; no container created")
        self.manifest["volume_verified_before_mount"] = True
        self.save()
        self.env["POSTGRES_PASSWORD"] = secrets.token_urlsafe(32)
        container = self.docker("create", "--name", self.manifest["container_name"],
            "--label", f"{LABEL}={self.run_id}", "--cpus", "1", "--memory", "512m", "--memory-swap", "512m",
            "--pids-limit", "128", "--publish", "127.0.0.1::5432",
            "--mount", f"type=volume,source={self.manifest['volume_name']},target=/var/lib/postgresql",
            "--env", "POSTGRES_PASSWORD", "--env", "POSTGRES_USER=fixture_owner",
            "--env", f"POSTGRES_DB={self.manifest['database']}", self.manifest["image"])
        self.manifest["container_id"] = container.stdout.strip()
        self.save()
        self.docker("start", self.manifest["container_id"])
        info = self.inspect_owned()
        host = info["HostConfig"]
        if host["Privileged"] or host["NetworkMode"] == "host" or host["NanoCpus"] != 1_000_000_000 or host["Memory"] != 512 * 1024**2:
            raise FixtureError("container resource/isolation settings differ from the bounded fixture")
        mounts = info["Mounts"]
        if len(mounts) != 1 or mounts[0]["Type"] != "volume" or mounts[0]["Name"] != self.manifest["volume_name"]:
            raise FixtureError("container has an unexpected mount")
        mappings = info["NetworkSettings"]["Ports"]["5432/tcp"]
        if len(mappings) != 1 or mappings[0]["HostIp"] != "127.0.0.1":
            raise FixtureError("database port is not exclusively bound to loopback")
        port = int(mappings[0]["HostPort"])
        owner_dsn = make_conninfo(host="127.0.0.1", hostaddr="127.0.0.1", port=port, dbname=self.manifest["database"],
                                 user="fixture_owner", password=self.env.pop("POSTGRES_PASSWORD"), connect_timeout=2, sslmode="disable")
        ready_deadline = min(self.deadline, time.monotonic() + 60)
        while True:
            try:
                connection = psycopg.connect(owner_dsn)
                break
            except psycopg.OperationalError:
                if time.monotonic() >= ready_deadline:
                    raise FixtureError("owned PostgreSQL did not become ready within 60 seconds") from None
                time.sleep(0.2)
        runtime_password = secrets.token_urlsafe(32)
        with connection:
            # Empty schema plus exact database and container ownership are mandatory.
            if connection.execute("SELECT current_database()").fetchone()[0] != self.manifest["database"]:
                raise FixtureError("bootstrap database identity mismatch")
            if connection.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'").fetchone()[0]:
                raise FixtureError("bootstrap refuses an existing schema")
            connection.execute("CREATE TABLE fixture_ownership(singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),run_id text UNIQUE NOT NULL)")
            connection.execute("INSERT INTO fixture_ownership(run_id) VALUES (%s)", (self.run_id,))
            connection.execute((ROOT / "tests/fixtures/vs0-schema.sql").read_text())
            migration = (ROOT / "src/radhouse/storage/migrations/0001_initial.sql").read_bytes()
            connection.execute(migration.decode())
            connection.execute(
                "INSERT INTO radhouse_metadata"
                "(singleton,deployment_id,schema_version,migration_sha256) VALUES (true,%s,1,%s)",
                (f"fixture-{self.run_id}", hashlib.sha256(migration).hexdigest()),
            )
            connection.execute(sql.SQL("CREATE ROLE radhouse_runtime LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT").format(sql.Literal(runtime_password)))
            connection.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(self.manifest["database"])))
            connection.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO radhouse_runtime").format(sql.Identifier(self.manifest["database"])))
            connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            connection.execute("GRANT USAGE ON SCHEMA public TO radhouse_runtime")
            connection.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO radhouse_runtime")
            connection.execute("REVOKE INSERT,UPDATE,DELETE ON fixture_ownership FROM radhouse_runtime")
            connection.execute("REVOKE INSERT,UPDATE,DELETE ON radhouse_metadata FROM radhouse_runtime")
            connection.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO radhouse_runtime")
        self.env.update(RADHOUSE_VS0_DSN=make_conninfo(host="127.0.0.1", hostaddr="127.0.0.1", port=port, dbname=self.manifest["database"],
                        user="radhouse_runtime", password=runtime_password, connect_timeout=3, sslmode="disable"),
                        RADHOUSE_VS0_OWNER_DSN=owner_dsn,
                        RADHOUSE_VS0_RUN_ID=self.run_id, RADHOUSE_VS0_MANIFEST=str(self.manifest_path),
                        RADHOUSE_VS0_FAKE_TARGET=str(self.output / "target.sqlite3"))
        self.manifest["runtime_role"] = "DML only; ownership marker read-only"
        self.manifest["port_loopback_only"] = True
        self.save()

    def cleanup(self):
        if not self.output.exists():
            return
        retained = []
        # Cleanup has its own short bound, even after the run deadline expires.
        self.deadline = max(self.deadline, time.monotonic() + 45)
        try:
            info = self.inspect_owned()
            if info:
                self.docker("rm", "--force", info["Id"], timeout=15)
        except FixtureError:
            retained.append("container (ownership check or local daemon unavailable)")
        try:
            if self.manifest.get("volume_preexisting"):
                raise FixtureError("preexisting volume must be retained")
            volume = self.docker("volume", "inspect", self.manifest["volume_name"], accepted=(0, 1), timeout=10)
            if volume.returncode == 0:
                info = json.loads(volume.stdout)[0]
                if info.get("Labels", {}).get(LABEL) != self.run_id:
                    raise FixtureError("volume ownership mismatch")
                self.docker("volume", "rm", info["Name"], timeout=10)
        except FixtureError:
            retained.append("volume (ownership check or local daemon unavailable)")
        for suffix in ("", "-wal", "-shm", "-journal"):
            (self.output / ("target.sqlite3" + suffix)).unlink(missing_ok=True)
        self.manifest["cleanup"] = "complete" if not retained else "residual resources"
        self.manifest["residual_resources"] = retained
        self.save()
        if retained:
            print("RESIDUAL: " + "; ".join(retained))


def service_for_environment(env, *, crash=False):
    from radhouse.application.service import Service
    from radhouse.storage.postgres import PostgresStore
    from tests.fakes import FakeAgentWork, FakeProvider, FixedClock
    store = PostgresStore(env["RADHOUSE_VS0_DSN"], env["RADHOUSE_VS0_RUN_ID"])
    target = env["RADHOUSE_VS0_FAKE_TARGET"]
    work = FakeAgentWork(
        target, "lost_reply_after_commit" if crash else "completed",
        crash_after_commit=crash, clock=FixedClock(),
    )
    return Service(store, work, FakeProvider(), FixedClock()), work


def controller_child(action, task_id):
    manifest = json.loads(Path(os.environ["RADHOUSE_VS0_MANIFEST"]).read_text())
    if manifest["run_id"] != os.environ["RADHOUSE_VS0_RUN_ID"] or not manifest.get("container_id"):
        raise FixtureError("child controller fixture ownership mismatch")
    service, _ = service_for_environment(os.environ, crash=action == "run")
    if action == "run":
        service.run(task_id)
    elif action == "recover":
        service.recover(task_id)
    else:
        raise FixtureError("invalid child controller action")


def demonstration(run: Run):
    from fastapi.testclient import TestClient
    from radhouse.api.app import create_app
    from radhouse.domain.access import AuthContext
    from radhouse.domain.tasks import StartTask
    from tests.conftest import seed_fixture
    from tests.fakes import FixedClock, SimulatedChannelDriver, make_envelope

    service, work = service_for_environment(run.env)
    with service.store.transaction():
        pass
    seed_fixture(run.env["RADHOUSE_VS0_DSN"])
    clock = FixedClock()
    for index, (source, destination) in enumerate((("radhouse", "buzz"), ("buzz", "radhouse")), 1):
        def client_for(channel):
            actor = AuthContext("alice", channel, f"alice@{channel}", clock() + timedelta(minutes=10))
            return TestClient(create_app(service, authenticate=lambda request: actor))
        with client_for(source) as source_client, client_for(destination) as destination_client:
            sender, receiver = SimulatedChannelDriver(source_client, source), SimulatedChannelDriver(destination_client, destination)
            admission = make_envelope(source, project_id="project-shared")
            start = StartTask("bot-beta", "project-shared", "Prepare the synthetic offline report.", "fake-local")
            response = sender.admit(admission, start)
            if response.status_code not in (200, 201):
                raise FixtureError("demo admission failed")
            task = response.json()
            task_id = task["task_id"]
            duplicate = sender.admit(admission, start)
            if duplicate.json()["task_id"] != task_id:
                raise FixtureError("duplicate admission created another task")
            print(f"TRACE channel={source} task={task_id} attempt=none state={task['phase']} decision=admitted runs={work.start_count}")
            run.command([sys.executable, str(Path(__file__)), "_controller", "run", task_id], env=run.env, accepted=(73,))
            run.command([sys.executable, str(Path(__file__)), "_controller", "recover", task_id], env=run.env)
            envelope = make_envelope(destination, project_id="project-shared")
            current = receiver.get(task_id, envelope)
            if current.status_code != 200:
                raise FixtureError("reverse-channel task read failed")
            task = current.json()
            if task["outcome"] != "completed" or work.start_count != index:
                raise FixtureError("fresh-process recovery did not confirm exactly one agent run")
            reviewed = receiver.review(task_id, envelope, expected_state_revision=task["state_revision"], audience=["alice", "bob"])
            if reviewed.status_code not in (200, 201):
                raise FixtureError("reverse-channel protected review failed")
            review = reviewed.json()
            released = receiver.publish(review["review_id"], make_envelope(destination, project_id="project-shared"),
                expected_revision=review["revision"], content=task["result"], audience=["alice", "bob"])
            if released.status_code not in (200, 201):
                raise FixtureError("reverse-channel protected publication failed")
            print(f"TRACE channel={destination} task={task_id} attempt={task['attempt_id']} state={task['phase']} decision=published runs={work.start_count}")
    # Missing runtime evidence stays blocked and never becomes permission for a new run.
    from tests.fakes import FakeAgentWork
    actor = AuthContext("alice", "radhouse", "alice@radhouse", clock() + timedelta(minutes=10))
    uncertain = service.admit(actor, make_envelope(), StartTask("bot-alpha", "personal-alice", "Synthetic unknown run.", "fake-local"))
    service.work = FakeAgentWork(run.env["RADHOUSE_VS0_FAKE_TARGET"], "unknown", clock=clock)
    service.run(uncertain.task_id)
    blocked = service.recover(uncertain.task_id)
    if "operation_unknown" not in blocked.blockers or work.start_count != 3:
        raise FixtureError("missing runtime evidence was incorrectly treated as a new run")
    print(f"TRACE channel=radhouse task={blocked.task_id} attempt={blocked.attempt_id} state={blocked.phase} decision=needs_attention runs={work.start_count}")
    run.manifest["demonstration"] = {"channel_directions": 2, "fresh_controller_recoveries": 2,
                                     "unknown_runtime_not_redispatched": True,
                                     "agent_runs": work.start_count}
    run.save()
    print("PASS: both simulated channel directions, duplicate admission, separate-process recovery, one run per completed task, protected publication, unknown runtime stays blocked")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("verify", "demo"))
    args = parser.parse_args()
    run = Run()
    def deadline_expired(signum, frame):
        raise FixtureError("VS0 reached its 15-minute execution limit")
    signal.signal(signal.SIGALRM, deadline_expired)
    signal.alarm(LIMIT_SECONDS)
    succeeded = False
    prerequisite_missing = False
    try:
        run.preflight()
        run.start()
        demonstration(run)
        if args.mode == "verify":
            report = run.output / "pytest.xml"
            result = run.command([sys.executable, "-m", "pytest", "-q", "--tb=short", f"--junitxml={report}"], env=run.env, accepted=(0, 1, 2, 3, 4, 5))
            import xml.etree.ElementTree as ET
            if not report.exists():
                raise FixtureError("pytest did not produce a verification report")
            # Retain test identities/status without captured tracebacks, DSNs or vendor output.
            suites = ET.parse(report).getroot()
            counts = {key: sum(int(node.get(key, "0")) for node in suites.iter("testsuite")) for key in ("tests", "failures", "errors", "skipped")}
            for node in suites.iter():
                if node.tag in {"failure", "error", "system-out", "system-err"}:
                    node.text = "Details omitted from sanitized fixture evidence."
                    node.attrib.pop("message", None)
            ET.ElementTree(suites).write(report, encoding="unicode")
            run.manifest["tests"] = counts
            print("TESTS: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
            if result.returncode != 0 or not counts["tests"] or any(counts[key] for key in ("failures", "errors", "skipped")):
                raise FixtureError("verification requires executed tests with no failures, errors or skips")
        run.manifest["result"] = "passed"
        succeeded = True
    except Exception as exc:
        prerequisite_missing = isinstance(exc, PrerequisiteError)
        run.manifest["result"] = "failed"
        print("FAIL: " + (str(exc) if isinstance(exc, FixtureError) else f"{type(exc).__name__} during local fixture execution; no proof recorded"), file=sys.stderr)
    finally:
        signal.alarm(0)
        run.cleanup()
    if run.output.exists():
        print(f"Sanitized run manifest: {run.manifest_path.relative_to(ROOT)}")
    if succeeded:
        print(f"PASS: offline {args.mode}; Python {run.manifest['python']}; source {run.manifest['source_commit']}; image {run.manifest['image']}")
    return 2 if prerequisite_missing else (0 if succeeded and run.manifest.get("cleanup") == "complete" else 1)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "_controller":
        controller_child(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(main())
