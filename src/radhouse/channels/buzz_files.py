"""Read signed text references from this relay's content-addressed media store."""

import base64
import json
import re
import time
from urllib.parse import urlsplit

import httpx

from radhouse.channels.nostr import encoded, sha256
from radhouse.domain.tasks import InputFile, Rejected


def reference_files(relay, event):
    tags = [tag for tag in event["tags"] if tag[0] == "imeta"]
    if len(tags) > 4 or any(tag[0] == "url" for tag in event["tags"]):
        raise Rejected("conversation_attachment_invalid", 422)
    files = []
    remaining = 65536
    for tag in tags:
        fields = {}
        for item in tag[1:]:
            key, separator, value = item.partition(" ")
            if not separator or key in fields:
                raise Rejected("conversation_attachment_invalid", 422)
            fields[key] = value
        url = fields.get("url", "")
        parsed = urlsplit(url)
        origin = urlsplit(relay.origin)
        match = re.fullmatch(
            r"/media/([a-f0-9]{64})(?:\.([a-z0-9]{1,10}))?", parsed.path
        )
        if (
            parsed.scheme != origin.scheme
            or parsed.netloc != origin.netloc
            or parsed.query
            or parsed.fragment
            or not match
            or fields.get("x", match[1]) != match[1]
        ):
            raise Rejected("conversation_attachment_denied", 422)
        digest = match[1]
        name = fields.get(
            "filename", fields.get("alt", "reference-" + digest[:8] + ".txt")
        )
        if not name or len(name) > 200 or any(ord(c) < 32 or c in "/\\" for c in name):
            name = "reference-" + digest[:8] + ".txt"
        auth = relay.event(
            24242,
            "Read attached reference",
            [
                ["t", "get"],
                ["x", digest],
                ["server", origin.netloc],
                ["expiration", str(int(relay.clock()) + 60)],
            ],
        )
        header = "Nostr " + base64.urlsafe_b64encode(encoded(auth)).decode().rstrip("=")
        headers = {"Authorization": header}
        if relay.owner_attestation is not None:
            headers["X-Auth-Tag"] = json.dumps(
                relay.owner_attestation, separators=(",", ":")
            )
        try:
            deadline = time.monotonic() + 10
            with relay.client.stream("GET", url, headers=headers) as response:
                if response.status_code != 200:
                    raise Rejected("conversation_attachment_unavailable", 503)
                mime = (
                    response.headers.get("content-type", "").partition(";")[0].lower()
                )
                if mime not in {
                    "text/plain",
                    "text/markdown",
                    "text/csv",
                    "application/json",
                    "application/octet-stream",
                }:
                    raise Rejected("conversation_attachment_requires_text", 422)
                data = bytearray()
                for chunk in response.iter_bytes():
                    if (
                        time.monotonic() > deadline
                        or len(data) + len(chunk) > remaining
                    ):
                        raise Rejected("conversation_attachment_too_large", 422)
                    data.extend(chunk)
            if sha256(data) != digest:
                raise Rejected("conversation_attachment_digest_mismatch", 422)
            content = data.decode("utf-8")
            if "\x00" in content:
                raise Rejected("conversation_attachment_requires_text", 422)
        except UnicodeError:
            raise Rejected("conversation_attachment_requires_text", 422) from None
        except httpx.HTTPError:
            raise Rejected("conversation_attachment_unavailable", 503) from None
        remaining -= len(data)
        files.append(InputFile(name, content))
    return tuple(files)
