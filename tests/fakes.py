"""Synthetic ports and channel drivers, never imported by the production package."""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from radhouse.domain.access import AuthContext
from radhouse.domain.tasks import (
    Attempt, EffectResult, LostReply, ProviderDescription, RuntimeCapabilities,
    RuntimeDispatch, RuntimeFailure, RuntimeResult, Task,
)
from radhouse.channels.commands import Envelope


class FixedClock:
    def __init__(self, now: datetime | None = None):
        self.now = now or datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
        if self.now.utcoffset() is None:
            raise ValueError("clock requires an aware UTC time")
        self.now = self.now.astimezone(timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


class _FakeLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.sqlite_path = self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS effects (
                    operation_key TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                    result TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS calls (
                    operation_key TEXT PRIMARY KEY, count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS runtimes (
                    dispatch_key TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL UNIQUE, state TEXT NOT NULL,
                    attach_count INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS agent_runs (
                    dispatch_key TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL UNIQUE, run_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL, provider_binding TEXT NOT NULL,
                    runtime_revision TEXT NOT NULL, submitted_at TEXT NOT NULL,
                    retention_until TEXT NOT NULL, state TEXT NOT NULL,
                    result TEXT, attach_count INTEGER NOT NULL DEFAULT 0);
            """)

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)


class FakeOperations(_FakeLedger):
    """Target receipts commit in SQLite independently of PostgreSQL.

    unknown_without_receipt has no authoritative receipt, so lookup stays unknown.
    lost_reply_after_commit commits exactly one effect before losing its reply.
    crash_after_commit exits a *child controller process* at that same boundary.
    """
    def __init__(self, path: str | Path, mode: str = "confirmed", *, crash_after_commit: bool = False):
        super().__init__(path)
        if mode not in {"confirmed", "lost_reply_after_commit", "unknown_without_receipt"}:
            raise ValueError("unsupported synthetic effect mode")
        self.mode = mode
        self.crash_after_commit = crash_after_commit

    def execute(self, task: Task, operation_key: str) -> EffectResult:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO calls VALUES (?,1) ON CONFLICT(operation_key) DO UPDATE SET count=count+1", (operation_key,))
            row = db.execute("SELECT result FROM effects WHERE operation_key=?", (operation_key,)).fetchone()
            if row:
                return EffectResult("confirmed", row[0])
            if self.mode == "unknown_without_receipt":
                return EffectResult("unknown")
            result = "Synthetic report: the bounded offline task completed."
            db.execute("INSERT INTO effects VALUES (?,?,?)", (operation_key, task.task_id, result))
        if self.crash_after_commit:
            os._exit(73)  # Deliberate fixture-only crash, after SQLite commit.
        if self.mode == "lost_reply_after_commit":
            raise LostReply()
        return EffectResult("confirmed", result)

    def lookup(self, operation_key: str) -> EffectResult:
        with self.connect() as db:
            row = db.execute("SELECT result FROM effects WHERE operation_key=?", (operation_key,)).fetchone()
        return EffectResult("confirmed", row[0]) if row else EffectResult("unknown")

    @property
    def effect_count(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT count(*) FROM effects").fetchone()[0]

    @property
    def execute_count(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT coalesce(sum(count),0) FROM calls").fetchone()[0]


class FakeRuntime(_FakeLedger):
    def start_or_attach(self, task: Task, attempt: Attempt, dispatch_key: str) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT task_id,attempt_id FROM runtimes WHERE dispatch_key=?", (dispatch_key,)).fetchone()
            if row and row != (task.task_id, attempt.attempt_id):
                raise ValueError("dispatch key reused for another attempt")
            db.execute("""INSERT INTO runtimes(dispatch_key,task_id,attempt_id,state) VALUES (?,?,?,'running')
                ON CONFLICT(dispatch_key) DO UPDATE SET attach_count=attach_count+1""",
                (dispatch_key, task.task_id, attempt.attempt_id))

    def stop(self, attempt: Attempt) -> bool:
        with self.connect() as db:
            db.execute("UPDATE runtimes SET state='stopped' WHERE attempt_id=?", (attempt.attempt_id,))
        return True

    def state(self, attempt_id: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT state FROM runtimes WHERE attempt_id=?", (attempt_id,)).fetchone()
        return row[0] if row else None

    @property
    def start_count(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT count(*) FROM runtimes").fetchone()[0]

    @property
    def attach_count(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT coalesce(sum(attach_count),0) FROM runtimes").fetchone()[0]


class FakeAgentWork(_FakeLedger):
    """Durable fake of one agent runtime; results come from the run itself."""

    def __init__(
        self, path: str | Path, mode: str = "completed", *,
        crash_after_commit: bool = False, clock=None,
    ):
        super().__init__(path)
        if mode not in {"completed", "lost_reply_after_commit", "unknown", "running", "failed"}:
            raise ValueError("unsupported synthetic agent-work mode")
        self.mode = mode
        self.crash_after_commit = crash_after_commit
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def capabilities(self, _task: Task) -> RuntimeCapabilities:
        return RuntimeCapabilities("fake-runtime-v1", 86_400)

    def start_or_attach(
        self, task: Task, attempt: Attempt, dispatch_key: str
    ) -> RuntimeDispatch:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT task_id,attempt_id,run_id,session_id,provider_binding,"
                "runtime_revision,submitted_at,retention_until FROM agent_runs "
                "WHERE dispatch_key=?", (dispatch_key,),
            ).fetchone()
            if row is not None:
                if row[:2] != (task.task_id, attempt.attempt_id):
                    raise RuntimeFailure("runtime_dispatch_conflict")
                db.execute(
                    "UPDATE agent_runs SET attach_count=attach_count+1 WHERE dispatch_key=?",
                    (dispatch_key,),
                )
                return RuntimeDispatch(
                    row[2], row[3], row[4], row[5],
                    datetime.fromisoformat(row[6]), datetime.fromisoformat(row[7]),
                )
            submitted_at = self.clock().astimezone(timezone.utc)
            retention_until = submitted_at + timedelta(days=1)
            run_id = "run-" + attempt.attempt_id
            state = {
                "completed": "completed",
                "lost_reply_after_commit": "completed",
                "unknown": "unknown",
                "running": "running",
                "failed": "failed",
            }[self.mode]
            result = (
                "Synthetic report: the bounded offline task completed."
                if state == "completed" else None
            )
            db.execute(
                "INSERT INTO agent_runs(dispatch_key,task_id,attempt_id,run_id,session_id,"
                "provider_binding,runtime_revision,submitted_at,retention_until,state,result) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (dispatch_key, task.task_id, attempt.attempt_id, run_id, task.task_id,
                 task.provider_binding, "fake-runtime-v1", submitted_at.isoformat(),
                 retention_until.isoformat(), state, result),
            )
        if self.crash_after_commit:
            os._exit(73)
        if self.mode == "lost_reply_after_commit":
            raise RuntimeFailure("runtime_lost_reply")
        return RuntimeDispatch(
            run_id, task.task_id, task.provider_binding, "fake-runtime-v1",
            submitted_at, retention_until,
        )

    def result(self, _task: Task, dispatch: RuntimeDispatch) -> RuntimeResult:
        with self.connect() as db:
            row = db.execute(
                "SELECT state,result FROM agent_runs WHERE run_id=?", (dispatch.run_id,),
            ).fetchone()
        if row is None or row[0] == "unknown":
            return RuntimeResult("unknown")
        if row[0] == "running":
            return RuntimeResult("running")
        if row[0] == "cancelled":
            return RuntimeResult("cancelled")
        if row[0] == "failed":
            return RuntimeResult("failed")
        return RuntimeResult("completed", row[1])

    def stop(self, _task: Task, dispatch: RuntimeDispatch) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE agent_runs SET state='cancelled' WHERE run_id=?", (dispatch.run_id,),
            )
        return cursor.rowcount == 1

    def settle(self, dispatch_key: str, state: str = "completed") -> None:
        result = "Synthetic report: the bounded offline task completed." if state == "completed" else None
        with self.connect() as db:
            db.execute(
                "UPDATE agent_runs SET state=?,result=? WHERE dispatch_key=?",
                (state, result, dispatch_key),
            )

    def state(self, dispatch_key: str) -> str | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT state FROM agent_runs WHERE dispatch_key=?", (dispatch_key,),
            ).fetchone()
        return row[0] if row else None

    @property
    def start_count(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT count(*) FROM agent_runs").fetchone()[0]

    @property
    def attach_count(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT coalesce(sum(attach_count),0) FROM agent_runs").fetchone()[0]


class FakeProvider:
    def __init__(self, model_id: str = "model-A", *, available: bool = True, compatible: bool = True):
        self.model_id, self.available, self.compatible = model_id, available, compatible

    def describe(self, binding: str) -> ProviderDescription:
        return ProviderDescription(binding, self.model_id, self.available, self.compatible)


def make_envelope(channel: str = "radhouse", *, event_id: str | None = None,
                  command_key: str | None = None, principal: str = "alice",
                  project_id: str = "personal-alice", binding_revision: int = 1,
                  mirrored: bool = False) -> Envelope:
    return Envelope(channel, event_id or uuid4().hex, f"{project_id}:{principal}:{channel}",
                    binding_revision, command_key or uuid4().hex, mirrored)


def channel_actor(actor: AuthContext, channel: str) -> AuthContext:
    return replace(actor, channel=channel, subject=f"{actor.principal_id}@{channel}")


class SimulatedChannelDriver:
    """Both synthetic UI directions call the same in-process HTTP API."""
    def __init__(self, client, channel: str):
        self.client, self.channel = client, channel

    def admit(self, envelope: Envelope, start):
        return self.client.post("/tasks", json={"envelope": asdict(envelope), "start": asdict(start)})

    def get(self, task_id: str, envelope: Envelope):
        return self.client.get(f"/tasks/{task_id}", params={"conversation_id": envelope.conversation_id, "binding_revision": envelope.binding_revision})

    def review(self, task_id: str, envelope: Envelope, *, expected_state_revision: int, audience: list[str], ttl_seconds: int = 300):
        return self.client.post(f"/tasks/{task_id}/review", json={
            "envelope": asdict(envelope), "expected_state_revision": expected_state_revision, "audience": audience,
            "ttl_seconds": ttl_seconds})

    def publish(self, review_id: str, envelope: Envelope, *, expected_revision: int, content: str, audience: list[str]):
        return self.client.post(f"/reviews/{review_id}/publish", json={"envelope": asdict(envelope),
            "expected_revision": expected_revision, "content": content, "audience": audience})
