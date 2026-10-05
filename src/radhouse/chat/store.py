"""Durable web transcript and run receipts; Hermes owns agent context."""
from contextlib import contextmanager
from pathlib import Path
import os
import sqlite3
import stat
from uuid import uuid4

from radhouse.domain.tasks import Rejected

TERMINAL = ("completed", "failed", "cancelled", "interrupted")


class ChatStore:
    def __init__(self, path: Path):
        self.path = Path(path).absolute()
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("chat_store_requires_private_regular_file") from None
        else:
            os.close(fd)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("chat_schema_mismatch")
            if version == 0:
                if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise ValueError("chat_schema_mismatch")
                db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE conversations (
                        owner TEXT PRIMARY KEY, session_id TEXT UNIQUE NOT NULL
                    );
                    CREATE TABLE turns (
                        seq INTEGER PRIMARY KEY AUTOINCREMENT,
                        owner TEXT NOT NULL REFERENCES conversations(owner),
                        request_id TEXT NOT NULL, text TEXT NOT NULL,
                        dispatch_key TEXT UNIQUE NOT NULL,
                        created_at REAL NOT NULL, retry_until REAL NOT NULL,
                        run_id TEXT, status TEXT NOT NULL, output TEXT, error TEXT,
                        UNIQUE(owner,request_id)
                    );
                    CREATE INDEX turns_owner ON turns(owner,seq);
                    PRAGMA user_version=1;
                    COMMIT;
                """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def find(self, owner, request_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM turns WHERE owner=? AND request_id=?", (owner, request_id)).fetchone()
            return dict(row) if row else None

    def reserve(self, owner, request_id, text, now, retention):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM turns WHERE owner=? AND request_id=?", (owner, request_id)).fetchone()
            if row:
                if row["text"] != text:
                    raise Rejected("message_conflict", 409)
                return dict(row)
            if db.execute("SELECT 1 FROM turns WHERE owner=? AND status NOT IN (?,?,?,?)", (owner, *TERMINAL)).fetchone():
                raise Rejected("reply_pending", 409)
            db.execute("INSERT OR IGNORE INTO conversations VALUES (?,?)", (owner, "chat:" + uuid4().hex))
            db.execute("INSERT INTO turns(owner,request_id,text,dispatch_key,created_at,retry_until,status) VALUES(?,?,?,?,?,?,?)",
                       (owner, request_id, text, "chat:" + uuid4().hex, now, now + retention, "awaiting_dispatch"))
            return dict(db.execute("SELECT * FROM turns WHERE owner=? AND request_id=?", (owner, request_id)).fetchone())

    def session_id(self, owner):
        with self.connection() as db:
            return db.execute("SELECT session_id FROM conversations WHERE owner=?", (owner,)).fetchone()[0]

    def attach(self, turn, run_id, status):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM turns WHERE seq=?", (turn["seq"],)).fetchone()
            if row["run_id"] is not None and row["run_id"] != run_id:
                raise Rejected("runtime_identity_changed", 503)
            if row["status"] not in TERMINAL:
                db.execute("UPDATE turns SET run_id=?,status=?,error=NULL WHERE seq=?", (run_id, status, turn["seq"]))

    def pending(self, owner):
        with self.connection() as db:
            row = db.execute("SELECT * FROM turns WHERE owner=? AND status NOT IN (?,?,?,?) ORDER BY seq LIMIT 1", (owner, *TERMINAL)).fetchone()
            return dict(row) if row else None

    def observe(self, turn, status, output=None, error=None):
        with self.connection() as db:
            db.execute("UPDATE turns SET status=?,output=?,error=? WHERE seq=? AND run_id=? AND status NOT IN (?,?,?,?)",
                       (status, output, error, turn["seq"], turn["run_id"], *TERMINAL))

    def note_error(self, turn, error):
        with self.connection() as db:
            db.execute("UPDATE turns SET error=? WHERE seq=? AND status NOT IN (?,?,?,?)", (error, turn["seq"], *TERMINAL))

    def history(self, owner, before=None, limit=50):
        with self.connection() as db:
            rows = db.execute("SELECT seq,request_id,text,status,output,error,created_at FROM turns WHERE owner=? AND (? IS NULL OR seq<?) ORDER BY seq DESC LIMIT ?",
                              (owner, before, before, limit + 1)).fetchall()
            more = len(rows) > limit
            page = [dict(row) for row in reversed(rows[:limit])]
            return {"turns": page, "older_before": page[0]["seq"] if more else None}
