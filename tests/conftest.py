"""Fresh, synthetic state inside the runner's exclusively owned PostgreSQL fixture."""
from __future__ import annotations

from datetime import timedelta
import json
import os
from pathlib import Path
import re

import psycopg
from psycopg import sql
import pytest

from radhouse.application.service import Service
from radhouse.domain.access import AuthContext
from radhouse.domain.tasks import StartTask
from radhouse.storage.postgres import PostgresStore
from tests.fakes import FakeAgentWork, FakeOperations, FakeProvider, FakeRuntime, FixedClock, make_envelope

FIXTURE = Path(__file__).parent / "fixtures" / "vs0.json"


def owned_environment() -> tuple[str, str]:
    """A DSN alone never opts an arbitrary database into the fixture suite."""
    run_id = os.environ.get("RADHOUSE_VS0_RUN_ID", "")
    manifest_path = os.environ.get("RADHOUSE_VS0_MANIFEST", "")
    dsn = os.environ.get("RADHOUSE_VS0_DSN", "")
    if not run_id or not manifest_path or not dsn:
        pytest.skip("PostgreSQL evidence requires the owned fixture: uv run python scripts/vs0.py verify")
    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise RuntimeError("invalid VS0 run ownership")
    manifest = json.loads(Path(manifest_path).read_text())
    if manifest.get("run_id") != run_id or manifest.get("database") != f"radhouse_vs0_{run_id}" or not manifest.get("container_id"):
        raise RuntimeError("missing VS0 fixture ownership")
    return dsn, run_id


def seed_fixture(dsn: str) -> None:
    """DML only. Store verifies the database and marker before this is called."""
    data = json.loads(FIXTURE.read_text())
    with psycopg.connect(dsn) as connection:
        # Reverse FK order from the fixture schema. No schema/role authority is used.
        for table in ("local_sessions", "local_login_throttles", "local_credentials", "events", "deliveries", "commands", "publications", "reviews", "agent_dispatches", "operations", "budget_reservations", "claims", "task_revisions", "attempts", "tasks", "channel_bindings", "project_members", "bot_grants", "bots", "projects", "actors"):
            connection.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier("public", table)))
        for bot in data["bots"]:
            connection.execute(
                "INSERT INTO bots(bot_id,display_name,role_name,provider_binding,state) "
                "VALUES (%s,%s,%s,%s,%s)",
                (bot["bot_id"], bot["display_name"], bot["role_name"],
                 bot["provider_binding"], bot["state"]),
            )
        for principal in data["principals"]:
            pid = principal["id"]
            connection.execute("INSERT INTO actors(principal_id,role) VALUES (%s,%s)", (pid, principal["role"]))
        for project in data["projects"]:
            connection.execute(
                "INSERT INTO projects(project_id,owner_id,display_name,state) VALUES (%s,%s,%s,%s)",
                (project["project_id"], project["owner_id"], project["display_name"], project["state"]),
            )
        for principal in data["principals"]:
            pid = principal["id"]
            for bot in principal["bots"]:
                connection.execute("INSERT INTO bot_grants(principal_id,bot_id) VALUES (%s,%s)", (pid, bot))
            for project in principal["projects"]:
                connection.execute("INSERT INTO project_members(principal_id,project_id) VALUES (%s,%s)", (pid, project))
                for channel in data["channels"]:
                    connection.execute("""INSERT INTO channel_bindings(channel,subject,conversation_id,principal_id,project_id,revision)
                        VALUES (%s,%s,%s,%s,%s,1)""", (channel, f"{pid}@{channel}", f"{project}:{pid}:{channel}", pid, project))


@pytest.fixture
def store():
    dsn, run_id = owned_environment()
    result = PostgresStore(dsn, run_id)
    with result.transaction():
        pass  # Validate exact owned DB/marker before any fixture DML.
    seed_fixture(dsn)
    return result


@pytest.fixture
def clock():
    return FixedClock()


@pytest.fixture
def fake_runtime(tmp_path):
    return FakeRuntime(tmp_path / "target.sqlite3")


@pytest.fixture
def fake_provider():
    return FakeProvider()


@pytest.fixture
def fake_operations(tmp_path):
    return FakeOperations(tmp_path / "target.sqlite3")


@pytest.fixture
def fake_work(tmp_path, clock):
    return FakeAgentWork(tmp_path / "target.sqlite3", clock=clock)


@pytest.fixture
def service_factory(store, fake_work, fake_provider, clock):
    def factory(**overrides):
        return Service(overrides.get("store", store), overrides.get("work", fake_work),
                       overrides.get("provider", fake_provider), overrides.get("clock", clock))
    return factory


@pytest.fixture
def service(service_factory):
    return service_factory()


def _actor(principal: str, clock: FixedClock) -> AuthContext:
    return AuthContext(principal, "radhouse", f"{principal}@radhouse", clock() + timedelta(minutes=10))


@pytest.fixture
def alice(clock):
    return _actor("alice", clock)


@pytest.fixture
def bob(clock):
    return _actor("bob", clock)


@pytest.fixture
def viewer(clock):
    return _actor("viewer", clock)


@pytest.fixture
def admin(clock):
    return _actor("admin", clock)


@pytest.fixture
def envelope():
    return make_envelope


@pytest.fixture
def start():
    return StartTask("bot-alpha", "personal-alice", "Prepare the synthetic offline report.", "fake-local")
