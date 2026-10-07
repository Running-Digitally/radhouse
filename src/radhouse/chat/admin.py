"""Small read-only management views using the existing authenticated owner."""
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
import os
import platform
import re
import sqlite3
import stat
from typing import Callable
from radhouse.integrations.hermes import browser_network_policy

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse


STATIC = Path(__file__).with_name("static")


@dataclass(frozen=True)
class EffectiveSettings:
    """Explicit public values, rather than a filtered copy of private config."""
    idle_timeout_seconds: int
    maximum_session_seconds: int
    remembered_session_seconds: int
    transcription_enabled: bool = False
    document_access_enabled: bool = False
    browser_enabled: bool = False
    message_character_limit: int = 16000
    upload_size_limit_bytes: int | None = None
    upload_count_limit: int | None = None


@dataclass(frozen=True)
class AssistantSignal:
    ready: bool
    version: str | None = None


@dataclass(frozen=True)
class DocumentSignal:
    available: bool
    connected: bool
    version: str | None = None


def utc_now():
    return datetime.now(timezone.utc)


def _version(value):
    # Probe/version values can originate upstream; don't return vendor bodies.
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._+-]{1,80}", value) else None


def _package_version():
    try:
        return _version(metadata.version("radhouse"))
    except metadata.PackageNotFoundError:
        return None


class AdminService:
    def __init__(self, store, *, settings: EffectiveSettings,
                 assistant_probe: Callable[[], AssistantSignal] | None = None,
                 document_probe: Callable[[], DocumentSignal] | None = None,
                 network_policy_probe: Callable[[], dict | None] | None = None,
                 release_commit: str | None = None,
                 clock: Callable[[], datetime] = utc_now):
        self.store = store
        self.effective = settings
        self.assistant_probe = assistant_probe
        self.document_probe = document_probe
        self.network_policy_probe = network_policy_probe
        self.release_commit = release_commit if isinstance(release_commit, str) and re.fullmatch(r"[a-f0-9]{40}", release_commit) else None
        self.clock = clock

    def _checked_at(self):
        return self.clock().astimezone(timezone.utc).isoformat()

    def settings(self):
        values = self.effective
        return {
            "checked_at": self._checked_at(),
            "permissions": {"read": True, "write": False},
            "authentication": {"methods": ["password", "totp"],
                "idle_timeout_seconds": values.idle_timeout_seconds,
                "maximum_session_seconds": values.maximum_session_seconds,
                "remembered_session_seconds": values.remembered_session_seconds},
            "messages": {"character_limit": values.message_character_limit},
            "files": {"upload_size_limit_bytes": values.upload_size_limit_bytes,
                "upload_count_limit": values.upload_count_limit,
                "document_formats": ["text", "pdf", "docx", "xlsx", "pptx"],
                "audio_transcription_enabled": values.transcription_enabled},
            "documents": {"selective_access_enabled": values.document_access_enabled},
            "browser": {"enabled": values.browser_enabled, "mode": "view_only"},
        }

    def _network_policy(self):
        try:
            policy = browser_network_policy(self.network_policy_probe()) if self.network_policy_probe else None
        except Exception:
            policy = None
        return policy or {"schema": "radhouse.browser-network-policy.v1", "verified": False,
            "source": None, "verified_at": None, "enforcement": "vm_firewall", "allowed": [], "denied": []}

    def _assistant(self):
        if self.assistant_probe is None:
            return {"id": "assistant", "state": "unverified", "detail": "No connection check is configured.", "version": None}
        try:
            signal = self.assistant_probe()
            if not isinstance(signal, AssistantSignal) or type(signal.ready) is not bool:
                raise ValueError("invalid_signal")
            return {"id": "assistant", "state": "healthy" if signal.ready else "unavailable",
                "detail": "Connection and required capabilities verified. This check does not send a message." if signal.ready else "The assistant is not ready to receive messages.",
                "version": _version(signal.version)}
        except Exception:
            return {"id": "assistant", "state": "unavailable", "detail": "The assistant connection could not be checked.", "version": None}

    def _documents(self):
        if self.document_probe is None:
            return {"id": "documents", "state": "unverified", "detail": "Full-document access has not been verified.", "version": None}
        try:
            signal = self.document_probe()
            if not isinstance(signal, DocumentSignal) or type(signal.available) is not bool or type(signal.connected) is not bool:
                raise ValueError("invalid_signal")
            state = "unavailable" if not signal.available else "healthy" if signal.connected else "unverified"
            detail = ("Document reader is available and selective reads are connected." if state == "healthy"
                else "Document reader is available; full-document access is not connected." if state == "unverified"
                else "The document reader is unavailable.")
            return {"id": "documents", "state": state, "detail": detail, "version": _version(signal.version)}
        except Exception:
            return {"id": "documents", "state": "unavailable", "detail": "The document reader could not be checked.", "version": None}

    def _storage(self):
        try:
            path, directory = self.store.path, self.store.files_path
            parent = path.parent
            file_info, directory_info, parent_info = path.lstat(), directory.lstat(), parent.lstat()
            if (not stat.S_ISREG(file_info.st_mode) or not stat.S_ISDIR(directory_info.st_mode)
                    or not stat.S_ISDIR(parent_info.st_mode)
                    or any(info.st_uid != os.getuid() or info.st_mode & 0o077
                           for info in (file_info, directory_info, parent_info))):
                raise ValueError("private_storage_required")
            # An observer must never create a replacement DB if the file vanished.
            with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1) as db:
                db.execute("PRAGMA query_only=ON")
                schema = db.execute("PRAGMA user_version").fetchone()[0]
                if schema != 3:
                    raise ValueError("chat_schema_mismatch")
                db.execute("SELECT seq FROM turns LIMIT 1").fetchone()
            # SQLite journals/sidecars need the DB parent, independently of the
            # original-files directory. Observe permissions and both filesystems.
            spaces = (os.statvfs(parent), os.statvfs(directory))
            free_bytes = min(space.f_bavail * space.f_frsize for space in spaces)
            directory_access = stat.S_IWUSR | stat.S_IXUSR
            writable = bool(file_info.st_mode & stat.S_IWUSR) and all(
                info.st_mode & directory_access == directory_access for info in (parent_info, directory_info))
            writable = writable and all(not space.f_flag & os.ST_RDONLY for space in spaces)
            state = "healthy" if writable and free_bytes > 0 else "unavailable"
            detail = ("Conversation storage and originals directory are readable." if state == "healthy"
                else "Application storage is read only." if not writable else "Application storage has no free space.")
            return {"id": "storage", "state": state, "detail": detail,
                "schema_version": schema, "database_bytes": file_info.st_size,
                "free_bytes": free_bytes}
        except (OSError, sqlite3.Error, ValueError):
            return {"id": "storage", "state": "unavailable", "detail": "Application storage could not be checked.",
                "schema_version": None, "database_bytes": None, "free_bytes": None}

    def infrastructure(self):
        return {"checked_at": self._checked_at(), "versions": {
                "release_commit": self.release_commit, "package": _package_version(), "python": platform.python_version()},
            "browser_network_policy": self._network_policy(),
            "components": [
                {"id": "web", "state": "healthy", "detail": "This request reached the web app and verified your management access."},
                self._assistant(), self._documents(), self._storage()],
        }


def create_admin_router(admin: AdminService, authorize: Callable[[Request], object]) -> APIRouter:
    """The app supplies its owner and freshly looked-up management role check."""
    router = APIRouter()

    @router.get("/admin/settings")
    def settings(request: Request):
        authorize(request)
        return admin.settings()

    @router.get("/admin/infrastructure")
    def infrastructure(request: Request):
        authorize(request)
        return admin.infrastructure()

    @router.get("/settings")
    @router.get("/infrastructure")
    def page(request: Request):
        authorize(request)
        return FileResponse(STATIC / "admin.html")

    @router.get("/admin.js")
    def script():
        return FileResponse(STATIC / "admin.js", media_type="text/javascript")

    @router.get("/admin.css")
    def stylesheet():
        return FileResponse(STATIC / "admin.css", media_type="text/css")

    return router
