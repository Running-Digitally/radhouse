"""Bounded original attachments and preparation for the Hermes input contract."""
from dataclasses import dataclass
import base64
import binascii
import hashlib
from pathlib import PurePath
import re

from radhouse.domain.tasks import InputFile, Rejected

MAX_FILES = 4
MAX_FILE = 20 * 1024 * 1024
MAX_TOTAL = 24 * 1024 * 1024
MAX_IMAGE = 4 * 1024 * 1024
MAX_IMAGES = 8 * 1024 * 1024
MAX_TEXT = 128 * 1024
MAX_REQUEST = 34 * 1024 * 1024
OFFICE = {".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
AUDIO = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".ogg": "audio/ogg",
         ".flac": "audio/flac", ".webm": "audio/webm"}


@dataclass(frozen=True)
class Attachment:
    name: str
    media_type: str
    kind: str
    data: bytes
    reference_text: str | None = None

    @property
    def sha256(self):
        return hashlib.sha256(self.data).hexdigest()

    def identity(self):
        return (self.name, self.media_type, self.sha256)

    def image(self):
        return InputFile(self.name, base64.b64encode(self.data).decode(), self.media_type, "base64", self.sha256)


def decode_uploads(values):
    if len(values) > MAX_FILES:
        raise Rejected("attachments_too_many", 422)
    result = []
    for value in values:
        name = value["name"]
        if not name or len(name) > 200 or re.search(r'[/\\\x00-\x1f\x7f]', name):
            raise Rejected("attachment_invalid", 422)
        try:
            data = base64.b64decode(value["content"], validate=True)
        except (binascii.Error, ValueError):
            raise Rejected("attachment_invalid", 422) from None
        if not data or len(data) > MAX_FILE:
            raise Rejected("attachment_too_large" if data else "attachment_empty", 422)
        extension = PurePath(name).suffix.lower()
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            media, kind, text = "image/png", "image", None
        elif data.startswith(b"\xff\xd8\xff"):
            media, kind, text = "image/jpeg", "image", None
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            media, kind, text = "image/webp", "image", None
        elif extension == ".pdf" and data.startswith(b"%PDF-"):
            media, kind, text = "application/pdf", "document", None
        elif extension in OFFICE and data.startswith(b"PK\x03\x04"):
            media, kind, text = OFFICE[extension], "document", None
        elif extension in AUDIO:
            valid = ((extension == ".wav" and data[:4] == b"RIFF" and data[8:12] == b"WAVE")
                or (extension == ".mp3" and (data.startswith(b"ID3") or len(data) >= 2 and data[0] == 255 and data[1] & 224 == 224))
                or (extension == ".m4a" and data[4:8] == b"ftyp")
                or (extension == ".ogg" and data.startswith(b"OggS"))
                or (extension == ".flac" and data.startswith(b"fLaC"))
                or (extension == ".webm" and data.startswith(b"\x1aE\xdf\xa3")))
            if not valid:
                raise Rejected("attachment_invalid", 422)
            media, kind, text = AUDIO[extension], "audio", None
        elif extension in (*OFFICE, ".pdf", ".doc", ".xls", ".ppt", ".docm", ".xlsm", ".pptm", ".svg", ".gif", ".heic"):
            raise Rejected("attachment_unsupported", 422)
        else:
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise Rejected("attachment_unsupported", 422) from None
            if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
                raise Rejected("attachment_unsupported", 422)
            media, kind = "text/plain", "text"
            if len(data) > MAX_TEXT:
                raise Rejected("attachment_text_too_large", 422)
        if kind == "image" and len(data) > MAX_IMAGE:
            raise Rejected("attachment_too_large", 422)
        result.append(Attachment(name, media, kind, data, text))
    if sum(len(a.data) for a in result) > MAX_TOTAL or sum(len(a.data) for a in result if a.kind == "image") > MAX_IMAGES:
        raise Rejected("attachments_too_large", 422)
    return tuple(result)
