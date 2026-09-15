from dataclasses import asdict, replace
from types import SimpleNamespace
import json

from coincurve import PrivateKey
from fastapi.testclient import TestClient
import pytest

from radhouse.api.app import create_app
from radhouse.channels.buzz_enrollment import (
    BuzzEnrollment,
    ConfiguredBuzzConversation,
    agent_profile_events,
)
from radhouse.channels.nostr import sha256
from radhouse.domain.tasks import Rejected
from tests.test_buzz_conversations import bridge
from tests.test_buzz_relay import signed

pytestmark = pytest.mark.postgres


def test_standard_buzz_profile_uses_the_configured_agent_role():
    class Relay:
        @staticmethod
        def event(kind, content, tags=None):
            return {"kind": kind, "content": content, "tags": tags or []}

    events = agent_profile_events(
        Relay(), SimpleNamespace(display_name="Builder", role_name="Builder"), ["attestation"]
    )

    profile = json.loads(events[0]["content"])
    capability = json.loads(events[1]["content"])
    assert profile["about"].startswith("Your Radhouse Builder.")
    assert capability["capabilities"] == ["builder"]

    researcher = agent_profile_events(
        Relay(), SimpleNamespace(display_name="Researcher", role_name="Researcher"), ["attestation"]
    )
    assert json.loads(researcher[1]["content"])["capabilities"] == ["research"]


@pytest.fixture
def enrollment(bridge, service, store, alice, envelope):
    cycle, state, owner = bridge
    candidate = SimpleNamespace(
        **{**asdict(cycle.link), "channel_id": None, "activated_at": None}
    )
    configured = ConfiguredBuzzConversation(service, cycle.relay, candidate)
    registry = BuzzEnrollment(service, (configured,))
    actor = replace(alice, channel="buzz", subject=cycle.link.owner_pubkey)
    command = replace(
        envelope(), channel="buzz", conversation_id=cycle.link.conversation_id
    )
    attestation = [
        "auth",
        cycle.link.owner_pubkey,
        "",
        owner.sign_schnorr(
            bytes.fromhex(
                sha256(f"nostr:agent-auth:{cycle.link.agent_pubkey}:".encode())
            )
        ).hex(),
    ]
    with store.transaction() as tx:
        bot = tx.bots(actor.principal_id)[0]
        # Remove the fixture's direct link so production enrollment owns it.
        tx._connection.execute(
            "DELETE FROM conversation_links WHERE link_id=%s", (cycle.link.link_id,)
        )
    state["directory"] = [
        signed(
            owner,
            30177,
            [["d", cycle.link.agent_pubkey]],
            json.dumps(
                {
                    "name": bot.display_name,
                    "persona_id": "9ab045df-eacf-4645-86b5-6d47bdac621a",
                    "parallelism": 10,
                    "respond_to": "owner-only",
                }
            ),
            cycle.link.activated_at,
        )
    ]
    return registry, configured, state, actor, command, attestation, cycle.link


def test_enrollment_lost_ack_retains_profiles_and_finishes_without_new_identity(
    enrollment, store
):
    registry, configured, state, actor, command, attestation, link = enrollment
    assert configured.run("ingress")["enrollment"] == "pending"
    state["lost_ack"] = True
    with pytest.raises(Rejected, match="buzz_relay_unavailable"):
        registry.enroll(actor, command, link.link_id, link.channel_id, attestation)
    with store.transaction() as tx:
        saved = tx.conversation_enrollment(link.link_id)
        assert not saved["ready"]
        identities = [event["id"] for event in saved["events"]]
    assert configured.run("ingress")["enrollment"] == "pending"
    assert registry.enroll(actor, command, link.link_id, link.channel_id, attestation)[
        "ready"
    ]
    assert sorted(state["published"]) == sorted(identities)
    assert configured.run("ingress")["error_code"] is None
    assert configured.run("egress")["error_code"] is None


@pytest.mark.parametrize(
    "change", ["owner", "key", "directory", "channel", "assurance", "grant"]
)
def test_enrollment_rejects_changed_authority_before_profile_publication(
    enrollment, store, change
):
    registry, _, state, actor, command, attestation, link = enrollment
    if change == "owner":
        actor = replace(actor, subject="0" * 64)
    if change == "key":
        attestation[3] = "0" * 128
    if change == "directory":
        state["directory"] = []
    if change == "channel":
        link = replace(link, channel_id="not-a-dm")
    if change == "assurance":
        actor = replace(actor, assurance_until=None)
    if change == "grant":
        with store.transaction() as tx:
            tx._connection.execute("DELETE FROM bot_grants WHERE principal_id='alice'")
    with pytest.raises(Rejected):
        registry.enroll(actor, command, link.link_id, link.channel_id, attestation)
    assert not state["published"]
    with store.transaction() as tx:
        assert tx.conversation_link(link.link_id) is None


def test_native_enrollment_http_surface_is_removed(service, alice):
    with TestClient(create_app(service, lambda request: alice)) as client:
        assert client.get("/agent-enrollment").status_code == 404
        assert client.post("/agent-enrollment", json={}).status_code == 404
        assert client.get("/buzz/auth/session").status_code == 404
        assert client.post("/buzz/tasks", json={}).status_code == 404


def test_candidate_removal_or_change_stops_an_enrolled_worker(enrollment):
    registry, configured, _, actor, command, attestation, link = enrollment
    registry.enroll(actor, command, link.link_id, link.channel_id, attestation)
    configured.candidate.project_id = "different-project"
    assert configured.run("ingress")["error_code"] == "buzz_agent_enrollment_conflict"


def test_corrupt_saved_delegation_stops_only_its_conversation(enrollment, store):
    registry, configured, _, actor, command, attestation, link = enrollment
    registry.enroll(actor, command, link.link_id, link.channel_id, attestation)
    with store.transaction() as tx:
        saved = tx.conversation_enrollment(link.link_id)
        saved["auth_tag"][3] = "0" * 128
        tx.save_conversation_enrollment(link.link_id, saved)
    assert configured.run("ingress")["error_code"] == "buzz_agent_attestation_denied"
