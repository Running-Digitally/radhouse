from dataclasses import replace
import json

from coincurve import PrivateKey
import httpx
import pytest

from radhouse.channels.buzz_relay import BuzzRelay
from radhouse.channels.nostr import encoded, nip98, sha256, verify_event
from radhouse.domain.conversations import ConversationLink
from radhouse.domain.tasks import Rejected


def signed(key, kind, tags, content="", now=1700000000):
    pubkey = key.public_key_xonly.format().hex()
    identity = sha256(encoded([0, pubkey, now, kind, tags, content]))
    return dict(
        id=identity,
        pubkey=pubkey,
        created_at=now,
        kind=kind,
        tags=tags,
        content=content,
        sig=key.sign_schnorr(bytes.fromhex(identity)).hex(),
    )


@pytest.fixture
def relay():
    agent, owner, authority = PrivateKey(), PrivateKey(), PrivateKey()
    pk = lambda k: k.public_key_xonly.format().hex()
    link = ConversationLink(
        "link",
        "dm-1",
        "personal:owner:buzz",
        "owner",
        pk(owner),
        pk(agent),
        "researcher",
        "personal",
        1700000000,
    )
    state = {"response": [], "calls": [], "status": 200}

    def receive(request):
        assert request.method == "POST" and request.url.host == "relay.test"
        auth, _ = nip98(
            request.headers["Authorization"],
            str(request.url),
            "POST",
            request.content,
            1700000000,
        )
        assert auth["pubkey"] == pk(agent)
        state["calls"].append(
            (request.url.path, json.loads(request.content), auth["id"])
        )
        if "raw" in state:
            return httpx.Response(state["status"], content=state["raw"])
        return httpx.Response(state["status"], json=state["response"])

    client = BuzzRelay(
        "https://relay.test",
        pk(authority),
        agent.secret.hex(),
        transport=httpx.MockTransport(receive),
        clock=lambda: 1700000000,
    )
    yield client, link, state, owner, authority
    client.close()


def snapshots(link, authority, members=None, *, private=True, kind="dm"):
    members = members if members is not None else [link.owner_pubkey, link.agent_pubkey]
    metadata = [["d", link.channel_id], ["t", kind]] + (
        [["private"]] if private else [["public"]]
    )
    return [
        signed(authority, 39000, metadata),
        signed(
            authority,
            39002,
            [["d", link.channel_id]] + [["p", pk, "", "member"] for pk in members],
        ),
    ]


def test_official_client_image_metadata_keeps_a_strict_bound():
    owner = PrivateKey()
    image = [
        "imeta",
        "url https://relay.test/media/" + "a" * 64 + ".png",
        "m image/png",
        "x " + "a" * 64,
        "size 1024",
        "dim 1200x900",
        "blurhash placeholder",
        "thumb https://relay.test/media/thumb.png",
        "filename preview.png",
    ]
    event = signed(owner, 9, [["h", "dm-1"], image])
    assert verify_event(event, 9) == event

    oversized = signed(
        owner, 9, [["imeta", *[f"field{index} value" for index in range(16)]]]
    )
    with pytest.raises(Rejected, match="buzz_signature_denied"):
        verify_event(oversized, 9)


def test_official_client_link_preview_metadata_keeps_a_strict_bound():
    owner = PrivateKey()
    preview = [
        "link-preview",
        "url https://builder-preview.runningdigitally.com",
        "title Two Person Expenses",
        "description Private Builder preview",
        "m text/html",
        "image https://relay.test/media/preview.png",
        "image_mime image/png",
        "image_width 1200",
        "image_height 630",
        "site builder-preview.runningdigitally.com",
        "favicon https://builder-preview.runningdigitally.com/favicon.ico",
    ]
    event = signed(owner, 9, [["h", "dm-1"], preview])
    assert verify_event(event, 9) == event

    oversized = signed(
        owner,
        9,
        [["link-preview", *[f"field{index} value" for index in range(16)]]],
    )
    with pytest.raises(Rejected, match="buzz_signature_denied"):
        verify_event(oversized, 9)


def test_exact_private_dm_and_fresh_signed_requests(relay):
    client, link, state, _, authority = relay
    state["response"] = snapshots(link, authority)
    client.verify_dm(link)
    client.verify_dm(link)
    assert state["calls"][0][2] != state["calls"][1][2]
    assert state["calls"][0][1] == [
        {
            "kinds": [39000, 39002],
            "authors": [client.relay_pubkey],
            "#d": ["dm-1"],
            "limit": 3,
        }
    ]


def test_exact_private_group_dm_membership(relay):
    client, link, state, _, authority = relay
    teammate = PrivateKey().public_key_xonly.format().hex()
    group = replace(
        link,
        member_pubkeys=tuple(sorted((link.agent_pubkey, teammate))),
    )
    state["response"] = snapshots(
        group, authority, [group.owner_pubkey, group.agent_pubkey, teammate]
    )
    client.verify_dm(group)

    state["response"] = snapshots(group, authority)
    with pytest.raises(Rejected, match="conversation_membership_denied"):
        client.verify_dm(group)


@pytest.mark.parametrize(
    "change",
    ["extra", "missing", "public", "room", "wrong_relay", "wrong_channel", "inactive"],
)
def test_membership_and_history_boundary_denies_before_read(relay, change):
    client, link, state, _, authority = relay
    members = [link.owner_pubkey, link.agent_pubkey]
    if change == "extra":
        members.append(PrivateKey().public_key_xonly.format().hex())
    if change == "missing":
        members.pop()
    state["response"] = snapshots(
        link,
        PrivateKey() if change == "wrong_relay" else authority,
        members,
        private=change != "public",
        kind="stream" if change == "room" else "dm",
    )
    if change == "wrong_channel":
        link = replace(link, channel_id="another")
    if change == "inactive":
        link = replace(link, active=False)
    with pytest.raises(Rejected):
        client.verify_dm(link)


def test_duplicate_delivery_reuses_signed_event_but_new_transport_nonce(relay):
    client, link, state, _, _ = relay
    event = client.event(9, "I have your assignment.", (("h", link.channel_id),))
    state["response"] = {
        "accepted": True,
        "event_id": event["id"],
        "message": "duplicate: already processed",
    }
    assert client.publish(event) == client.publish(event) == event["id"]
    assert state["calls"][0][1] == state["calls"][1][1]
    assert state["calls"][0][2] != state["calls"][1][2]


@pytest.mark.parametrize(
    "response", [{}, [], {"accepted": False}, {"accepted": True, "event_id": "wrong"}]
)
def test_delivery_requires_exact_acknowledgment(relay, response):
    client, _, state, *_ = relay
    state["response"] = response
    with pytest.raises(Rejected, match="buzz_delivery_unconfirmed"):
        client.publish(client.event(9, "reply"))


@pytest.mark.parametrize(
    "path,status,body,expected",
    [
        ("/events", 400, {"error": "invalid: root tag does not match thread ancestry"}, "buzz_thread_ancestry_rejected"),
        ("/query", 400, {"error": "invalid: root tag does not match thread ancestry"}, "buzz_relay_unavailable"),
        ("/events", 401, {"error": "invalid: root tag does not match thread ancestry"}, "buzz_relay_denied"),
        ("/events", 403, {"error": "invalid: root tag does not match thread ancestry"}, "buzz_relay_denied"),
        ("/events", 500, {"error": "invalid: root tag does not match thread ancestry"}, "buzz_relay_unavailable"),
        ("/events", 400, {"error": "invalid: reply target not found"}, "buzz_relay_unavailable"),
        ("/events", 400, {"error": "invalid: root tag does not match thread ancestry", "extra": True}, "buzz_relay_unavailable"),
        ("/events", 400, [], "buzz_relay_unavailable"),
    ],
)
def test_only_exact_ancestry_rejection_is_permanent(relay, path, status, body, expected):
    client, _, state, *_ = relay
    state.update(status=status, response=body)
    with pytest.raises(Rejected, match=expected):
        client._request(path, {})


@pytest.mark.parametrize("raw,expected", [
    (b"not-json", "buzz_relay_unavailable"),
    (b"x" * 1048577, "buzz_response_limit"),
])
def test_ancestry_error_body_remains_bounded_and_validated(relay, raw, expected):
    client, _, state, *_ = relay
    state.update(status=400, raw=raw)
    with pytest.raises(Rejected, match=expected):
        client.publish(client.event(9, "reply"))


def test_read_preserves_oldest_first_order_and_rejects_saturation(relay):
    client, link, state, owner, _ = relay
    state["response"] = [
        signed(owner, 9, [["h", link.channel_id]], "later", 1700000001),
        signed(owner, 9, [["h", link.channel_id]], "first"),
    ]
    assert [e["content"] for e in client.messages(link, 0)] == ["first", "later"]
    state["response"] *= 51
    with pytest.raises(Rejected, match="conversation_history_window_full"):
        client.messages(link, 0)


@pytest.mark.parametrize(
    "change", ["author", "channel", "before", "future", "mirror", "signature"]
)
def test_ingress_rejects_unadmitted_or_mirrored_events(relay, change):
    client, link, state, owner, _ = relay
    tags = [["h", "elsewhere" if change == "channel" else link.channel_id]]
    if change == "mirror":
        tags.append(["radhouse-mirror", "message"])
    event = signed(
        PrivateKey() if change == "author" else owner,
        9,
        tags,
        "message",
        1699999999
        if change == "before"
        else 1700000100
        if change == "future"
        else 1700000000,
    )
    if change == "signature":
        event["content"] = "changed"
    state["response"] = [event]
    with pytest.raises(Rejected):
        client.messages(link, 0)


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
def test_relay_error_is_not_empty_history(relay, status):
    client, link, state, *_ = relay
    state["status"] = status
    with pytest.raises(Rejected):
        client.messages(link, 0)


@pytest.mark.parametrize(
    "origin",
    [
        "http://remote.test",
        "https://user:pass@relay.test",
        "https://relay.test/path",
        "https://relay.test?x=1",
    ],
)
def test_origin_is_pinned(origin):
    with pytest.raises(ValueError, match="invalid_relay_origin"):
        BuzzRelay(origin, "0" * 64, PrivateKey().secret.hex())
