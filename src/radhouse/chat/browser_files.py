"""Library authority and bounded browser transfers; no raw host paths in APIs."""
import base64
import hashlib
import os
import re
from threading import Lock
from uuid import NAMESPACE_URL, uuid4, uuid5

from radhouse.domain.tasks import Rejected
from .attachments import classify, validate_name

CHUNK = 32768


class BrowserFiles:
    def __init__(self, browser):
        self.browser = browser
        self.store = browser.store
        self.owner = browser.owner_id
        self.collect_lock = Lock()
        self.pending_count = 0
        self.unavailable = False

    def human(self, session, tab, binding, value):
        return self.browser._call(session, tab, "files", {**binding, "file": value})

    def chooser(self, session, tab, binding):
        return self.human(session, tab, binding, {"action": "list"})

    def upload(self, session, tab, binding, file_id, chooser, destination, recheck):
        original = self.store.upload(self.owner, file_id)
        identity = uuid4().hex
        recheck()
        self.human(session, tab, binding, {"action": "begin", "id": identity,
            "chooser": chooser, "destination": destination, "name": original.name,
            "size": original.size, "sha256": original.sha256})
        with original.open() as stream:
            offset = 0
            while chunk := stream.read(CHUNK):
                recheck()
                result = self.human(session, tab, binding, {"action": "write", "id": identity,
                    "offset": offset, "data": base64.b64encode(chunk).decode()})
                offset += len(chunk)
                if result.get("offset") != offset:
                    raise Rejected("browser_upload_unconfirmed", 409)
        recheck()
        result = self.human(session, tab, binding, {"action": "commit", "id": identity})
        if result.get("applied") is not True:
            raise Rejected("browser_upload_unconfirmed", 409)
        return {"applied": True, "file_id": file_id}

    def remote(self, session_id, launch_id, value):
        return self.browser.hermes.browser_session(session_id, "files",
            {"collector": self.owner, "launch_id": launch_id, "file": value})

    def collect(self):
        session = self.store.browser_session(self.owner)
        if session is None or not self.collect_lock.acquire(blocking=False):
            return
        try:
            launches = self.remote(session, None, {"action": "list"})
            self.pending_count = 0
            for launch in launches["launches"]:
                identity = launch["launch_id"]
                if type(identity) is not str or not re.fullmatch(r"[a-f0-9]{32}", identity):
                    raise Rejected("browser_download_unconfirmed", 503)
                listing = self.remote(session, identity, {"action": "list"})
                self.pending_count += len(listing["downloads"])
                for download in listing["downloads"]:
                    if download["state"] == "completed":
                        self.receive(session, identity, download)
                        self.pending_count -= 1
            self.unavailable = False
        except Exception:
            self.unavailable = True
            raise
        finally:
            self.collect_lock.release()

    def receive(self, session, launch, download):
        identity = download.get("id")
        size, sha = download.get("size"), download.get("sha256")
        if (type(identity) is not str or not re.fullmatch(r"[a-f0-9]{32}", identity)
                or type(size) is not int or not 0 <= size < 2**53
                or type(sha) is not str or not re.fullmatch(r"[a-f0-9]{64}", sha)
                or type(download.get("private")) not in {int, bool} or download["private"] not in (0, 1)
                or download.get("producer") not in {"user", "assistant"}):
            raise Rejected("browser_download_unconfirmed", 503)
        name = download["name"]
        validate_name(name)
        file_id = str(uuid5(NAMESPACE_URL, "radhouse-browser:" + self.owner + ":" + launch + ":" + identity))
        stream, path = self.store.begin_upload(self.owner, file_id, name)
        try:
            digest, offset, prefix = hashlib.sha256(), 0, bytearray()
            with stream:
                while offset < size:
                    value = self.remote(session, launch, {"action": "read", "id": identity, "offset": offset})
                    encoded = value.get("data")
                    if (value.get("offset") != offset or value.get("size") != size or value.get("sha256") != sha
                            or type(encoded) is not str or len(encoded) > 4 * ((CHUNK + 2) // 3)):
                        raise Rejected("browser_download_unconfirmed", 503)
                    chunk = base64.b64decode(encoded, validate=True)
                    if not 0 < len(chunk) <= min(CHUNK, size - offset):
                        raise Rejected("browser_download_unconfirmed", 503)
                    stream.write(chunk)
                    digest.update(chunk)
                    prefix.extend(chunk[:max(0, 4096 - len(prefix))])
                    offset += len(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if digest.hexdigest() != sha:
                raise Rejected("browser_download_digest_mismatch", 503)
            latest = self.remote(session, launch, {"action": "list"})
            confirmed = next((item for item in latest["downloads"] if item["id"] == identity), None)
            if confirmed is None or any(confirmed.get(key) != download[key] for key in ("sha256", "size", "name")):
                raise Rejected("browser_download_unconfirmed", 503)
            private = bool(download["private"]) or bool(confirmed.get("private", True))
            run_id = download.get("run_id") if download.get("run_id") == confirmed.get("run_id") else None
            media, kind = classify(name, bytes(prefix))
            self.store.commit_upload(self.owner, file_id, name, path, media, kind, sha, size,
                browser={"private": private, "producer": download["producer"], "run_id": run_id,
                    "origin": "browser", "created_at": self.browser.clock()})
            if self.remote(session, launch, {"action": "ack", "id": identity, "sha256": sha}).get("saved") is not True:
                raise Rejected("browser_download_ack_unconfirmed", 503)
        finally:
            path.unlink(missing_ok=True)
