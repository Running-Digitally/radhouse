"""Durable, session-bound reply notifications. No provider credentials or chat text."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
import math
from pathlib import Path
import re
import sqlite3
import stat
import time
from typing import Callable, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from cryptography.fernet import Fernet

from radhouse.domain.tasks import Rejected


BEGIN_WRITE = "BEGIN IMMEDIATE"
DAY = 86400
MAX_DEVICES = 16


@dataclass(frozen=True)
class PushBinding:
    principal_id: str
    conversation_id: str
    binding_revision: int
    session_hash: str
    expires_at: float


@dataclass(frozen=True)
class PushResult:
    outcome: Literal["sent", "retry", "invalid", "blocked"]
    retry_after: int = 60


def installation_id(value: str) -> str:
    try:
        parsed = UUID(value)
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        raise Rejected("invalid_push_installation", 422) from None
    return value


def notification(owner: str, request_id: str, kind="reply_ready") -> dict[str, str]:
    """Stable event identity makes retries deduplicable on the handset."""
    if kind == "commitment_ready":
        return {"version": "2", "kind": kind, "item_id": request_id,
                "event_id": str(uuid5(NAMESPACE_URL, f"radhouse:commitment:{owner}:{request_id}"))}
    if kind != "reply_ready":
        raise ValueError("unsupported_notification_kind")
    return {"version": "1", "kind": "reply_ready", "request_id": request_id,
            "event_id": str(uuid5(NAMESPACE_URL, f"radhouse:reply:{owner}:{request_id}"))}


class PushOutbox:
    """A separate private database keeps provider latency off the chat write lock.

    Dispatch holds this database's write lock through the bounded provider call.
    Rotation/opt-out therefore serialize with dispatch across worker processes.
    Revocation cannot recall a notification already accepted by the provider.
    """
    def __init__(self, path: Path, encryption_key: str, *, clock: Callable[[], float] = time.time):
        self.path = Path(path).absolute()
        self.cipher = Fernet(encryption_key.encode("ascii"))
        self.clock = clock
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("push_store_requires_private_regular_file") from None
        else:
            os.close(fd)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise ValueError("push_schema_mismatch")
                db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE devices (
                        installation TEXT PRIMARY KEY, owner TEXT NOT NULL,
                        conversation TEXT NOT NULL, revision INTEGER NOT NULL,
                        session_hash TEXT NOT NULL, expires_at REAL NOT NULL,
                        platform TEXT NOT NULL, token BLOB NOT NULL, token_hash TEXT UNIQUE NOT NULL,
                        generation INTEGER NOT NULL, start_seq INTEGER NOT NULL,
                        active INTEGER NOT NULL, updated_at REAL NOT NULL);
                    CREATE TABLE deliveries (
                        installation TEXT NOT NULL REFERENCES devices(installation) ON DELETE CASCADE,
                        request_id TEXT NOT NULL, event_id TEXT NOT NULL,
                        generation INTEGER NOT NULL, state TEXT NOT NULL,
                        attempts INTEGER NOT NULL, due_at REAL NOT NULL,
                        expires_at REAL NOT NULL, created_at REAL NOT NULL,
                        PRIMARY KEY(installation,event_id));
                    CREATE INDEX push_due ON deliveries(state,due_at);
                    PRAGMA user_version=1;
                    COMMIT;
                """)
            elif version not in (1, 2):
                raise ValueError("push_schema_mismatch")
            db.execute(BEGIN_WRITE)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(devices)")}
            if "commitments_since" not in columns:
                db.execute("ALTER TABLE devices ADD COLUMN commitments_since REAL")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(deliveries)")}
            if "kind" not in columns:
                db.execute("ALTER TABLE deliveries ADD COLUMN kind TEXT NOT NULL DEFAULT 'reply_ready'")
            db.execute("PRAGMA user_version=2")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def register(self, installation: str, binding: PushBinding, platform: str, token: str,
                 *, latest_seq: int, commitments=False):
        installation_id(installation)
        if (type(commitments) is not bool or platform not in {"ios", "android"} or not isinstance(token, str)
                or not re.fullmatch(r"[A-Za-z0-9_:.-]{20,4096}", token)
                or not re.fullmatch(r"[a-f0-9]{64}", binding.session_hash)
                or not math.isfinite(binding.expires_at) or binding.expires_at <= self.clock()
                or type(binding.binding_revision) is not int or binding.binding_revision < 1
                or type(latest_seq) is not int or latest_seq < 0):
            raise Rejected("invalid_push_registration", 422)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        scope = (binding.principal_id, binding.conversation_id, binding.binding_revision, binding.session_hash)
        with self.connection() as db:
            db.execute(BEGIN_WRITE)
            old = db.execute("SELECT * FROM devices WHERE installation=?", (installation,)).fetchone()
            self._admit_registration(db, old, installation, binding.principal_id, token_hash, self.clock())
            same = old is not None and old["active"] and tuple(old[k] for k in
                ("owner", "conversation", "revision", "session_hash")) == scope
            generation = old["generation"] + 1 if old else 1
            start = old["start_seq"] if same else latest_seq
            since = None
            if commitments:
                since = old["commitments_since"] if same and old["commitments_since"] is not None else self.clock()
            db.execute("""INSERT INTO devices VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(installation) DO UPDATE SET
                conversation=excluded.conversation, revision=excluded.revision,
                session_hash=excluded.session_hash, expires_at=excluded.expires_at,
                platform=excluded.platform, token=excluded.token, token_hash=excluded.token_hash,
                generation=excluded.generation, start_seq=excluded.start_seq,
                active=1, updated_at=excluded.updated_at, commitments_since=excluded.commitments_since""",
                (installation, *scope, binding.expires_at, platform, self.cipher.encrypt(token.encode()),
                 token_hash, generation, start, 1, self.clock(), since))
            # Rotation retargets only unsent work. A new session cannot inherit it.
            db.execute("UPDATE deliveries SET generation=?,state=? WHERE installation=? AND state='pending'",
                (generation, "pending" if same else "discarded", installation))
            if not commitments:
                db.execute("UPDATE deliveries SET state='discarded' WHERE installation=? AND kind='commitment_ready' AND state='pending'", (installation,))

    @staticmethod
    def _admit_registration(db, old, installation, owner, token_hash, now):
        if old and old["owner"] != owner:
            raise Rejected("push_installation_conflict", 409)
        existing = db.execute("SELECT installation FROM devices WHERE token_hash=?", (token_hash,)).fetchone()
        if existing and existing["installation"] != installation:
            raise Rejected("push_token_conflict", 409)
        count = db.execute("SELECT count(*) FROM devices WHERE owner=? AND active=1 AND expires_at>?",
                           (owner, now)).fetchone()[0]
        if count >= MAX_DEVICES and (old is None or not old["active"] or old["expires_at"] <= now):
            raise Rejected("push_device_limit", 409)

    def unregister(self, installation: str, owner: str, session_hash: str):
        installation_id(installation)
        with self.connection() as db:
            db.execute(BEGIN_WRITE)
            db.execute("DELETE FROM devices WHERE installation=? AND owner=? AND session_hash=?",
                       (installation, owner, session_hash))

    def reconcile(self, chat_store, owner: str):
        """Re-read durable completion, including out-of-order completions after crashes.

        Consent covers requests submitted after registration. Existing history is
        never replayed. Only the latest day of submitted requests is eligible.
        """
        now = self.clock()
        with self.connection() as db:
            db.execute(BEGIN_WRITE)
            db.execute("UPDATE deliveries SET state='expired' WHERE state='pending' AND expires_at<=?", (now,))
            db.execute("DELETE FROM deliveries WHERE created_at<?", (now - 30 * DAY,))
            db.execute("DELETE FROM devices WHERE updated_at<? AND expires_at<=?", (now - 30 * DAY, now))
            start = db.execute("SELECT min(start_seq) FROM devices WHERE owner=? AND active=1 AND expires_at>?",
                               (owner, now)).fetchone()[0]
        if start is None:
            return
        # Keyset batches bound memory while preserving every eligible completion.
        # Pending earlier requests are reconsidered from the consent floor next pass.
        while True:
            with chat_store.connection() as chat:
                turns = chat.execute("""SELECT seq,request_id FROM turns WHERE owner=? AND seq>?
                    AND created_at>=? AND status='completed' ORDER BY seq LIMIT 256""",
                    (owner, start, now - DAY)).fetchall()
            if not turns:
                return
            self._enqueue(owner, turns, now)
            start = turns[-1]["seq"]

    def _enqueue(self, owner, turns, now):
        with self.connection() as db:
            db.execute(BEGIN_WRITE)
            devices = db.execute("SELECT * FROM devices WHERE owner=? AND active=1 AND expires_at>?",
                                 (owner, now)).fetchall()
            for device in devices:
                for turn in turns:
                    if turn["seq"] <= device["start_seq"]:
                        continue
                    payload = notification(owner, turn["request_id"])
                    db.execute("INSERT OR IGNORE INTO deliveries(installation,request_id,event_id,generation,state,attempts,due_at,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (device["installation"], turn["request_id"], payload["event_id"], device["generation"],
                         "pending", 0, now, min(now + 3600, device["expires_at"]), now))

    def enqueue_commitments(self, owner, items):
        """Only explicitly capable/opted-in devices; never replay pre-consent items."""
        now = self.clock()
        with self.connection() as db:
            db.execute(BEGIN_WRITE)
            devices = db.execute("SELECT * FROM devices WHERE owner=? AND active=1 AND expires_at>? AND commitments_since IS NOT NULL",
                                 (owner, now)).fetchall()
            admitted = {row[0] for row in db.execute("SELECT DISTINCT q.event_id FROM deliveries q JOIN devices d USING(installation) WHERE q.kind='commitment_ready' AND q.created_at>? AND d.owner=?", (now - DAY, owner))}
            for item in items:
                payload = notification(owner, item["id"], "commitment_ready")
                if "event_id" in item:
                    payload["event_id"] = str(UUID(item["event_id"]))
                if payload["event_id"] not in admitted and len(admitted) >= 2:
                    continue
                for device in devices:
                    if item["created_at"] < device["commitments_since"] or item["created_at"] + DAY <= now:
                        continue
                    db.execute("INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (device["installation"], item["id"], payload["event_id"], device["generation"],
                         "pending", 0, now, min(item["created_at"] + DAY, device["expires_at"]), now, "commitment_ready"))
                    admitted.add(payload["event_id"])

    def dispatch_one(self, authorize: Callable[[PushBinding], bool], send: Callable, *, commitment_decision=None) -> bool:
        """The authorizer reads current session/actor/binding without extending expiry.

        Provider/auth failures retain a sanitized bounded retry. An uncertain send
        may be repeated after a crash, always with the same event/collapse ID.
        """
        now = self.clock()
        with self.connection() as db:
            db.execute(BEGIN_WRITE)
            item = db.execute("""SELECT q.*, d.owner,d.conversation,d.revision,d.session_hash,
                d.expires_at AS session_expiry,d.token,d.platform,d.active,d.generation AS current_generation,d.commitments_since
                FROM deliveries q JOIN devices d USING(installation)
                WHERE q.state='pending' AND q.due_at<=? ORDER BY q.due_at,q.created_at LIMIT 1""", (now,)).fetchone()
            if item is None:
                return False
            if (not item["active"] or item["generation"] != item["current_generation"]
                    or min(item["expires_at"], item["session_expiry"]) <= now):
                self._finish(db, item, "discarded")
                return True
            binding = PushBinding(item["owner"], item["conversation"], item["revision"],
                                  item["session_hash"], item["session_expiry"])
            try:
                if not authorize(binding):
                    self._deactivate(db, item)
                    return True
                if self._defer_commitment(db, item, commitment_decision, now):
                    return True
                payload = notification(item["owner"], item["request_id"], item["kind"])
                payload["event_id"] = item["event_id"]
                result = send(self.cipher.decrypt(item["token"]).decode(), item["platform"], payload)
            except Exception:
                # Provider exceptions may contain registration tokens. Never log them.
                result = PushResult("retry")
            if result.outcome == "invalid":
                self._deactivate(db, item)
            elif result.outcome in {"sent", "blocked"}:
                self._finish(db, item, result.outcome)
            else:
                attempts = item["attempts"] + 1
                delay = max(60 * 2 ** (attempts - 1), min(3600, result.retry_after))
                state = "exhausted" if attempts >= 5 or now + delay >= item["expires_at"] else "pending"
                db.execute("UPDATE deliveries SET attempts=?,due_at=?,state=? WHERE installation=? AND event_id=?",
                    (attempts, now + delay, state, item["installation"], item["event_id"]))
            return True

    def _defer_commitment(self, db, item, decide, now):
        if item["kind"] != "commitment_ready":
            return False
        decision = decide(item["request_id"], event_id=item["event_id"]) if decide and item["commitments_since"] is not None else "discard"
        if decision == "allow":
            return False
        if decision == "hold":
            db.execute("UPDATE deliveries SET due_at=? WHERE installation=? AND event_id=?",
                       (now + 60, item["installation"], item["event_id"]))
        else:
            self._finish(db, item, "discarded")
        return True

    @staticmethod
    def _finish(db, item, state):
        db.execute("UPDATE deliveries SET state=? WHERE installation=? AND event_id=?",
                   (state, item["installation"], item["event_id"]))

    @staticmethod
    def _deactivate(db, item):
        db.execute("UPDATE devices SET active=0,token=X'' WHERE installation=?", (item["installation"],))
        db.execute("UPDATE deliveries SET state='discarded' WHERE installation=? AND state='pending'",
                   (item["installation"],))
