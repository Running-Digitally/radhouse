import base64
from dataclasses import replace
import json

from fastapi.testclient import TestClient
import pytest

from radhouse.api.app import create_app
from radhouse.application.review_links import ReviewLinks, TTL
from radhouse.application.conversations import Conversations
from radhouse.domain.conversations import ConversationMessage
from radhouse.domain.tasks import Rejected
from tests.test_buzz_conversations import bridge, incoming
from tests.test_buzz_enrollment import enrollment
from tests.test_local_reauthentication import local_client, login

pytestmark = pytest.mark.postgres


@pytest.fixture
def review_link(enrollment, service, store, bridge):
    registry, configured, state, actor, command, attestation, link = enrollment
    registry.enroll(actor, command, link.link_id, link.channel_id, attestation)
    state["published"].clear()
    service.review_links = ReviewLinks(service, "https://radhouse.test", (configured,))
    app = Conversations(service)
    event = incoming(bridge[0], bridge[2], "Use no tools. Give a short synthetic summary.")
    state["messages"].append(event)
    message = ConversationMessage(event["id"], link.link_id, link.principal_id,
                                  event["content"], "buzz", link.activated_at)
    app.receive(link, message, event=event)
    selected = app.process(link, message.message_id)
    done = service.run(selected.task_id)
    assert done.outcome == "completed"
    with store.transaction() as tx:
        url = service.review_links.issue(tx, link, done)
    return url.split("#review=")[1], done, configured, state, link


def test_review_locator_is_authenticated_navigation_only(review_link, service, alice, store):
    token, done, _, _, link = review_link
    target = service.review_links.resolve(alice, token)
    assert target == {"task_id": done.task_id, "project_id": done.project_id,
                      "conversation_id": "personal-alice:alice:radhouse", "binding_revision": 1}
    assert service.review_links.resolve(alice, token) == target
    with store.transaction() as tx:
        assert tx.publication(done.task_id) is None
        assert len(tx.tasks()) == 1
    with TestClient(create_app(service, lambda request: None)) as client:
        assert client.post("/reviews/resolve", json={"locator": token}).status_code == 401
        assert client.get(f"/tasks/{done.task_id}", params={"review": token}).status_code == 401


@pytest.mark.parametrize("change", ["signature", "payload", "expired", "future", "audience", "assurance", "channel",
                                     "candidate", "binding", "web_binding", "grant", "project", "digest", "attestation", "enrollment", "malformed", "oversized"])
def test_locator_rejects_changed_data_or_authority(review_link, service, alice, store, clock, change):
    token, done, configured, _, link = review_link
    if change == "signature": token = token[:-1] + ("0" if token[-1] != "0" else "1")
    if change == "payload":
        body, sig = token.split(".")
        value = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        value["task_id"] = "00000000-0000-0000-0000-000000000000"
        token = base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=") + "." + sig
    if change == "expired": clock.advance(seconds=TTL)
    if change == "future": clock.advance(seconds=-1)
    if change == "audience": alice = replace(alice, principal_id="bob")
    if change == "assurance": alice = replace(alice, assurance_until=None)
    if change == "channel": alice = replace(alice, channel="buzz")
    if change == "candidate": configured.candidate.active = False
    if change == "malformed": token = "bad"
    if change == "oversized": token = "x" * 10000
    with store.transaction() as tx:
        if change == "binding": tx._connection.execute("UPDATE channel_bindings SET active=false WHERE channel='buzz'")
        if change == "web_binding": tx._connection.execute("UPDATE channel_bindings SET active=false WHERE channel='radhouse'")
        if change == "grant": tx._connection.execute("DELETE FROM bot_grants WHERE principal_id='alice'")
        if change == "project": tx._connection.execute("UPDATE projects SET state='archived' WHERE project_id=%s", (link.project_id,))
        if change == "digest": tx.save_task(replace(done, result_digest="0" * 64, state_revision=done.state_revision+1), done.state_revision)
        if change in {"attestation", "enrollment"}:
            saved = tx.conversation_enrollment(link.link_id)
            if change == "attestation": saved["auth_tag"][3] = "0" * 128
            else: saved["ready"] = False
            tx.save_conversation_enrollment(link.link_id, saved)
    with pytest.raises(Rejected): service.review_links.resolve(alice, token)


def test_real_cookie_csrf_and_mfa_still_required(review_link, local_client, service, clock):
    token, _, _, _, _ = review_link
    client, auth, totp, password = local_client
    body = {"locator": token}
    assert client.post("/reviews/resolve", json=body).status_code == 401
    signed = login(client, password, totp.at(clock()))
    assert signed.status_code == 200
    assert client.post("/reviews/resolve", json=body).status_code == 403
    headers = {"Origin": "https://radhouse.test", "X-Radhouse-CSRF": signed.json()["csrf_token"]}
    result = client.post("/reviews/resolve", json=body, headers=headers)
    assert result.status_code == 200
    assert result.headers["Cache-Control"] == "no-store"
    clock.advance(minutes=11)
    assert client.post("/reviews/resolve", json=body, headers=headers).json()["code"] == "fresh_assurance_required"
    assert client.post("/auth/reauthenticate", headers=headers,
                       json={"password": password, "totp_code": totp.at(clock())}).status_code == 200
    assert client.post("/reviews/resolve", json=body, headers=headers).status_code == 200


def test_completion_and_publication_are_stable_across_recovery(review_link, service, store, alice, envelope, clock):
    token, done, configured, state, link = review_link
    assert configured.run("egress")["error_code"] is None
    completion = [e for e in state["published"].values() if ["radhouse-review", done.task_id] in e["tags"]]
    assert len(completion) == 1 and "https://radhouse.test/app/#review=" in completion[0]["content"]
    assert "Review required" in completion[0]["content"]
    assert ["radhouse-result", done.result_digest] in completion[0]["tags"]
    url = completion[0]["content"].split("https://radhouse.test/app/#review=")[1]
    assert service.review_links.resolve(alice, url)["task_id"] == done.task_id
    reviewed = service.prepare_review(alice, done.task_id, done.state_revision, ("alice",), 120, envelope=envelope())
    publication = service.publish(alice, envelope(), reviewed.review_id, reviewed.revision, done.result, ("alice",))
    state["lost_ack"] = True
    assert configured.run("egress")["error_code"] == "buzz_relay_unavailable"
    assert configured.run("egress")["error_code"] is None
    clock.advance(minutes=20)
    assert configured.run("egress")["error_code"] is None
    with store.transaction() as tx:
        messages = [r["message"] for r in tx.conversation_history(link.link_id)]
        statuses = [m for m in messages if m.state == "publication"]
        assert len(statuses) == 1 and statuses[0].message_id == "publication:" + publication.publication_id
        assert tx.task(done.task_id).state_revision == done.state_revision
        anchor = tx.conversation_task_anchor(link, done.task_id)
    event = next(e for e in state["published"].values() if ["radhouse-mirror", "publication:" + publication.publication_id] in e["tags"])
    assert ["e", anchor, "", "reply"] in event["tags"]
    assert "Approved and published" in event["content"]
    assert ["radhouse-result", done.result_digest] in event["tags"]
    assert len([e for e in state["published"].values() if ["radhouse-review", done.task_id] in e["tags"]]) == 1
    app = Conversations(service)
    status = ConversationMessage("status-published", link.link_id, link.principal_id,
                                 "status", "buzz", int(clock().timestamp()))
    app.receive(link, status)
    app.process(link, status.message_id)
    with store.transaction() as tx:
        content = tx.conversation_message("reply:status-published")["message"].content
    assert "Approved and published" in content and "#review=" not in content


def test_expired_completion_is_not_rewritten_and_status_gets_fresh_link(review_link, service, store, alice, clock, fake_work):
    _, done, configured, state, link = review_link
    configured.run("egress")
    original = dict(state["published"])
    clock.advance(seconds=TTL + 1)
    configured.run("egress")
    assert state["published"] == original
    app = Conversations(service)
    message = ConversationMessage("status-new", link.link_id, link.principal_id,
                                  "status", "buzz", int(clock().timestamp()))
    app.receive(link, message)
    assert app.process(link, message.message_id).task_id == done.task_id
    with store.transaction() as tx:
        content = tx.conversation_message("reply:status-new")["message"].content
        assert len(tx.tasks()) == 1
    assert "Review required" in content
    from datetime import timedelta
    target = service.review_links.resolve(replace(alice, assurance_until=clock()+timedelta(minutes=10)), content.split("#review=")[1])
    assert target["task_id"] == done.task_id
    assert fake_work.start_count == 1


@pytest.mark.parametrize("change", ["forged_key", "wrong_domain", "unknown_field", "duplicate_field"])
def test_locator_canonical_encoding_and_signing_domain(review_link, service, alice, change):
    from coincurve import PrivateKey
    from radhouse.application.review_links import ReviewLocator
    from radhouse.channels.nostr import sha256
    token, _, configured, _, _ = review_link
    body, sig = token.split(".")
    raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    value = json.loads(raw)
    if change == "forged_key":
        key = PrivateKey()
        value["agent_pubkey"] = key.public_key_xonly.format().hex()
        locator = ReviewLocator(**value)
        raw = locator.model_dump_json().encode()
        sig = key.sign_schnorr(locator.signing_digest()).hex()
    if change == "wrong_domain": sig = configured.relay._key.sign_schnorr(bytes.fromhex(sha256(raw))).hex()
    if change == "unknown_field": raw = raw[:-1] + b',"return_to":"https://elsewhere.test"}'
    if change == "duplicate_field": raw = b'{"version":1,' + raw[1:]
    token = base64.urlsafe_b64encode(raw).decode().rstrip("=") + "." + sig
    with pytest.raises(Rejected): service.review_links.resolve(alice, token)


def test_long_result_is_labelled_preview_and_full_digest_is_retained(review_link, service, store, alice):
    from radhouse.domain.releases import digest
    _, done, configured, state, link = review_link
    full = "Synthetic research result. " * 100
    with store.transaction() as tx:
        changed = replace(done, result=full, result_digest=digest(full), state_revision=done.state_revision + 1)
        tx.save_task(changed, done.state_revision)
    assert configured.run("egress")["error_code"] is None
    completion = next(e for e in state["published"].values() if ["radhouse-review", done.task_id] in e["tags"])
    assert completion["content"].startswith(full[:1200] + "\n\n[Preview")
    assert full not in completion["content"]
    target = service.review_links.resolve(alice, completion["content"].split("#review=")[1])
    with store.transaction() as tx:
        assert tx.task(target["task_id"]).result == full
