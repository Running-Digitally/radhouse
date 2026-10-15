"""Read the owner's two built-in saved-note files without initializing memory."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat

SCHEMA = "radhouse.saved-memory.v1"
MAX_RESPONSE_BYTES = 1_048_576  # The existing Hermes HTTP response boundary.
SOURCES = (("user", "USER.md"), ("memory", "MEMORY.md"))


def _empty_source(target, filename, state, *, modified=None):
    complete = state in {"missing", "empty"}
    return {"target": target, "source_filename": filename, "state": state,
        "entries": [] if complete else None, "file_modified_at": modified,
        "complete": complete}


def _parse_entries(raw):
    from tools.memory_tool_store import MemoryStore
    return MemoryStore._parse_entries(raw)


def _scrub(text):
    from agent.redact import REDACTION_UNAVAILABLE, redact_for_egress
    from radhouse_hermes_bridge import _redacted
    value = redact_for_egress(_redacted(text))
    if value == REDACTION_UNAVAILABLE:
        raise ValueError("memory_redaction_unavailable")
    return value


def _read_source(directory, target, filename, scrub):
    modified = None
    try:
        fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                return _empty_source(target, filename, "unreadable")
            modified = datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat()
            raw = stream.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            return _empty_source(target, filename, "too_large", modified=modified)
        entries = _parse_entries(raw.decode("utf-8-sig"))
        if not entries:
            return _empty_source(target, filename, "empty", modified=modified)
        # Scrub complete parsed entries before any content leaves the VM.
        return {"target": target, "source_filename": filename, "state": "available",
            "entries": [scrub(entry) for entry in entries],
            "file_modified_at": modified, "complete": True}
    except FileNotFoundError:
        return _empty_source(target, filename, "missing")
    except (OSError, UnicodeDecodeError):
        return _empty_source(target, filename, "unreadable", modified=modified)


def read_saved_memory(profile_home: Path, *, scrub=None, now=None):
    """One coherent read per fixed source; never create a home, file, lock or store."""
    scrub = scrub or _scrub
    checked = (now or datetime.now(timezone.utc)).isoformat()
    sources = None
    try:
        home_fd = os.open(profile_home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            if os.fstat(home_fd).st_uid != os.getuid():
                raise OSError("profile_owner_mismatch")
            directory = os.open("memories", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=home_fd)
            try:
                if os.fstat(directory).st_uid != os.getuid():
                    raise OSError("memory_owner_mismatch")
                sources = [_read_source(directory, target, name, scrub) for target, name in SOURCES]
            finally:
                os.close(directory)
        finally:
            os.close(home_fd)
    except FileNotFoundError:
        sources = [_empty_source(target, name, "missing") for target, name in SOURCES]
    except OSError:
        sources = [_empty_source(target, name, "unreadable") for target, name in SOURCES]
    result = {"schema": SCHEMA, "checked_at": checked, "sources": sources}
    # Oversized manually edited stores stay intact; never silently truncate notes.
    while len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_RESPONSE_BYTES:
        candidates = [source for source in sources if source["state"] == "available"]
        if not candidates:
            raise ValueError("memory_response_unavailable")
        source = max(candidates, key=lambda item: len(json.dumps(item["entries"], ensure_ascii=False)))
        source.update(state="too_large", entries=None, complete=False)
    return result


async def handle_about_you(adapter, request):
    """Private bearer-authenticated read under the current native profile scope."""
    from aiohttp import web
    error = adapter._check_auth(request)
    if error is not None:
        return error
    if request.query:
        return web.json_response({"error": "memory_invalid_request"}, status=400)
    try:
        from hermes_constants import get_hermes_home
        value = await asyncio.to_thread(read_saved_memory, get_hermes_home())
    except Exception:
        # Native exceptions can contain profile paths or source text.
        return web.json_response({"error": "memory_unavailable"}, status=503,
            headers={"Cache-Control": "no-store"})
    return web.json_response(value, dumps=lambda item: json.dumps(item, ensure_ascii=False),
        headers={"Cache-Control": "no-store"})
