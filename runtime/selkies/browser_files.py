"""Fixed browser file operations. No caller-selected paths or general CDP API."""
import asyncio
import base64
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import time
from uuid import uuid4

CHUNK = 32 * 1024
ID = re.compile(r"[a-f0-9]{32}")
GUID = re.compile(r"[a-f0-9-]{36}")


def identifier(value):
    if type(value) is not str or ID.fullmatch(value) is None:
        raise ValueError("invalid_file_identity")
    return value


def filename(value):
    if (type(value) is not str or not 1 <= len(value) <= 200
            or value in {".", ".."} or re.search(r'[/\\\x00-\x1f\x7f]', value)):
        raise ValueError("invalid_filename")
    return value


def validate(value):
    fields = {
        "list": set(), "read": {"id", "offset"}, "ack": {"id", "sha256"},
        "begin": {"id", "chooser", "destination", "name", "size", "sha256"},
        "write": {"id", "offset", "data"}, "commit": {"id"}, "cancel": {"chooser"},
    }
    if type(value) is not dict or value.get("action") not in fields or set(value) != fields[value["action"]] | {"action"}:
        raise ValueError("invalid_file_request")
    for key in {"id", "chooser"} & value.keys():
        identifier(value[key])
    for key in {"offset", "size"} & value.keys():
        if type(value[key]) is not int or not 0 <= value[key] < 2**53:
            raise ValueError("invalid_file_offset")
    if "sha256" in value and (type(value["sha256"]) is not str or re.fullmatch(r"[a-f0-9]{64}", value["sha256"]) is None):
        raise ValueError("invalid_file_digest")
    if "name" in value:
        filename(value["name"])
    if "destination" in value and (type(value["destination"]) is not str or not 1 <= len(value["destination"]) <= 4096):
        raise ValueError("invalid_file_destination")
    if "data" in value:
        if type(value["data"]) is not str or len(value["data"]) > 4 * ((CHUNK + 2) // 3):
            raise ValueError("invalid_file_chunk")
        if not 0 < len(base64.b64decode(value["data"], validate=True)) <= CHUNK:
            raise ValueError("invalid_file_chunk")
    return value


def regular(path, mode=os.O_RDONLY):
    descriptor = os.open(path, mode | os.O_NOFOLLOW, 0o600)
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        os.close(descriptor)
        raise ValueError("invalid_file_storage")
    return descriptor


class Files:
    """A launch-local CDP observer and durable, acknowledgement-driven outbox."""
    def __init__(self, root, launch_id):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("private_file_storage_required")
        self.launch_id = identifier(launch_id)
        self.downloads = self.root / "downloads"
        self.uploads = self.root / "uploads"
        for path in (self.downloads, self.uploads):
            path.mkdir(mode=0o700, exist_ok=True)
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("private_file_storage_required")
        database = self.root / "files.sqlite3"
        descriptor = regular(database, os.O_RDWR | os.O_CREAT)
        try:
            if os.fstat(descriptor).st_mode & 0o077:
                raise ValueError("private_file_storage_required")
        finally:
            os.close(descriptor)
        self.db = sqlite3.connect(database)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS downloads (
            id TEXT PRIMARY KEY, guid TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            private INTEGER NOT NULL, producer TEXT NOT NULL, state TEXT NOT NULL,
            size INTEGER, sha256 TEXT, created_at REAL NOT NULL)""")
        self.db.commit()
        self.private = True
        self.producer = "user"
        self.chooser = None
        self.staged = {}
        self.sessions = {}
        self.pending = {}
        self.sequence = 0
        self.tasks = set()
        self.socket = self.http = self.listener = None
        self.faulted = False
        self.operation_lock = asyncio.Lock()

    async def start(self, endpoint):
        from aiohttp import ClientSession
        self.http = ClientSession(trust_env=False)
        self.socket = await self.http.ws_connect(endpoint, max_msg_size=1024 * 1024)
        self.listener = asyncio.create_task(self.listen())
        await self.call("Browser.setDownloadBehavior", {"behavior": "allowAndName", "downloadPath": str(self.downloads), "eventsEnabled": True})
        await self.call("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True})
        await asyncio.gather(*list(self.tasks))
        if self.faulted:
            raise ValueError("browser_file_observer_unavailable")

    async def call(self, method, params=None, session=None):
        self.sequence += 1
        identity = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[identity] = future
        body = {"id": identity, "method": method, "params": params or {}}
        if session:
            body["sessionId"] = session
        try:
            await self.socket.send_json(body)
            return await asyncio.wait_for(future, 10)
        finally:
            self.pending.pop(identity, None)

    async def attach(self, session, target):
        try:
            if target.get("type") in {"page", "iframe"}:
                self.sessions[session] = target.get("targetId")
                await self.call("Page.enable", session=session)
                await self.call("Page.setInterceptFileChooserDialog", {"enabled": True}, session)
                await self.call("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True}, session)
            await self.call("Runtime.runIfWaitingForDebugger", session=session)
        except Exception as error:
            logging.getLogger(__name__).warning("Browser file observer failed: phase=attach kind=%s", type(error).__name__)
            self.faulted = True

    async def listen(self):
        try:
            async for message in self.socket:
                if message.type.name != "TEXT":
                    break
                value = json.loads(message.data)
                future = self.pending.get(value.get("id"))
                if future is not None and not future.done():
                    if "error" in value:
                        future.set_exception(ValueError("browser_file_command_failed"))
                    else:
                        future.set_result(value.get("result", {}))
                elif "id" not in value:
                    await self.event(value)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logging.getLogger(__name__).warning("Browser file observer failed: phase=listen kind=%s", type(error).__name__)
            self.faulted = True
        finally:
            self.faulted = True
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ValueError("browser_file_connection_closed"))

    async def event(self, value):
        method, data, session = value.get("method"), value.get("params", {}), value.get("sessionId")
        if method == "Target.attachedToTarget":
            task = asyncio.create_task(self.attach(data["sessionId"], data["targetInfo"]))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        elif method == "Target.detachedFromTarget":
            self.sessions.pop(data.get("sessionId"), None)
            if self.chooser and self.chooser["session"] == data.get("sessionId"):
                self.chooser = None
        elif method in {"Page.frameNavigated", "Page.navigatedWithinDocument", "Page.frameDetached"}:
            if self.chooser and self.chooser["session"] == session:
                self.chooser = None
        elif method == "Page.fileChooserOpened":
            self.chooser = {"id": uuid4().hex, "session": session, "frame": data["frameId"],
                            "node": data["backendNodeId"], "multiple": data.get("mode") == "selectMultiple"}
        elif method == "Browser.downloadWillBegin":
            guid = data.get("guid", "")
            if not GUID.fullmatch(guid):
                raise ValueError("invalid_download_identity")
            try:
                name = filename(data.get("suggestedFilename"))
            except ValueError:
                name = "download.bin"
            with self.db:
                self.db.execute("INSERT OR IGNORE INTO downloads VALUES (?,?,?,?,?,'pending',NULL,NULL,?)",
                    (guid.replace("-", ""), guid, name, int(self.private), self.producer, time.time()))
        elif method == "Browser.downloadProgress":
            guid = data.get("guid")
            if data.get("state") == "completed":
                await self.complete(guid)
            elif data.get("state") == "canceled":
                with self.db:
                    self.db.execute("UPDATE downloads SET state='cancelled' WHERE guid=? AND state='pending'", (guid,))

    async def complete(self, guid):
        row = self.db.execute("SELECT * FROM downloads WHERE guid=? AND state='pending'", (guid,)).fetchone()
        if row is None:
            return
        def digest():
            with os.fdopen(regular(self.downloads / row["guid"]), "rb") as stream:
                size = os.fstat(stream.fileno()).st_size
                value = hashlib.file_digest(stream, "sha256").hexdigest()
                os.fsync(stream.fileno())
            return size, value
        size, sha = await asyncio.to_thread(digest)
        directory = os.open(self.downloads, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        with self.db:
            self.db.execute("UPDATE downloads SET state='completed',size=?,sha256=? WHERE guid=?", (size, sha, guid))

    def visibility(self, private, producer):
        if type(private) is not bool or producer not in {"user", "assistant"}:
            raise ValueError("invalid_file_visibility")
        self.private, self.producer = private, producer
        if private:
            with self.db:
                self.db.execute("UPDATE downloads SET private=1 WHERE state='pending'")

    async def chooser_state(self):
        chooser = self.chooser
        if chooser is None or self.socket is None:
            return None
        tree = await self.call("Page.getFrameTree", session=chooser["session"])
        frames = [tree["frameTree"]]
        while frames:
            entry = frames.pop()
            frame = entry["frame"]
            if frame["id"] == chooser["frame"] and self.chooser is chooser:
                if not frame.get("url", "").startswith(("https://", "http://")):
                    raise ValueError("invalid_upload_destination")
                return {"id": chooser["id"], "destination": frame["url"], "multiple": chooser["multiple"]}
            frames.extend(entry.get("childFrames", []))
        raise ValueError("file_chooser_changed")

    async def execute(self, value):
        async with self.operation_lock:
            return await self._execute(value)

    async def _execute(self, value):
        value = validate(value)
        action = value["action"]
        if action == "list":
            rows = self.db.execute("SELECT id,name,private,producer,state,size,sha256,created_at FROM downloads WHERE state IN ('completed','pending') ORDER BY state,created_at LIMIT 16").fetchall()
            return {"chooser": await self.chooser_state(), "downloads": [dict(row) for row in rows], "faulted": self.faulted}
        if action in {"read", "ack"}:
            return self.download(value)
        if action == "cancel":
            if self.chooser and self.chooser["id"] == value["chooser"]:
                self.chooser = None
            return {"cancelled": True}
        if action == "begin":
            chooser = await self.chooser_state()
            if chooser is None or chooser["id"] != value["chooser"] or chooser["destination"] != value["destination"]:
                raise ValueError("file_chooser_changed")
            if value["id"] in self.staged:
                if self.staged[value["id"]] != value:
                    raise ValueError("upload_conflict")
            else:
                directory = self.uploads / value["id"]
                directory.mkdir(mode=0o700)
                descriptor = regular(directory / value["name"], os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(descriptor)
                self.staged[value["id"]] = value
            return {"accepted": True}
        staged = self.staged.get(value["id"])
        if staged is None:
            raise ValueError("upload_not_found")
        path = self.uploads / value["id"] / staged["name"]
        if action == "write":
            return await asyncio.to_thread(self.write, path, staged, value)
        chooser = await self.chooser_state()
        if chooser is None or chooser["id"] != staged["chooser"] or chooser["destination"] != staged["destination"]:
            raise ValueError("file_chooser_changed")
        def verify():
            with os.fdopen(regular(path), "rb") as stream:
                if os.fstat(stream.fileno()).st_size != staged["size"] or hashlib.file_digest(stream, "sha256").hexdigest() != staged["sha256"]:
                    raise ValueError("upload_incomplete")
        await asyncio.to_thread(verify)
        current = self.chooser
        if current is None or current["id"] != staged["chooser"]:
            raise ValueError("file_chooser_changed")
        # Consume before effect. An uncertain response never authorizes replay.
        self.chooser = None
        await self.call("DOM.setFileInputFiles", {"files": [str(path)], "backendNodeId": current["node"]}, current["session"])
        return {"applied": True}

    @staticmethod
    def write(path, staged, value):
        data = base64.b64decode(value["data"], validate=True)
        with os.fdopen(regular(path, os.O_RDWR), "r+b") as stream:
            size = os.fstat(stream.fileno()).st_size
            offset = value["offset"]
            if offset + len(data) > staged["size"] or offset > size:
                raise ValueError("invalid_file_offset")
            stream.seek(offset)
            if offset < size:
                if stream.read(len(data)) != data:
                    raise ValueError("upload_conflict")
            else:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        return {"offset": offset + len(data)}

    def download(self, value):
        row = self.db.execute("SELECT * FROM downloads WHERE id=?", (value["id"],)).fetchone()
        if row is None or row["state"] not in {"completed", "saved"}:
            raise ValueError("download_incomplete")
        path = self.downloads / row["guid"]
        if value["action"] == "ack":
            if value["sha256"] != row["sha256"]:
                raise ValueError("download_digest_mismatch")
            with self.db:
                self.db.execute("UPDATE downloads SET state='saved' WHERE id=?", (value["id"],))
            path.unlink(missing_ok=True)
            return {"saved": True}
        if row["state"] != "completed" or value["offset"] > row["size"]:
            raise ValueError("invalid_file_offset")
        with os.fdopen(regular(path), "rb") as stream:
            if os.fstat(stream.fileno()).st_size != row["size"]:
                raise ValueError("download_changed")
            stream.seek(value["offset"])
            data = stream.read(CHUNK)
        return {"data": base64.b64encode(data).decode(), "offset": value["offset"], "size": row["size"], "sha256": row["sha256"]}

    async def close(self):
        if self.socket is not None:
            await self.socket.close()
        if self.listener is not None:
            self.listener.cancel()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*(list(self.tasks) + ([self.listener] if self.listener else [])), return_exceptions=True)
        if self.http is not None:
            await self.http.close()
        self.db.close()

    async def recover_downloads(self):
        """Only after the launch is gone: Chrome's final rename is durable evidence.

        Incomplete .crdownload files are never promoted to originals. They remain
        failed transfers and can be removed with retired staging.
        """
        rows = self.db.execute("SELECT guid FROM downloads WHERE state='pending'").fetchall()
        for row in rows:
            try:
                await self.complete(row["guid"])
            except (OSError, ValueError):
                with self.db:
                    self.db.execute("UPDATE downloads SET state='cancelled' WHERE guid=?", (row["guid"],))
        for row in self.db.execute("SELECT guid FROM downloads WHERE state IN ('saved','cancelled')"):
            if GUID.fullmatch(row["guid"]) is None:
                raise ValueError("invalid_download_identity")
            (self.downloads / row["guid"]).unlink(missing_ok=True)
            (self.downloads / (row["guid"] + ".crdownload")).unlink(missing_ok=True)
        # Chrome is gone; uploaded originals need no second retained copy here.
        if self.uploads.exists():
            shutil.rmtree(self.uploads)
            self.uploads.mkdir(mode=0o700)
