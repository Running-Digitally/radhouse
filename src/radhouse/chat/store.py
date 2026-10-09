"""Durable web transcript and run receipts; Hermes owns agent context."""
from contextlib import contextmanager
from pathlib import Path
import base64
import hashlib
import os
import sqlite3
import stat
import tempfile
import json
import secrets
from uuid import NAMESPACE_URL, uuid4, uuid5

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
            if "browser_context" not in columns:
                db.execute("ALTER TABLE turns ADD COLUMN browser_context TEXT")
            if "request_options" not in columns:
                db.execute("ALTER TABLE turns ADD COLUMN request_options TEXT")
            db.execute("UPDATE turns SET first_dispatch_at=created_at WHERE first_dispatch_at IS NULL AND retry_until>0")
            db.execute("""CREATE TABLE IF NOT EXISTS document_grants (
                token TEXT PRIMARY KEY, turn_seq INTEGER UNIQUE NOT NULL REFERENCES turns(seq),
                expires_at REAL NOT NULL, bound_run_id TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS document_grant_files (
                token TEXT NOT NULL REFERENCES document_grants(token), file_id TEXT NOT NULL REFERENCES uploads(file_id),
                sha256 TEXT NOT NULL, PRIMARY KEY(token,file_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS assistant_files (
                file_id TEXT PRIMARY KEY REFERENCES uploads(file_id),
                turn_seq INTEGER NOT NULL REFERENCES turns(seq))""")
            db.execute("""CREATE TABLE IF NOT EXISTS agent_profiles (
                owner TEXT PRIMARY KEY, revision INTEGER NOT NULL CHECK(revision>0),
                profile TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS uploads_owner ON uploads(owner)")
            db.execute("CREATE INDEX IF NOT EXISTS attachments_file ON attachments(file_id,turn_seq,position)")
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

    def share_file(self, token, run_id, session_id, dispatch_key, name, data, *, clock, before_publish):
        """Publish UTF-8 output once, after the bridge corroborates the live run.

        The saved grant is checked again in the same transaction that publishes
        the file and its assistant association. No upload grants grow here.
        """
        validate_name(name)
        digest = hashlib.sha256(data).hexdigest()
        file_id = str(uuid5(NAMESPACE_URL, json.dumps(
            ["radhouse.shared-file.v1", run_id, name, digest], separators=(",", ":"))))
        stream, path = self.begin_upload(self.document_grant(token, clock())["owner"], file_id, name)
        try:
            with stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # Runtime corroboration stays outside the SQLite write lock.
            before_publish()
            with self.connection() as db:
                db.execute(BEGIN_WRITE)
                grant = db.execute("""SELECT g.*,t.owner,t.dispatch_key,t.run_id,t.status,t.tool_policy,c.session_id
                    FROM document_grants g JOIN turns t ON t.seq=g.turn_seq JOIN conversations c ON c.owner=t.owner
                    WHERE g.token=? AND g.expires_at>? AND t.status NOT IN (?,?,?,?)""",
                    (token, clock(), *TERMINAL)).fetchone()
                if (grant is None or grant["run_id"] != run_id or grant["bound_run_id"] != run_id
                        or grant["session_id"] != session_id or grant["dispatch_key"] != dispatch_key
                        or not {"document_search", "document_read", "file_share"} <= set(self.tools(dict(grant)))):
                    raise Rejected("document_access_denied", 403)
                row = db.execute("""SELECT u.*,s.turn_seq FROM uploads u
                    LEFT JOIN assistant_files s USING(file_id) WHERE u.file_id=?""", (file_id,)).fetchone()
                if row:
                    if (row["owner"], row["name"], row["sha256"], row["size"], row["turn_seq"],
                            row["media_type"], row["kind"]) != (
                            grant["owner"], name, digest, len(data), grant["turn_seq"], "text/plain", "text"):
                        raise Rejected("attachment_conflict", 409)
                else:
                    storage_name = uuid4().hex
                    os.replace(path, self.files_path / storage_name)
                    directory = os.open(self.files_path, os.O_RDONLY)
                    try: os.fsync(directory)
                    finally: os.close(directory)
                    db.execute("INSERT INTO uploads VALUES(?,?,?,?,?,?,?,?)",
                        (file_id, grant["owner"], name, "text/plain", "text", digest, len(data), storage_name))
                    db.execute("INSERT INTO assistant_files VALUES(?,?)", (file_id, grant["turn_seq"]))
                result = self._shared_file(db, file_id)
            return result
        finally:
            path.unlink(missing_ok=True)

    @staticmethod
    def _shared_file(db, file_id):
        row = db.execute("""SELECT u.*,t.request_id,t.created_at FROM uploads u
            JOIN assistant_files s USING(file_id) JOIN turns t ON t.seq=s.turn_seq
            WHERE u.file_id=?""", (file_id,)).fetchone()
        return {"id": "file:" + file_id, "file_id": file_id, "name": row["name"],
            "size": row["size"], "kind": row["kind"], "media_type": row["media_type"],
            "source": "assistant", "request_id": row["request_id"], "position": None,
            "download_url": "/chat/files/" + file_id + "/content", "created_at": row["created_at"]}

    def library(self, owner, before=None, query="", source="all", limit=40):
        """Owner files, received uploads first; old embedded originals remain usable."""
        if (type(query) is not str or len(query) > 512 or type(source) is not str
                or source not in {"all", "user", "assistant"}
                or type(limit) is not int or not 1 <= limit <= 100):
            raise Rejected("library_query_invalid", 422)
        cursor = None
        if before is not None:
            try:
                if type(before) is not str or not 1 <= len(before) <= 256:
                    raise ValueError()
                cursor = json.loads(base64.b64decode(before, altchars=b"-_", validate=True))
                if (type(cursor) is not list or len(cursor) != 3
                        or any(type(value) is not int for value in cursor)
                        or cursor[0] not in (0, 1) or not 1 <= cursor[1] <= 2**63 - 1
                        or not 0 <= cursor[2] <= 2**63 - 1):
                    raise ValueError()
            except (ValueError, TypeError, RecursionError):
                raise Rejected("library_cursor_invalid", 422) from None
        pattern = "%" + query.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        with self.connection() as db:
            db.create_function("casefold", 1, str.casefold, deterministic=True)
            tier, ordering, position = cursor or (0, 0, 0)
            rows = db.execute("""WITH files AS (
                SELECT 0 AS tier,u.rowid AS ordering,0 AS item_position,
                    'file:'||u.file_id AS id,u.file_id,u.name,u.size,u.kind,u.media_type,
                    CASE WHEN s.file_id IS NULL THEN 'user' ELSE 'assistant' END AS source,
                    COALESCE(st.request_id,(SELECT t.request_id FROM attachments a JOIN turns t ON t.seq=a.turn_seq
                        WHERE a.file_id=u.file_id AND t.owner=u.owner ORDER BY t.seq LIMIT 1)) AS request_id,
                    CASE WHEN s.file_id IS NULL THEN (SELECT a.position FROM attachments a JOIN turns t ON t.seq=a.turn_seq
                        WHERE a.file_id=u.file_id AND t.owner=u.owner ORDER BY t.seq,a.position LIMIT 1) END AS position,
                    '/chat/files/'||u.file_id||'/content' AS download_url,
                    COALESCE(st.created_at,(SELECT min(t.created_at) FROM attachments a JOIN turns t ON t.seq=a.turn_seq
                        WHERE a.file_id=u.file_id AND t.owner=u.owner)) AS created_at
                FROM uploads u LEFT JOIN assistant_files s USING(file_id) LEFT JOIN turns st ON st.seq=s.turn_seq
                WHERE u.owner=?
                UNION ALL
                SELECT 1,t.seq,a.position,'legacy:'||t.seq||':'||a.position,NULL,a.name,length(a.data),a.kind,
                    a.media_type,'user',t.request_id,a.position,
                    '/chat/messages/'||t.request_id||'/attachments/'||a.position,t.created_at
                FROM attachments a JOIN turns t ON t.seq=a.turn_seq WHERE t.owner=? AND a.file_id IS NULL
            ) SELECT * FROM files WHERE (?='all' OR source=?) AND casefold(name) LIKE ? ESCAPE '\\'
                AND (? IS NULL OR tier>? OR tier=? AND (ordering<? OR ordering=? AND item_position<?))
                ORDER BY tier,ordering DESC,item_position DESC LIMIT ?""",
                (owner, owner, source, source, pattern,
                 None if cursor is None else tier, tier, tier, ordering, ordering, position, limit + 1)).fetchall()
            page = [dict(row) for row in rows[:limit]]
            next_cursor = None
            if len(rows) > limit:
                last = page[-1]
                next_cursor = base64.urlsafe_b64encode(json.dumps(
                    [last["tier"], last["ordering"], last["item_position"]], separators=(",", ":")).encode()).decode()
            for item in page:
                for key in ("tier", "ordering", "item_position"):
                    item.pop(key)
            return {"files": page, "next_cursor": next_cursor}

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

    def agent_profile(self, owner):
        """Read presentation without creating a conversation or default row."""
        from .agent_profile import DEFAULT_PROFILE
        with self.connection() as db:
            row = db.execute("SELECT revision,profile FROM agent_profiles WHERE owner=?", (owner,)).fetchone()
            return {**json.loads(row["profile"]), "revision": row["revision"]} if row else dict(DEFAULT_PROFILE)

    def save_agent_profile(self, owner, profile):
        """Compare and save one full validated draft under the SQLite lock."""
        with self.connection() as db:
            db.execute(BEGIN_WRITE)
            row = db.execute("SELECT revision FROM agent_profiles WHERE owner=?", (owner,)).fetchone()
            revision = row["revision"] if row else 0
            if profile["revision"] != revision:
                raise Rejected("agent_profile_conflict", 409)
            saved = {key: value for key, value in profile.items() if key != "revision"}
            db.execute("""INSERT INTO agent_profiles(owner,revision,profile) VALUES(?,?,?)
                ON CONFLICT(owner) DO UPDATE SET revision=excluded.revision,profile=excluded.profile""",
                (owner, revision + 1, json.dumps(saved, ensure_ascii=False, separators=(",", ":"))))
            return {**saved, "revision": revision + 1}

    def browser_session(self, owner, *, create=False):
        """A browser can share the durable agent session before the first message."""
        with self.connection() as db:
            if create:
                db.execute(BEGIN_WRITE)
                db.execute("INSERT OR IGNORE INTO conversations VALUES (?,?)", (owner, "chat:" + uuid4().hex))
            row = db.execute("SELECT session_id FROM conversations WHERE owner=?", (owner,)).fetchone()
            return row["session_id"] if row else None

    def freeze_browser_context(self, turn, value):
        """Freeze dispatch identity only. Human input and passwords never enter this table."""
        encoded = json.dumps(value, separators=(",", ":"), sort_keys=True)
        with self.connection() as db:
            db.execute("UPDATE turns SET browser_context=? WHERE seq=? AND browser_context IS NULL "
                "AND input_text IS NULL AND first_dispatch_at IS NULL", (encoded, turn["seq"]))
            saved = dict(db.execute(TURN_BY_SEQUENCE, (turn["seq"],)).fetchone())
            if saved["browser_context"] != encoded:
                raise Rejected("browser_context_changed", 409)
            return saved

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

    def freeze_request_options(self, turn, value):
        """Keep model choices and a scrubbed, explicitly shared excerpt per turn."""
        encoded = json.dumps(value, separators=(",", ":"), sort_keys=True)
        with self.connection() as db:
            db.execute(BEGIN_WRITE)
            db.execute("UPDATE turns SET request_options=? WHERE seq=? AND request_options IS NULL "
                       "AND input_text IS NULL AND first_dispatch_at IS NULL", (encoded, turn["seq"]))
            saved = dict(db.execute(TURN_BY_SEQUENCE, (turn["seq"],)).fetchone())
            # Pre-feature turns with a prepared input preserve their default behaviour.
            stored = json.loads(saved["request_options"]) if saved["request_options"] else {}
            if stored != value:
                raise Rejected("message_options_changed", 409)
            return saved

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
        """The newest saved turn anchors viewing, including a retained terminal run.

        An undispatched latest turn shadows older receipts; observing never
        falls back to an earlier turn or creates a browser session.
        """
        with self.connection() as db:
            row = db.execute("SELECT t.*,c.session_id FROM turns t JOIN conversations c USING(owner) "
                "WHERE owner=? ORDER BY seq DESC LIMIT 1", (owner,)).fetchone()
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
                db.execute("""INSERT OR IGNORE INTO document_grant_files SELECT ?,u.file_id,u.sha256
                    FROM uploads u JOIN assistant_files s USING(file_id) JOIN turns t ON t.seq=s.turn_seq
                    WHERE t.owner=? AND u.owner=? AND t.seq<? AND u.kind='text'""",
                    (token, saved["owner"], saved["owner"], saved["seq"]))
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

    def reject_unadmitted(self, turn, error):
        """Only an explicit gateway proof of no run admission may close an unsent handoff."""
        with self.connection() as db:
            db.execute("UPDATE turns SET status='failed',error=? WHERE seq=? AND run_id IS NULL "
                "AND dispatch_key=? AND status='awaiting_dispatch'", (error, turn["seq"], turn["dispatch_key"]))

    def history(self, owner, before=None, limit=50):
        with self.connection() as db:
            rows = db.execute("SELECT seq,request_id,text,status,output,error,created_at,request_options FROM turns WHERE owner=? AND (? IS NULL OR seq<?) ORDER BY seq DESC LIMIT ?",
                              (owner, before, before, limit + 1)).fetchall()
            more = len(rows) > limit
            page = [dict(row) for row in reversed(rows[:limit])]
            for turn in page:
                options = json.loads(turn.pop("request_options")) if turn["request_options"] else {}
                turn.pop("request_options", None)
                turn["inference"] = options.get("selection")
                turn["terminal_context"] = options.get("terminal_context")
                rows = db.execute("SELECT position,a.name,a.media_type,a.kind,coalesce(u.size,length(a.data)) AS size,CASE WHEN a.kind='audio' THEN reference_text END AS reference_text,reading_state,reading_error FROM attachments a LEFT JOIN uploads u ON u.file_id=a.file_id WHERE turn_seq=? ORDER BY position", (turn["seq"],)).fetchall()
                turn["attachments"] = [{"position":a["position"], "name":a["name"], "media_type":a["media_type"], "kind":a["kind"], "size":a["size"],
                    "transcript":a["reference_text"] if a["kind"] == "audio" else None,
                    "reading_state":a["reading_state"], "reading_error":a["reading_error"]} for a in rows]
                turn["shared_files"] = [self._shared_file(db, row["file_id"]) for row in db.execute(
                    "SELECT file_id FROM assistant_files WHERE turn_seq=? ORDER BY rowid", (turn["seq"],))]
            return {"turns": page, "older_before": page[0]["seq"] if more else None}
