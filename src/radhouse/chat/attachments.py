"""Original files are independent of bounded automatic reading operations."""
from dataclasses import dataclass
import base64
import binascii
import hashlib
from io import BytesIO
from pathlib import Path, PurePath
import re

from radhouse.domain.tasks import InputFile, Rejected

# These are reader/inline transport budgets, never upload admission limits.
MAX_IMAGE = 4 * 1024 * 1024
MAX_IMAGES = 8 * 1024 * 1024
MAX_TEXT = 128 * 1024
OFFICE = {".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
AUDIO = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".ogg": "audio/ogg",
         ".flac": "audio/flac", ".webm": "audio/webm"}
FILE_ID = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")


def validate_name(name):
    if not name or len(name) > 200 or re.search(r'[/\\\x00-\x1f\x7f]', name):
        raise Rejected("attachment_invalid", 422)


def classify(name, prefix):
    """Sniff only a small prefix. Unrecognized originals remain downloadable."""
    validate_name(name)
    extension = PurePath(name).suffix.lower()
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png", "image"
    if prefix.startswith(b"\xff\xd8\xff"): return "image/jpeg", "image"
    if prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP": return "image/webp", "image"
    if extension == ".pdf" and prefix.startswith(b"%PDF-"): return "application/pdf", "document"
    if extension in OFFICE and prefix.startswith(b"PK\x03\x04"): return OFFICE[extension], "document"
    valid_audio = ((extension == ".wav" and prefix[:4] == b"RIFF" and prefix[8:12] == b"WAVE")
        or (extension == ".mp3" and (prefix.startswith(b"ID3") or len(prefix) >= 2 and prefix[0] == 255 and prefix[1] & 224 == 224))
        or (extension == ".m4a" and prefix[4:8] == b"ftyp") or (extension == ".ogg" and prefix.startswith(b"OggS"))
        or (extension == ".flac" and prefix.startswith(b"fLaC")) or (extension == ".webm" and prefix.startswith(b"\x1aE\xdf\xa3")))
    if valid_audio: return AUDIO[extension], "audio"
    if extension in (*OFFICE, *AUDIO, ".pdf", ".doc", ".xls", ".ppt", ".docm", ".xlsm", ".pptm", ".svg", ".gif", ".heic"):
        return "application/octet-stream", "file"
    try:
        # A prefix may end part way through a UTF-8 codepoint.
        import codecs
        text = codecs.getincrementaldecoder("utf-8-sig")().decode(prefix, final=False)
        if any(ord(c) < 32 and c not in "\n\r\t" for c in text): raise ValueError()
    except ValueError: return "application/octet-stream", "file"
    return "text/plain", "text"


@dataclass(frozen=True)
class Attachment:
    name: str
    media_type: str
    kind: str
    data: bytes | Path
    reference_text: str | None = None
    file_id: str | None = None
    stored_sha256: str | None = None
    stored_size: int | None = None
    reading_state: str | None = None
    reading_error: str | None = None

    @property
    def sha256(self):
        if self.stored_sha256 is not None: return self.stored_sha256
        return hashlib.sha256(self.data).hexdigest()

    @property
    def size(self):
        return self.stored_size if self.stored_size is not None else len(self.data)

    def open(self):
        return self.data.open("rb") if isinstance(self.data, Path) else BytesIO(self.data)

    def identity(self):
        return (self.name, self.media_type, self.sha256, self.file_id)

    def image(self):
        with self.open() as stream:
            data = stream.read(MAX_IMAGE + 1)
        if len(data) > MAX_IMAGE: raise Rejected("image_reading_unavailable", 422)
        return InputFile(self.name, base64.b64encode(data).decode(), self.media_type, "base64", self.sha256)


def decode_uploads(values):
    """Byte fixture helper; HTTP clients use streamed originals and file IDs."""
    result = []
    for value in values:
        name = value["name"]
        validate_name(name)
        try: data = base64.b64decode(value["content"], validate=True)
        except ValueError: raise Rejected("attachment_invalid", 422) from None
        media, kind = classify(name, data[:4096])
        result.append(Attachment(name, media, kind, data))
    return tuple(result)
