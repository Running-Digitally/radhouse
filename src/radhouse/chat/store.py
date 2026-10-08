"""Durable web transcript and run receipts; Hermes owns agent context."""
from contextlib import contextmanager
from pathlib import Path
import os
import sqlite3
import stat
import tempfile
import json
import secrets
from uuid import uuid4

from radhouse.domain.tasks import Rejected
from .attachments import Attachment, FILE_ID, validate_name


BEGIN_WRITE = 'BEGIN IMMEDIATE'
TURN_BY_REQUEST = 'SELECT * FROM turns WHERE owner=? AND request_id=?'
TURN_BY_SEQUENCE = 'SELECT * FROM turns WHERE seq=?'

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
            if version not in (0, 1, 2, 3):
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
                version = 1
            if version == 1:
                db.executescript("""
                    BEGIN IMMEDIATE;
                    ALTER TABLE turns ADD COLUMN input_text TEXT;
                    UPDATE turns SET input_text=text;
                    CREATE TABLE attachments (
                        turn_seq INTEGER NOT NULL REFERENCES turns(seq),
                        position INTEGER NOT NULL, name TEXT NOT NULL,
                        media_type TEXT NOT NULL, kind TEXT NOT NULL,
                        sha256 TEXT NOT NULL, data BLOB NOT NULL,
                        reference_text TEXT, PRIMARY KEY(turn_seq,position)
                    );
                    PRAGMA user_version=2;
                    COMMIT;
                """)

                version = 2
            if version == 2:
                db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE uploads (
                        file_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                        name TEXT NOT NULL, media_type TEXT NOT NULL, kind TEXT NOT NULL,
                        sha256 TEXT NOT NULL, size INTEGER NOT NULL, storage_name TEXT NOT NULL
                    );
                    ALTER TABLE attachments ADD COLUMN file_id TEXT REFERENCES uploads(file_id);
                    ALTER TABLE attachments ADD COLUMN reading_state TEXT;
                    ALTER TABLE attachments ADD COLUMN reading_error TEXT;
                    PRAGMA user_version=3;
                    COMMIT;
                """)
            # Additive metadata keeps schema-3 readers usable for rollback.
            # Legacy positive deadlines may represent an uncertain submission;
            # preserve their original window rather than granting a fresh one.
            db.execute(BEGIN_WRITE)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(turns)")}
            if "first_dispatch_at" not in columns:
                db.execute("ALTER TABLE turns ADD COLUMN first_dispatch_at REAL")
            if "tool_policy" not in columns:
                db.execute("ALTER TABLE turns ADD COLUMN tool_policy TEXT")
            db.execute("UPDATE turns SET first_dispatch_at=created_at WHERE first_dispatch_at IS NULL AND retry_until>0")
            db.execute("""CREATE TABLE IF NOT EXISTS document_grants (
                token TEXT PRIMARY KEY, turn_seq INTEGER UNIQUE NOT NULL REFERENCES turns(seq),
                expires_at REAL NOT NULL, bound_run_id TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS document_grant_files (
                token TEXT NOT NULL REFERENCES document_grants(token), file_id TEXT NOT NULL REFERENCES uploads(file_id),
                sha256 TEXT NOT NULL, PRIMARY KEY(token,file_id))""")
        self.files_path = self.path.with_name(self.path.name + ".files")
        self.files_path.mkdir(mode=0o700, exist_ok=True)
        info = self.files_path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("chat_files_require_private_directory")

    def begin_upload(self, owner, file_id, name):
        if not FILE_ID.fullmatch(file_id): raise Rejected("attachment_invalid", 422)
        validate_name(name)
        with self.connection() as db:
            row = db.execute("SELECT owner,name FROM uploads WHERE file_id=?", (file_id,)).fetchone()
            if row and (row["owner"] != owner or row["name"] != name):
                raise Rejected("attachment_conflict", 409)
        fd, path = tempfile.mkstemp(prefix="upload-", dir=self.files_path)
        return os.fdopen(fd, "wb"), Path(path)

    def commit_upload(self, owner, file_id, name, path, media, kind, sha256, size):
        # The complete immutable file is durable before the DB publishes it.
        # A crash can leave an unpublished file, never a receipt for partial bytes.
        with self.connection() as db:
            db.execute(BEGIN_WRITE)
            row = db.execute("SELECT * FROM uploads WHERE file_id=?", (file_id,)).fetchone()
            if row:
                if (row["owner"], row["name"], row["sha256"], row["size"]) != (owner, name, sha256, size):
                    raise Rejected("attachment_conflict", 409)
            else:
                storage_name = uuid4().hex
                os.replace(path, self.files_path / storage_name)
                directory = os.open(self.files_path, os.O_RDONLY)
                try: os.fsync(directory)
                finally: os.close(directory)
                db.execute("INSERT INTO uploads VALUES(?,?,?,?,?,?,?,?)",
                           (file_id, owner, name, media, kind, sha256, size, storage_name))
        return self.upload(owner, file_id)

    def upload(self, owner, file_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM uploads WHERE owner=? AND file_id=?", (owner, file_id)).fetchone()
            if not row: raise Rejected("attachment_not_found", 404)
            return Attachment(row["name"], row["media_type"], row["kind"], self.files_path / row["storage_name"],
                              file_id=file_id, stored_sha256=row["sha256"], stored_size=row["size"])

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
            row = db.execute(TURN_BY_REQUEST, (owner, request_id)).fetchone()
            return dict(row) if row else None

    def reserve(self, owner, request_id, text, now, attachments=()):
        with self.connection() as db:
            db.execute(BEGIN_WRITE)
            row = db.execute(TURN_BY_REQUEST, (owner, request_id)).fetchone()
            if row:
                self._match(db, row, text, attachments)
                return dict(row)
            if db.execute("SELECT 1 FROM turns WHERE owner=? AND status NOT IN (?,?,?,?)", (owner, *TERMINAL)).fetchone():
                raise Rejected("reply_pending", 409)
            db.execute("INSERT OR IGNORE INTO conversations VALUES (?,?)", (owner, "chat:" + uuid4().hex))
            db.execute("INSERT INTO turns(owner,request_id,text,dispatch_key,created_at,retry_until,status) VALUES(?,?,?,?,?,?,?)",
                       (owner, request_id, text, "chat:" + uuid4().hex, now, 0, "awaiting_dispatch"))
            row = db.execute(TURN_BY_REQUEST, (owner, request_id)).fetchone()
            for i, attachment in enumerate(attachments):
                db.execute("INSERT INTO attachments VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (row["seq"], i, attachment.name, attachment.media_type, attachment.kind,
                     attachment.sha256, b"" if attachment.file_id else attachment.data, attachment.reference_text,
                     attachment.file_id, attachment.reading_state, attachment.reading_error))
            return dict(row)

    def begin_dispatch(self, turn, now, retention):
        with self.connection() as db:
            db.execute(BEGIN_WRITE)
            # Zero is reserved for a positively known, never-attempted turn.
            # Persist before the POST so a lost response cannot renew its window.
            db.execute("UPDATE turns SET first_dispatch_at=?,retry_until=? WHERE seq=? AND first_dispatch_at IS NULL AND retry_until=0",
                       (now, now + retention, turn["seq"]))
            return dict(db.execute(TURN_BY_SEQUENCE, (turn["seq"],)).fetchone())

    def select_tools(self, turn, tools):
        """Freeze exact tool policy once, before any prompt or dispatch is saved."""
        encoded = json.dumps(list(tools), separators=(",", ":"))
        with self.connection() as db:
            db.execute("UPDATE turns SET tool_policy=? WHERE seq=? AND tool_policy IS NULL "
                       "AND input_text IS NULL AND first_dispatch_at IS NULL", (encoded, turn["seq"]))
            return dict(db.execute(TURN_BY_SEQUENCE, (turn["seq"],)).fetchone())

    @staticmethod
    def tools(turn):
        # Legacy saved turns retain their original no-tools behavior on retry.
        return tuple(json.loads(turn["tool_policy"])) if turn.get("tool_policy") is not None else ()

    def browser_run(self, owner):
        with self.connection() as db:
            row = db.execute("SELECT t.*,c.session_id FROM turns t JOIN conversations c USING(owner) "
                "WHERE owner=? AND status NOT IN (?,?,?,?) ORDER BY seq LIMIT 1", (owner, *TERMINAL)).fetchone()
            if row is None:
                return None
            result = dict(row)
            return {key: result[key] for key in ("request_id", "run_id", "session_id", "status")} | {
                "allowed_tools": self.tools(result)}

    def document_grant_for_turn(self, turn):
        """Mint once after the dispatch deadline is durable; scope cannot grow on retry."""
        with self.connection() as db:
            db.execute(BEGIN_WRITE)
            row = db.execute("SELECT * FROM document_grants WHERE turn_seq=?", (turn["seq"],)).fetchone()
            if row is None:
                saved = dict(db.execute(TURN_BY_SEQUENCE, (turn["seq"],)).fetchone())
                if saved["status"] in TERMINAL or saved["retry_until"] <= 0 or (
                        not {"document_search", "document_read"} <= set(self.tools(saved))):
                    raise Rejected("document_access_denied", 403)
                token = secrets.token_urlsafe(32)
                db.execute("INSERT INTO document_grants VALUES(?,?,?,NULL)",
                           (token, saved["seq"], saved["retry_until"]))
                db.execute("""INSERT INTO document_grant_files SELECT DISTINCT ?,u.file_id,u.sha256
                    FROM uploads u JOIN attachments a ON a.file_id=u.file_id JOIN turns t ON t.seq=a.turn_seq
                    WHERE t.owner=? AND u.owner=? AND t.seq<=? AND u.kind IN ('text','document')
                    AND a.sha256=u.sha256""", (token, saved["owner"], saved["owner"], saved["seq"]))
                row = db.execute("SELECT * FROM document_grants WHERE token=?", (token,)).fetchone()
            return row["token"]

    def document_grant(self, token, now):
        with self.connection() as db:
            row = db.execute("""SELECT g.*,t.owner,t.dispatch_key,t.run_id,t.status,t.tool_policy,c.session_id
                FROM document_grants g JOIN turns t ON t.seq=g.turn_seq JOIN conversations c ON c.owner=t.owner
                WHERE g.token=? AND g.expires_at>? AND t.status NOT IN (?,?,?,?)""",
                (token, now, *TERMINAL)).fetchone()
            if row is None:
                raise Rejected("document_access_denied", 403)
            result = dict(row)
            result["files"] = {r["file_id"]: r["sha256"] for r in db.execute(
                "SELECT file_id,sha256 FROM document_grant_files WHERE token=? ORDER BY file_id", (token,))}
            result["allowed_tools"] = self.tools(result)
            return result

    def bind_document_grant(self, token, run_id, session_id, dispatch_key, now):
        with self.connection() as db:
            db.execute(BEGIN_WRITE)
            row = db.execute("""SELECT g.*,t.owner,t.dispatch_key,t.run_id,t.status,c.session_id
                FROM document_grants g JOIN turns t ON t.seq=g.turn_seq JOIN conversations c ON c.owner=t.owner
                WHERE g.token=? AND g.expires_at>? AND t.status NOT IN (?,?,?,?)""",
                (token, now, *TERMINAL)).fetchone()
            if row is None or row["session_id"] != session_id or row["dispatch_key"] != dispatch_key or (
                    row["bound_run_id"] not in (None, run_id) or row["run_id"] not in (None, run_id)):
                raise Rejected("document_access_denied", 403)
            db.execute("UPDATE document_grants SET bound_run_id=? WHERE token=?", (run_id, token))
            # Live corroboration also recovers a lost acknowledgment, without redispatch.
            db.execute("UPDATE turns SET run_id=?,status='running' WHERE seq=? AND run_id IS NULL",
                       (run_id, row["turn_seq"]))

    @staticmethod
    def _match(db, row, text, attachments):
        saved = db.execute("SELECT name,media_type,sha256,file_id FROM attachments WHERE turn_seq=? ORDER BY position", (row["seq"],)).fetchall()
        if row["text"] != text or [tuple(a) for a in saved] != [a.identity() for a in attachments]:
            raise Rejected("message_conflict", 409)

    def match(self, turn, text, attachments):
        with self.connection() as db:
            self._match(db, turn, text, attachments)

    def attachments(self, owner, request_id):
        with self.connection() as db:
            rows = db.execute("SELECT a.*,u.storage_name,u.size FROM attachments a LEFT JOIN uploads u ON u.file_id=a.file_id JOIN turns t ON t.seq=a.turn_seq WHERE t.owner=? AND t.request_id=? ORDER BY position", (owner, request_id)).fetchall()
            return tuple(self._attachment(r) for r in rows)

    def _attachment(self, row):
        data = self.files_path / row["storage_name"] if row["file_id"] else row["data"]
        return Attachment(row["name"], row["media_type"], row["kind"], data, row["reference_text"],
                          row["file_id"], row["sha256"], row["size"], row["reading_state"], row["reading_error"])

    def attachment(self, owner, request_id, position):
        with self.connection() as db:
            row = db.execute("SELECT a.*,u.storage_name,u.size FROM attachments a LEFT JOIN uploads u ON u.file_id=a.file_id JOIN turns t ON t.seq=a.turn_seq WHERE t.owner=? AND t.request_id=? AND a.position=?", (owner, request_id, position)).fetchone()
            if not row: raise Rejected("attachment_not_found", 404)
            return self._attachment(row)

    def cache_reference(self, turn, position, text, state="excerpt", error=None):
        with self.connection() as db:
            db.execute("UPDATE attachments SET reference_text=?,reading_state=?,reading_error=? WHERE turn_seq=? AND position=? AND reading_state IS NULL", (text, state, error, turn["seq"], position))

    def freeze_input(self, turn, text):
        with self.connection() as db:
            db.execute("UPDATE turns SET input_text=? WHERE seq=? AND input_text IS NULL", (text, turn["seq"]))
            return db.execute("SELECT input_text FROM turns WHERE seq=?", (turn["seq"],)).fetchone()[0]

    def preparation_failed(self, turn, error):
        with self.connection() as db:
            db.execute("UPDATE turns SET status='failed',error=? WHERE seq=? AND run_id IS NULL AND status='awaiting_dispatch'", (error,turn["seq"]))

    def session_id(self, owner):
        with self.connection() as db:
            return db.execute("SELECT session_id FROM conversations WHERE owner=?", (owner,)).fetchone()[0]

    def attach(self, turn, run_id, status):
        with self.connection() as db:
            db.execute(BEGIN_WRITE)
            row = db.execute(TURN_BY_SEQUENCE, (turn["seq"],)).fetchone()
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
            for turn in page:
                rows = db.execute("SELECT position,a.name,a.media_type,a.kind,coalesce(u.size,length(a.data)) AS size,CASE WHEN a.kind='audio' THEN reference_text END AS reference_text,reading_state,reading_error FROM attachments a LEFT JOIN uploads u ON u.file_id=a.file_id WHERE turn_seq=? ORDER BY position", (turn["seq"],)).fetchall()
                turn["attachments"] = [{"position":a["position"], "name":a["name"], "media_type":a["media_type"], "kind":a["kind"], "size":a["size"],
                    "transcript":a["reference_text"] if a["kind"] == "audio" else None,
                    "reading_state":a["reading_state"], "reading_error":a["reading_error"]} for a in rows]
            return {"turns": page, "older_before": page[0]["seq"] if more else None}
