"""Strict Nostr signatures using libsecp256k1; no home-grown cryptography."""
import base64
import binascii
import hashlib
import json
import re

from coincurve import PublicKeyXOnly
from radhouse.domain.tasks import Rejected


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _valid_tag(tag) -> bool:
    if not isinstance(tag, list) or not tag:
        return False
    # Official Buzz clients emit richer metadata for images and URL previews.
    # Keep the wider shape specific to those tags rather than weakening the
    # bound for every event tag.
    limit = 16 if tag[0] in {"imeta", "link-preview"} else 8
    return (
        len(tag) <= limit
        and all(isinstance(item, str) and len(item) <= 8192 for item in tag)
    )


def encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def verify_event(event: dict, kind: int) -> dict:
    try:
        if (not isinstance(event, dict) or set(event) != {"id", "pubkey", "created_at", "kind", "tags", "content", "sig"}
                or event["kind"] != kind or type(event["created_at"]) is not int
                or not isinstance(event["content"], str) or len(event["content"]) > 65536
                or not isinstance(event["tags"], list) or len(event["tags"]) > 4096
                or any(not _valid_tag(tag) for tag in event["tags"])):
            raise ValueError()
        for name, length in (("id", 64), ("pubkey", 64), ("sig", 128)):
            if not isinstance(event[name], str) or re.fullmatch("[a-f0-9]{" + str(length) + "}", event[name]) is None:
                raise ValueError()
        message = encoded([0, event["pubkey"], event["created_at"], event["kind"], event["tags"], event["content"]])
        event_id = sha256(message)
        # Exact lengths are checked above before entering Coincurve's C binding.
        if event_id != event["id"] or not PublicKeyXOnly(bytes.fromhex(event["pubkey"])).verify(
                bytes.fromhex(event["sig"]), bytes.fromhex(event_id)):
            raise ValueError()
        return event
    except (ValueError, TypeError, KeyError):
        raise Rejected("buzz_signature_denied", 401) from None


def nip98(header: str, url: str, method: str, body: bytes, now: int) -> tuple[dict, dict[str, str]]:
    try:
        if not header.startswith("Nostr ") or len(header) > 32768:
            raise ValueError()
        event = json.loads(base64.b64decode(header[6:], validate=True))
        verify_event(event, 27235)
        if event["content"] != "" or abs(now - event["created_at"]) > 30:
            raise ValueError()
        tags = {}
        for tag in event["tags"]:
            if len(tag) != 2 or tag[0] in tags:
                raise ValueError()
            tags[tag[0]] = tag[1]
        if (tags.get("u") != url or tags.get("method") != method
                or tags.get("payload") != sha256(body) or not 16 <= len(tags.get("nonce", "")) <= 200):
            raise ValueError()
        return event, tags
    except (ValueError, TypeError, binascii.Error, UnicodeError):
        raise Rejected("buzz_signature_denied", 401) from None
