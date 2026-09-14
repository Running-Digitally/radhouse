"""Explicit qualification against an exclusively owned, unmodified Buzz relay.

The launcher owns PostgreSQL, Redis and the relay process. These environment
variables contain synthetic identities, never operator credentials.
"""

from dataclasses import replace
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from types import SimpleNamespace

from coincurve import PrivateKey
import pytest

from radhouse.channels.buzz_enrollment import BuzzEnrollment, ConfiguredBuzzConversation
from radhouse.channels.buzz_relay import BuzzRelay
from radhouse.channels.nostr import encoded, sha256
from tests.test_buzz_relay import signed

pytestmark = pytest.mark.postgres


def test_real_relay_enrollment_dm_pagination_and_result(
    service, store, clock, alice, envelope
):
    origin = os.environ.get("RADHOUSE_OWNED_BUZZ_ORIGIN")
    if not origin:
        pytest.skip("requires the exclusively owned Buzz protocol fixture")
    assert origin.startswith("http://127.0.0.1:")
    clock.now = datetime.now(timezone.utc)
    owner_key = PrivateKey(bytes.fromhex(os.environ["RADHOUSE_OWNED_BUZZ_OWNER_KEY"]))
    agent_key = PrivateKey()
    relay_key = os.environ["RADHOUSE_OWNED_BUZZ_RELAY_KEY"]
    owner = BuzzRelay(origin, relay_key, owner_key.secret.hex())
    agent = BuzzRelay(origin, relay_key, agent_key.secret.hex())
    try:
        ack = owner._request("/events", owner.event(41010, "", [["p", agent.pubkey]]))
        assert ack["accepted"], ack
        message = json.loads(ack["message"].removeprefix("response:"))
        channel_id = message["channel_id"]
        candidate = SimpleNamespace(
            link_id="researcher",
            channel_id=None,
            conversation_id="personal-alice:alice:buzz",
            principal_id="alice",
            owner_pubkey=owner.pubkey,
            agent_pubkey=agent.pubkey,
            bot_id="bot-alpha",
            project_id="personal-alice",
            activated_at=int(clock().timestamp()),
            binding_revision=1,
            active=True,
        )
        with store.transaction() as tx:
            tx._connection.execute(
                "UPDATE channel_bindings SET subject=%s WHERE subject='alice@buzz'",
                (owner.pubkey,),
            )
            name = tx.bots("alice")[0].display_name
        directory = signed(
            owner_key,
            30177,
            [["d", agent.pubkey]],
            json.dumps({"name": name, "parallelism": 1, "respond_to": "owner-only"}),
            candidate.activated_at,
        )
        assert owner._request("/events", directory)["accepted"]
        attestation = [
            "auth",
            owner.pubkey,
            "",
            owner_key.sign_schnorr(
                bytes.fromhex(sha256(f"nostr:agent-auth:{agent.pubkey}:".encode()))
            ).hex(),
        ]
        configured = ConfiguredBuzzConversation(service, agent, candidate)
        registry = BuzzEnrollment(service, (configured,))
        actor = replace(
            alice,
            channel="buzz",
            subject=owner.pubkey,
            assurance_until=clock() + timedelta(minutes=10),
        )
        command = replace(
            envelope(), channel="buzz", conversation_id=candidate.conversation_id
        )
        assert registry.enroll(
            actor, command, candidate.link_id, channel_id, attestation
        )["ready"]
        profiles = owner.query(
            [{"kinds": [10100], "authors": [agent.pubkey], "limit": 1}]
        )
        assert json.loads(profiles[0]["content"])["channel_add_policy"] == "owner_only"
        print(
            "PASS actual relay: owner-signed directory, attestation, exact private DM and agent profiles"
        )
        # A native composer assignment reaches the controller through the real
        # relay. No model is used: only the existing synthetic execution port.
        reference = b"Prefer a quiet morning, walking and an early start."
        digest = sha256(reference)
        authorization = owner.event(
            24242,
            "Upload the synthetic reference",
            [
                ["t", "upload"],
                ["x", digest],
                ["server", origin.removeprefix("http://")],
                ["expiration", str(int(owner.clock()) + 60)],
            ],
        )
        upload = owner.client.put(
            origin + "/upload",
            content=reference,
            headers={
                "Content-Type": "text/plain",
                "X-SHA-256": digest,
                "Authorization": "Nostr "
                + base64.urlsafe_b64encode(encoded(authorization)).decode().rstrip("="),
            },
        )
        assert upload.status_code == 200, upload.text
        media = upload.json()
        assignment = owner.event(
            9,
            "Summarize the reference. Use no tools.",
            [
                ["h", channel_id],
                [
                    "imeta",
                    "url " + media["url"],
                    "x " + digest,
                    "m " + media["type"],
                    "size " + str(media["size"]),
                    "filename routine.txt",
                ],
            ],
        )
        owner.publish(assignment)
        assert configured.run("ingress")["error_code"] is None
        assert configured.run("ingress")["error_code"] is None
        with store.transaction() as tx:
            tasks = tx.tasks()
            assert len(tasks) == 1 and tasks[0].disable_tools
            assert tasks[0].files[0].content.encode() == reference
        service.run(tasks[0].task_id)
        assert configured.run("egress")["error_code"] is None
        results = owner.query(
            [
                {
                    "kinds": [9],
                    "authors": [agent.pubkey],
                    "#h": [channel_id],
                    "limit": 100,
                }
            ]
        )
        assert any(
            ["radhouse-review", tasks[0].task_id] in event["tags"] for event in results
        )
        print(
            "PASS actual relay: authenticated reference upload/retrieval, duplicate ingress, one task, signed Researcher result and protected-review locator"
        )
        # Timestamp ties straddle two pages: the real relay orders IDs ascending.
        timestamp = int(clock().timestamp())
        sent = []
        for index in range(105):
            event = owner.event(
                9, f"Status {index}", [["h", channel_id]], created_at=timestamp
            )
            sent.append(owner.publish(event))
        with store.transaction() as tx:
            link = tx.conversation_link(candidate.link_id)
        read = agent.messages(link, link.activated_at)
        assert set(sent).issubset({event["id"] for event in read})
        assert len(read) == 106
        print(
            "PASS actual relay: 106 messages across equal-timestamp cursor pages, no omissions"
        )
    finally:
        owner.close()
        agent.close()
