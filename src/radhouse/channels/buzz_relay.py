"""Bounded NIP-98 transport for an explicitly enrolled Radhouse agent key.

This adapter signs only as the agent. Task execution, human assurance and grants
remain outside it. Callers persist returned signed events before publication.
"""

import base64
import json
import secrets
import time
from urllib.parse import urlsplit

from coincurve import PrivateKey
import httpx

from radhouse.channels.nostr import encoded, sha256, verify_event
from radhouse.domain.conversations import ConversationLink
from radhouse.domain.tasks import Rejected


class BuzzRelay:
    def __init__(self, origin, relay_pubkey, key, *, transport=None, clock=time.time):
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.scheme == "http"
            and parsed.hostname not in {"127.0.0.1", "localhost"}
        ):
            raise ValueError("invalid_relay_origin")
        self.origin = origin.rstrip("/")
        self.relay_pubkey = relay_pubkey
        self._key = PrivateKey(bytes.fromhex(key))
        self.pubkey = self._key.public_key_xonly.format().hex()
        self.clock = clock
        self.owner_attestation = None
        self.client = httpx.Client(
            timeout=5, follow_redirects=False, trust_env=False, transport=transport
        )

    def close(self):
        self.client.close()

    def event(self, kind, content, tags=(), *, created_at=None):
        """Return one signed event; retries must reuse these exact bytes."""
        if kind not in {0, 9, 10100, 20001, 24242, 27235, 41010}:
            raise Rejected("buzz_event_kind_denied", 403)
        event = {
            "pubkey": self.pubkey,
            "kind": kind,
            "created_at": int(self.clock()) if created_at is None else created_at,
            "content": content,
            "tags": [list(tag) for tag in tags],
        }
        event["id"] = sha256(
            encoded(
                [0, event["pubkey"], event["created_at"], kind, event["tags"], content]
            )
        )
        event["sig"] = self._key.sign_schnorr(bytes.fromhex(event["id"])).hex()
        return verify_event(event, kind)

    def _request(self, path, value):
        if path not in {"/query", "/events"}:
            raise Rejected("buzz_route_denied", 403)
        body = encoded(value)
        if len(body) > 262144:
            raise Rejected("buzz_request_too_large", 413)
        url = self.origin + path
        auth = self.event(
            27235,
            "",
            (
                ("u", url),
                ("method", "POST"),
                ("payload", sha256(body)),
                ("nonce", secrets.token_hex(16)),
            ),
        )
        headers = {
            "Authorization": "Nostr " + base64.b64encode(encoded(auth)).decode(),
            "Content-Type": "application/json",
        }
        if self.owner_attestation is not None:
            headers["X-Auth-Tag"] = json.dumps(
                self.owner_attestation, separators=(",", ":")
            )
        try:
            deadline = time.monotonic() + 10
            with self.client.stream(
                "POST", url, content=body, headers=headers
            ) as response:
                if response.status_code != 200:
                    raise Rejected(
                        "buzz_relay_denied"
                        if response.status_code in {401, 403}
                        else "buzz_relay_unavailable",
                        503,
                    )
                data = bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic() > deadline or len(data) + len(chunk) > 1048576:
                        raise Rejected("buzz_response_limit", 503)
                    data.extend(chunk)
            return json.loads(data)
        except httpx.HTTPError, ValueError, UnicodeError:
            raise Rejected("buzz_relay_unavailable", 503) from None

    def query(self, filters):
        if not 1 <= len(filters) <= 4 or any(not f.get("kinds") for f in filters):
            raise Rejected("buzz_query_denied", 403)
        values = self._request("/query", filters)
        if not isinstance(values, list) or len(values) > 256:
            raise Rejected("buzz_response_invalid", 503)
        return values

    def publish(self, event):
        """Confirm the exact outgoing event, including a duplicate acknowledgment."""
        verify_event(event, event.get("kind"))
        if event["pubkey"] != self.pubkey:
            raise Rejected("buzz_author_denied", 403)
        value = self._request("/events", event)
        if (
            not isinstance(value, dict)
            or value.get("accepted") is not True
            or value.get("event_id") != event["id"]
        ):
            raise Rejected("buzz_delivery_unconfirmed", 503)
        return event["id"]

    def verify_dm(self, link: ConversationLink):
        """Require relay-signed immutable DM metadata and exact two-person membership."""
        if not link.active or link.agent_pubkey != self.pubkey:
            raise Rejected("conversation_link_denied", 403)
        values = self.query(
            [
                {
                    "kinds": [39000, 39002],
                    "authors": [self.relay_pubkey],
                    "#d": [link.channel_id],
                    "limit": 3,
                }
            ]
        )
        if len(values) != 2:
            raise Rejected("conversation_membership_denied", 403)
        snapshots = {}
        for value in values:
            kind = value.get("kind")
            if kind not in {39000, 39002} or kind in snapshots:
                raise Rejected("conversation_membership_denied", 403)
            event = verify_event(value, kind)
            if event["pubkey"] != self.relay_pubkey or [
                t for t in event["tags"] if t[0] == "d"
            ] != [["d", link.channel_id]]:
                raise Rejected("conversation_membership_denied", 403)
            snapshots[kind] = event
        metadata = snapshots[39000]["tags"]
        if ["private"] not in metadata or ["t", "dm"] not in metadata:
            raise Rejected("conversation_requires_private_dm", 403)
        tags = [t for t in snapshots[39002]["tags"] if t[0] == "p"]
        if (
            len(tags) != 2
            or {t[1] for t in tags if len(t) == 4} != {link.owner_pubkey, self.pubkey}
            or any(
                len(t) != 4 or t[3] not in {"member", "owner", "admin", "bot"}
                for t in tags
            )
        ):
            raise Rejected("conversation_membership_denied", 403)
        return snapshots

    def history_page(self, link: ConversationLink, since: int, before=None):
        query = {
            "kinds": [9],
            "authors": [link.owner_pubkey],
            "#h": [link.channel_id],
            "since": max(since, link.activated_at),
            "limit": 100,
        }
        if before is not None:
            query.update(until=before[0], before_id=before[1])
        values = self.query([query])
        if len(values) > 100:
            raise Rejected("conversation_history_window_full", 503)
        result = []
        seen = set()
        for value in values:
            event = verify_event(value, 9)
            after_cursor = (
                before is None
                or event["created_at"] < before[0]
                or (event["created_at"] == before[0] and event["id"] > before[1])
            )
            if (
                event["pubkey"] != link.owner_pubkey
                or [t for t in event["tags"] if t[0] == "h"] != [["h", link.channel_id]]
                or event["created_at"] < max(since, link.activated_at)
                or event["created_at"] > int(self.clock()) + 30
                or not after_cursor
                or event["id"] in seen
                or any(t[0] == "radhouse-mirror" for t in event["tags"])
            ):
                raise Rejected("conversation_event_denied", 403)
            seen.add(event["id"])
            result.append(event)
        result.sort(key=lambda e: (-e["created_at"], e["id"]))
        cursor = (
            (result[-1]["created_at"], result[-1]["id"]) if len(result) == 100 else None
        )
        return result, cursor

    def messages(self, link: ConversationLink, since: int):
        """Read a bounded burst with keyset pagination, including timestamp ties."""
        result = []
        before = None
        for _ in range(10):
            page, before = self.history_page(link, since, before)
            result.extend(page)
            if before is None:
                return sorted(result, key=lambda e: (e["created_at"], e["id"]))
        raise Rejected("conversation_history_window_full", 503)
