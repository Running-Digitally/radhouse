"""Synthetic ports and channel drivers, never imported by the production package."""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from radhouse.domain.access import AuthContext
from radhouse.domain.tasks import Attempt, EffectResult, LostReply, ProviderDescription, Task
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
