import base64
from dataclasses import replace
import json

from coincurve import PrivateKey
import httpx
import pytest

from radhouse.channels.buzz_conversations import BuzzConversationCycle
from radhouse.channels.buzz_relay import BuzzRelay
from radhouse.channels.nostr import nip98, sha256, verify_event
from radhouse.domain.conversations import ConversationLink
from tests.test_buzz_relay import signed
from tests.test_runtime_controls import receipt
from radhouse.domain.tasks import RuntimeResult

pytestmark = pytest.mark.postgres


@pytest.fixture
def bridge(service, store, clock):
    agent, owner, authority = PrivateKey(), PrivateKey(), PrivateKey()
    pk = lambda key: key.public_key_xonly.format().hex()
    now = int(clock().timestamp())
    link = ConversationLink(
        "researcher",
        "76d35b0c-0710-4aa2-83f2-11bd925913b1",
        "personal-alice:alice:buzz",
        "alice",
        pk(owner),
        pk(agent),
        "bot-alpha",
        "personal-alice",
        now,
    )
    state = {
        "messages": [],
        "published": {},
        "lost_ack": False,
        "files": {},
        "reads": 0,
        "publish_attempts": [],
    }

    def receive(request):
        if request.method == "GET":
            encoded = request.headers["Authorization"].removeprefix("Nostr ")
            auth = verify_event(
                json.loads(
                    base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
                ),
                24242,
            )
            digest = request.url.path.split("/")[-1].split(".")[0]
            assert auth["pubkey"] == pk(agent) and ["x", digest] in auth["tags"]
            state["reads"] += 1
            return httpx.Response(
                200,
                content=state["files"][digest],
                headers={"content-type": "text/plain"},
            )
        auth, _ = nip98(
            request.headers["Authorization"],
            str(request.url),
            "POST",
            request.content,
            now,
        )
        assert auth["pubkey"] == pk(agent)
        body = json.loads(request.content)
        if request.url.path == "/events":
            event = verify_event(body, body["kind"])
            state["publish_attempts"].append(event)
            markers = {t[3]: t[1] for t in event["tags"]
                       if len(t) >= 4 and t[0] == "e" and t[3] in {"root", "reply"}}
            if "reply" in markers:
                parent = next(e for e in [*state["messages"], *state["published"].values()]
                              if e["id"] == markers["reply"])
                ancestry = {t[3]: t[1] for t in parent["tags"]
                            if len(t) >= 4 and t[0] == "e" and t[3] in {"root", "reply"}}
                expected_root = (ancestry.get("root", ancestry["reply"])
                                 if "reply" in ancestry else parent["id"])
                if markers.get("root", markers["reply"]) != expected_root:
                    return httpx.Response(400, json={"error": "invalid: root tag does not match thread ancestry"})
            state["published"][event["id"]] = event
            if state["lost_ack"]:
                state["lost_ack"] = False
                raise httpx.ReadError("lost response after commit")
            return httpx.Response(200, json={"accepted": True, "event_id": event["id"]})
        query = body[0]
        if query["kinds"] == [30177]:
            return httpx.Response(200, json=state.get("directory", []))
        if query["kinds"] == [39000, 39002]:
            return httpx.Response(
                200,
                json=[
                    signed(
                        authority,
                        39000,
                        [["d", link.channel_id], ["private"], ["t", "dm"]],
                        now=now,
                    ),
                    signed(
                        authority,
                        39002,
                        [
                            ["d", link.channel_id],
                            ["p", pk(owner), "", "member"],
                            ["p", pk(agent), "", "member"],
                        ],
                        now=now,
                    ),
                ],
            )
        events = [e for e in state["messages"] if e["created_at"] >= query["since"]]
        if "until" in query:
            events = [
                e
                for e in events
                if e["created_at"] < query["until"]
                or (e["created_at"] == query["until"] and e["id"] > query["before_id"])
            ]
        return httpx.Response(
            200,
            json=sorted(events, key=lambda e: (-e["created_at"], e["id"]))[
                : query["limit"]
            ],
        )

    relay = BuzzRelay(
        "https://relay.test",
        pk(authority),
        agent.secret.hex(),
        transport=httpx.MockTransport(receive),
        clock=lambda: now,
    )
    with store.transaction() as tx:
        tx._connection.execute(
            "UPDATE channel_bindings SET subject=%s WHERE subject='alice@buzz'",
            (pk(owner),),
        )
        tx.save_conversation_link(link)
    yield BuzzConversationCycle(service, relay, link), state, owner
    relay.close()


def incoming(cycle, owner, text="Summarize the reference.", tags=(), offset=0):
    return signed(
        owner,
        9,
        [["h", cycle.link.channel_id], *tags],
        text,
        cycle.link.activated_at + offset,
    )


@pytest.mark.parametrize("initial", ["accepted", "too_late"])
def test_guidance_outcome_is_one_native_message_across_poll_and_reconnect(
    bridge, service, store, fake_work, initial,
):
    cycle, state, owner = bridge
    state["messages"] = [incoming(cycle, owner)]
    cycle.ingress()
    with store.transaction() as tx:
        task_id = tx.tasks()[0].task_id
    fake_work.result = lambda *_: RuntimeResult("running", guidance_receipts=())
    service.run(task_id)
    cycle.egress()
    values = []
    fake_work.steer = lambda task, run, text, control_id: values.append(receipt(run, control_id, text, initial)) or values[-1]
    state["messages"].append(incoming(cycle, owner, "Focus on costs.", offset=1))
    cycle.ingress()
    assert len(values) == 1
    value = (replace(values[0], state="applied", revision=2, checkpoint_id="checkpoint-1", api_request_id="request-2")
             if initial == "accepted" else values[0])
    fake_work.result = lambda *_: RuntimeResult("completed", "Synthetic final result", guidance_receipts=(value,))
    done = service.recover(task_id)
    for _ in range(3):
        cycle = BuzzConversationCycle(service, cycle.relay, cycle.link)
        assert cycle.run("egress")["error_code"] is None
    with store.transaction() as tx:
        history = [row["message"] for row in tx.conversation_history(cycle.link.link_id)]
        outcomes = [m for m in history if m.message_id.startswith("guidance:")]
        assert len(outcomes) == 1
        assert outcomes[0].task_id == task_id
        assert outcomes[0].reply_to == state["messages"][1]["id"]
        assert ("completed model response" if initial == "accepted" else "no longer accepting guidance") in outcomes[0].content
        assert len([m for m in history if m.state == "result"]) == 1
        assert tx.task(task_id).result_digest == done.result_digest
    outcome_event = next(e for e in state["published"].values() if ["radhouse-mirror", outcomes[0].message_id] in e["tags"])
    assert ["e", state["messages"][1]["id"], "", "reply"] in outcome_event["tags"]
    assert len(values) == 1 and fake_work.start_count == 1


def test_transport_lost_ack_and_restart_reuse_task_and_signed_reply(
    bridge, service, store
):
    cycle, state, owner = bridge
    state["messages"] = [incoming(cycle, owner)]
    assert cycle.run("ingress")["error_code"] is None
    state["lost_ack"] = True
    assert cycle.run("egress")["error_code"] == "buzz_relay_unavailable"
    first_id = next(iter(state["published"]))
    restarted = BuzzConversationCycle(service, cycle.relay, cycle.link)
    assert restarted.run("ingress")["error_code"] is None
    assert restarted.run("egress")["error_code"] is None
    with store.transaction() as tx:
        tasks = tx.tasks()
        assert len(tasks) == 1 and not tx.conversation_outgoing(cycle.link.link_id)
    assert first_id in state["published"]
    service.run(tasks[0].task_id)
    assert restarted.run("egress")["error_code"] is None
    results = [
        e
        for e in state["published"].values()
        if ["radhouse-review", tasks[0].task_id] in e["tags"]
    ]
    assert len(results) == 1
    assert ["e", state["messages"][0]["id"], "", "reply"] in results[0]["tags"]
    assert restarted.run("egress")["count"] == 0


def test_retained_rejected_reply_does_not_block_new_delivery_or_retry_on_restart(
    bridge, service, store, fake_work,
):
    cycle, state, owner = bridge
    original = incoming(cycle, owner)
    state["messages"] = [original]
    cycle.ingress()
    with store.transaction() as tx:
        first = tx.tasks()[0]
    service.run(first.task_id)
    cycle.egress()
    followup = incoming(cycle, owner, "Adapt the result.",
                        tags=[["e", original["id"], "", "reply"]], offset=1)
    state["messages"].append(followup)
    cycle.ingress()
    cycle._task_messages()
    # Reproduce an immutable signed event retained from the old adapter.
    with store.transaction() as tx:
        message = tx.conversation_message("reply:" + followup["id"])["message"]
        bad = cycle.relay.event(9, message.content, [
            ["h", cycle.link.channel_id],
            ["e", followup["id"], "", "root"],
            ["e", followup["id"], "", "reply"],
        ])
        tx.conversation_enqueue(message.message_id, cycle.link.link_id, message.message_id, bad)
        second = next(t for t in tx.tasks() if t.task_id != first.task_id)
    assert cycle.run("egress")["error_code"] is None
    assert bad["id"] not in state["published"]
    service.run(second.task_id)
    restarted = BuzzConversationCycle(service, cycle.relay, cycle.link)
    for _ in range(2):
        assert restarted.run("ingress")["error_code"] is None
        assert restarted.run("egress")["error_code"] is None
    with store.transaction() as tx:
        retained = tx._connection.execute(
            "SELECT * FROM conversation_outbox WHERE delivery_key=%s", (message.message_id,),
        ).fetchone()
        assert retained["event"] == bad and retained["delivered"] is False
        assert retained["error_code"] == "buzz_thread_ancestry_rejected"
        assert not tx.conversation_outgoing(cycle.link.link_id)
        assert len(tx.tasks()) == 2
    assert sum(e["id"] == bad["id"] for e in state["publish_attempts"]) == 1
    assert any(["radhouse-review", second.task_id] in e["tags"] for e in state["published"].values())
    assert fake_work.start_count == 2


@pytest.mark.parametrize("markers", [("reply",), ("root", "reply"), ("root",)])
def test_official_followup_thread_ancestry_survives_lost_ack_and_reconnect(
    bridge, service, store, fake_work, markers,
):
    cycle, state, owner = bridge
    original = incoming(cycle, owner)
    state["messages"] = [original]
    cycle.ingress()
    with store.transaction() as tx:
        first = tx.tasks()[0]
    completed = service.run(first.task_id)
    cycle.egress()
    followup = incoming(cycle, owner, "Adapt that completed result.",
                        tags=[["e", original["id"], "", marker] for marker in markers], offset=1)
    state["messages"].append(followup)
    cycle.ingress()
    with store.transaction() as tx:
        second = next(t for t in tx.tasks() if t.task_id != first.task_id)
        assert second.follows_task_id == first.task_id
        assert second.previous_result == completed.result
    state["lost_ack"] = True
    assert cycle.run("egress")["error_code"] == "buzz_relay_unavailable"
    published_before = dict(state["published"])
    restarted = BuzzConversationCycle(service, cycle.relay, cycle.link)
    restarted.ingress()
    assert restarted.run("egress")["error_code"] is None
    assert all(state["published"][key] == event for key, event in published_before.items())
    service.run(second.task_id)
    assert restarted.run("egress")["error_code"] is None
    expected_root = original["id"] if "reply" in markers else followup["id"]
    replies = [e for e in state["published"].values()
               if ["radhouse-task", second.task_id] in e["tags"]]
    assert replies and all(["e", expected_root, "", "root"] in e["tags"]
                           and ["e", followup["id"], "", "reply"] in e["tags"] for e in replies)
    with store.transaction() as tx:
        assert len(tx.tasks()) == 2
        assert not tx.conversation_outgoing(cycle.link.link_id)
    assert fake_work.start_count == 2
    assert restarted.run("egress")["count"] == 0


def test_reference_download_is_once_and_exact_bytes_reach_task(bridge, store):
    cycle, state, owner = bridge
    reference = b"Prefer walking and a quiet morning."
    digest = sha256(reference)
    state["files"][digest] = reference
    state["messages"] = [
        incoming(
            cycle,
            owner,
            tags=[
                [
                    "imeta",
                    f"url https://relay.test/media/{digest}.txt",
                    f"x {digest}",
                    "filename routine.txt",
                ]
            ],
        )
    ]
    for _ in range(2):
        assert cycle.run("ingress")["error_code"] is None
    with store.transaction() as tx:
        assert tx.tasks()[0].files[0].content.encode() == reference
    assert state["reads"] == 1


def test_official_client_screenshot_does_not_discard_written_brief(bridge, store):
    cycle, state, owner = bridge
    digest = "a" * 64
    state["messages"] = [
        incoming(
            cycle,
            owner,
            "Audit the group-management experience and improve it.",
            tags=[
                [
                    "imeta",
                    f"url https://relay.test/media/{digest}.png",
                    "m image/png",
                    f"x {digest}",
                    "size 1024",
                    "dim 1200x900",
                    "blurhash placeholder",
                    "thumb https://relay.test/media/thumb.png",
                    "filename current-preview.png",
                ]
            ],
        )
    ]
    assert cycle.run("ingress")["error_code"] is None
    with store.transaction() as tx:
        tasks = tx.tasks()
        assert len(tasks) == 1
        assert tasks[0].brief == "Audit the group-management experience and improve it."
        assert len(tasks[0].files) == 1
        assert "cannot inspect its pixels" in tasks[0].files[0].content
    assert state["reads"] == 0


@pytest.mark.parametrize(
    "url",
    [
        "https://elsewhere.test/media/" + "a" * 64,
        "https://relay.test/private",
        "https://relay.test/media/" + "a" * 64 + "?token=secret",
    ],
)
def test_bad_attachment_is_explained_without_blocking_later_message(bridge, store, url):
    cycle, state, owner = bridge
    bad = incoming(cycle, owner, tags=[["imeta", "url " + url]])
    good = incoming(cycle, owner, "Compare the options.", offset=1)
    state["messages"] = [bad, good]
    assert cycle.run("ingress")["error_code"] is None
    with store.transaction() as tx:
        assert len(tx.tasks()) == 1
        assert tx.conversation_message(bad["id"])["message"].state.startswith(
            "rejected:"
        )
        assert tx.conversation_message(good["id"])["message"].task_id is not None
    assert state["reads"] == 0


def test_grant_revocation_blocks_saved_outbox(bridge, store):
    cycle, state, owner = bridge
    state["messages"] = [incoming(cycle, owner)]
    cycle.ingress()
    cycle._prepare_outbox()
    with store.transaction() as tx:
        tx._connection.execute("DELETE FROM bot_grants WHERE principal_id='alice'")
    assert cycle.run("egress")["error_code"] is not None
    assert state["published"] == {}


def test_archive_scan_recovers_event_older_than_poll_overlap(bridge, store):
    cycle, state, owner = bridge
    with store.transaction() as tx:
        tx.conversation_progress(
            cycle.link.link_id, cursor=cycle.link.activated_at + 1000
        )
    state["messages"] = [incoming(cycle, owner)]
    assert cycle.run("ingress")["error_code"] is None
    with store.transaction() as tx:
        assert len(tx.tasks()) == 1


@pytest.mark.parametrize("source", ["buzz", "radhouse"])
def test_guidance_outcome_waits_for_exact_parent_during_processing_race(bridge, service, store, fake_work, monkeypatch, source):
    from radhouse.application.conversations import Conversations
    from radhouse.domain.conversations import ConversationMessage
    cycle, state, owner = bridge
    state["messages"] = [incoming(cycle, owner)]
    cycle.ingress()
    with store.transaction() as tx:
        task_id = tx.tasks()[0].task_id
    fake_work.result = lambda *_: RuntimeResult("running", guidance_receipts=())
    service.run(task_id)
    cycle.egress()
    posted = []
    fake_work.steer = lambda task, run, text, control_id: posted.append(control_id) or receipt(run, control_id, text, "too_late")
    event = incoming(cycle, owner, "Focus on costs.", offset=1)
    message = ConversationMessage(event["id"], cycle.link.link_id, cycle.link.principal_id,
        event["content"], source, event["created_at"])
    app = Conversations(service)
    if source == "buzz":
        state["messages"].append(event)
    app.receive(cycle.link, message, event=event if source == "buzz" else None)
    original = service.guide

    def race(*args, **kwargs):
        result = original(*args, **kwargs)
        cycle.egress()  # Source route exists, but source processing is unfinished.
        with store.transaction() as tx:
            pending = tx.conversation_message(message.message_id)
            assert not pending["processed"] and pending["message"].task_id is None
            outcomes = [r["message"] for r in tx.conversation_history(cycle.link.link_id) if r["message"].state == "guidance"]
            assert len(outcomes) == 1 and outcomes[0].reply_to == message.message_id
            if source == "radhouse": assert tx.conversation_event(outcomes[0].message_id) is None
        return result

    monkeypatch.setattr(service, "guide", race)
    app.process(cycle.link, message.message_id)
    for _ in range(2): assert cycle.run("egress")["error_code"] is None
    with store.transaction() as tx:
        outcomes = [r["message"] for r in tx.conversation_history(cycle.link.link_id) if r["message"].message_id.startswith("guidance:")]
        assert len(outcomes) == 1
        child = tx.conversation_event(outcomes[0].message_id)
        parent = event if source == "buzz" else tx.conversation_event(message.message_id)
        assert ["e", parent["id"], "", "reply"] in child["tags"]
        assert tx.conversation_outgoing(cycle.link.link_id) == []
    assert len(posted) == 1 and fake_work.start_count == 1
