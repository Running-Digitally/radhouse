from dataclasses import asdict, replace
from types import SimpleNamespace
import json

from coincurve import PrivateKey
from fastapi.testclient import TestClient
import pytest

from radhouse.api.app import create_app
from radhouse.channels.buzz_enrollment import BuzzEnrollment, ConfiguredBuzzConversation
from radhouse.channels.nostr import sha256
from radhouse.domain.tasks import Rejected
from tests.test_buzz_conversations import bridge
from tests.test_buzz_relay import signed

pytestmark = pytest.mark.postgres


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
                {"name": bot.display_name, "parallelism": 1, "respond_to": "owner-only"}
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


def test_enrollment_api_returns_only_public_receipt(enrollment, service):
    registry, _, _, actor, command, attestation, link = enrollment
    with TestClient(
        create_app(service, lambda request: actor, enrollment=registry)
    ) as client:
        query = {
            "conversation_id": command.conversation_id,
            "binding_revision": command.binding_revision,
        }
        candidates = client.get("/agent-enrollment", params=query)
        assert candidates.status_code == 200 and len(candidates.json()) == 1
        response = client.post(
            "/agent-enrollment",
            json={
                "envelope": asdict(command),
                "link_id": link.link_id,
                "channel_id": link.channel_id,
                "attestation": attestation,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["ready"]
        history = client.get(f"/conversations/{link.link_id}/messages", params=query)
        assert history.status_code == 200
        assert attestation[3] not in history.text + response.text + candidates.text


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
