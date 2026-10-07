"""Conversation-scoped selective access to immutable uploaded originals.

The resolver and file allowlist are supplied by the server, never by an agent.
Operation budgets limit parser work and returned context, not upload admission.
"""
from dataclasses import dataclass
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePath
import re
import stat
import subprocess
import sys
from threading import BoundedSemaphore
from typing import Callable

from radhouse.domain.tasks import Rejected
from .attachments import Attachment, FILE_ID

PARSER_VERSION = 1
MAX_RESULT_BYTES = 32 * 1024
_PARSER_SLOT = BoundedSemaphore(1)
_ERRORS = frozenset({"document_unreadable", "document_encrypted", "document_needs_ocr",
                     "document_operation_exhausted", "document_locator_not_found", "document_source_changed"})
_COVERAGE = {".pdf": "PDF text layer; images and scanned text require OCR",
             ".docx": "Current main-body paragraphs and tables; excludes headers, footers, notes and images",
             ".xlsx": "Stored worksheet cells and cached formula values; no formula execution or formatting inference",
             ".pptx": "Slide text in presentation order; excludes speaker notes and images"}


@dataclass(frozen=True)
class Passage:
    locator: str
    label: str
    text: str


@dataclass(frozen=True)
class DocumentResult:
    file_id: str
    sha256: str
    passages: tuple[Passage, ...] = ()
    next_cursor: str | None = None
    complete: bool = False
    error: str | None = None


class DocumentAccess:
    def __init__(self, resolve: Callable[[str, str], Attachment], *, owner: str,
                 file_ids: frozenset[str], cursor_key: bytes):
        if type(owner) is not str or not owner or len(owner) > 200 or type(file_ids) is not frozenset or any(
                type(value) is not str or not FILE_ID.fullmatch(value) for value in file_ids) or (
                type(cursor_key) is not bytes or len(cursor_key) < 32):
            raise ValueError("invalid_document_scope")
        self._resolve, self._owner, self._file_ids = resolve, owner, file_ids
        self._cursor_key = cursor_key

    def _signature(self, body):
        encoded = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        return hmac.new(self._cursor_key, encoded, hashlib.sha256).hexdigest()

    def _source(self, file_id):
        if type(file_id) is not str or file_id not in self._file_ids:
            raise Rejected("attachment_not_found", 404)
        attachment = self._resolve(self._owner, file_id)
        if (attachment.file_id != file_id or attachment.kind not in {"text", "document"}
                or not isinstance(attachment.stored_sha256, str)
                or re.fullmatch(r"[a-f0-9]{64}", attachment.stored_sha256) is None):
            raise Rejected("document_reader_unavailable", 422)
        return attachment

    def catalog(self):
        """Upload receipts in the saved scope; no file reads or current-byte assertion."""
        result = []
        for file_id in sorted(self._file_ids):
            attachment = self._resolve(self._owner, file_id)
            if attachment.file_id != file_id:
                raise Rejected("attachment_not_found", 404)
            extension = PurePath(attachment.name).suffix.lower()
            result.append({"file_id": file_id, "name": attachment.name,
                           "media_type": attachment.media_type, "sha256": attachment.sha256,
                           "sha256_basis": "upload_receipt",
                           "size": attachment.size,
                           "reader_scope": _COVERAGE.get(extension, "UTF-8 text" if attachment.kind == "text" else None),
                           "locator_kind": {".pdf": "page", ".docx": "paragraph",
                                            ".xlsx": "sheet/cell", ".pptx": "slide"}.get(
                                                extension, "line" if attachment.kind == "text" else None)})
        return tuple(result)

    def search(self, file_id: str, query: str, cursor: str | None = None) -> DocumentResult:
        if type(query) is not str or not query.strip() or len(query) > 512 or "\x00" in query:
            raise Rejected("document_query_invalid", 422)
        return self._operate(file_id, "search", query=query, cursor=cursor)

    def read(self, file_id: str, locator: str | None = None,
             cursor: str | None = None) -> DocumentResult:
        if locator is not None and (type(locator) is not str or len(locator) > 1024):
            raise Rejected("document_locator_invalid", 422)
        return self._operate(file_id, "read", locator=locator, cursor=cursor)

    def _operate(self, file_id, operation, *, query=None, locator=None, cursor=None):
        attachment = self._source(file_id)
        binding = {"v": PARSER_VERSION, "file_id": file_id, "sha256": attachment.sha256,
                   "operation": operation, "query": hashlib.sha256(query.encode()).hexdigest() if query else None,
                   "locator": locator}
        position, resume = 0, None
        if cursor is not None:
            try:
                if type(cursor) is not str or len(cursor) > 4096:
                    raise ValueError()
                signed = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
                if (type(signed) is not dict or set(signed) != {"body", "signature"}
                        or type(signed["body"]) is not dict or type(signed["signature"]) is not str
                        or re.fullmatch(r"[a-f0-9]{64}", signed["signature"]) is None
                        or not hmac.compare_digest(signed["signature"], self._signature(signed["body"]))):
                    raise ValueError()
                decoded = signed["body"]
                if type(decoded) is not dict or set(decoded) != {"binding", "position", "resume"} or decoded["binding"] != binding:
                    raise ValueError()
                position = decoded["position"]
                if type(position) is not int or not 0 <= position <= 2**63 - 1:
                    raise ValueError()
                resume = decoded["resume"]
                if resume is not None:
                    if (attachment.kind != "text" or type(resume) is not dict
                            or set(resume) != {"cookie", "line", "offset", "index", "has_text"}
                            or any(type(resume[key]) is not int or resume[key] < 0
                                   for key in ("cookie", "line", "offset", "index"))
                            or resume["line"] < 1 or resume["cookie"].bit_length() > 512
                            or type(resume["has_text"]) is not bool
                            or not 0 <= position - resume["index"] <= 1):
                        raise ValueError()
            except (ValueError, TypeError, UnicodeDecodeError, RecursionError):
                raise Rejected("document_cursor_invalid", 422) from None
        request = {"operation": operation, "query": query, "locator": locator, "position": position, "resume": resume,
                   "sha256": attachment.sha256,
                   "extension": ".txt" if attachment.kind == "text" else PurePath(attachment.name).suffix.lower()}
        if not _PARSER_SLOT.acquire(blocking=False):
            return DocumentResult(file_id, attachment.sha256, error="document_reader_busy")
        source_fd = None
        try:
            try:
                if isinstance(attachment.data, Path):
                    # A replaced FIFO must not block before the child's deadline. Hold
                    # one regular inode through verification and parsing, never reopen
                    # the retained pathname after checking its content.
                    source_fd = os.open(attachment.data, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    if not stat.S_ISREG(os.fstat(source_fd).st_mode):
                        raise Rejected("document_source_changed", 409)
                    request["source_fd"] = source_fd
                else:
                    request["data"] = base64.b64encode(attachment.data).decode()
                result = subprocess.run([sys.executable, "-m", "radhouse.chat.document_parser"],
                    input=json.dumps(request), text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    timeout=15, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    pass_fds=(source_fd,) if source_fd is not None else ())
                if result.returncode or len(result.stdout.encode()) > MAX_RESULT_BYTES:
                    return DocumentResult(file_id, attachment.sha256, error="document_operation_exhausted")
                value = json.loads(result.stdout)
                if "error" in value:
                    code = value["error"] if value["error"] in _ERRORS else "document_unreadable"
                    if code == "document_source_changed":
                        raise Rejected(code, 409)
                    return DocumentResult(file_id, attachment.sha256, error=code)
                passages = tuple(Passage(**entry) for entry in value["passages"])
                if (type(value["complete"]) is not bool or len(passages) > 8
                        or any(type(field) is not str for entry in passages for field in (entry.locator, entry.label, entry.text))):
                    raise ValueError()
                next_position = value["next_position"]
                continuation = None
                if next_position is not None:
                    if type(next_position) is not int or next_position <= position or value["complete"]:
                        raise ValueError()
                    body = {"binding": binding, "position": next_position, "resume": value.get("next_resume")}
                    continuation = base64.urlsafe_b64encode(json.dumps(
                        {"body": body, "signature": self._signature(body)}, ensure_ascii=False,
                        separators=(",", ":")).encode()).decode()
                elif not value["complete"]:
                    raise ValueError()
                return DocumentResult(file_id, attachment.sha256, passages, continuation, value["complete"])
            except subprocess.TimeoutExpired:
                return DocumentResult(file_id, attachment.sha256, error="document_operation_exhausted")
            except (OSError, ValueError, KeyError, TypeError):
                return DocumentResult(file_id, attachment.sha256, error="document_unreadable")
        finally:
            if source_fd is not None:
                os.close(source_fd)
            _PARSER_SLOT.release()
