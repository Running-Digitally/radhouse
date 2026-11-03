import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from radhouse.chat.commitment_review import CommitmentReview, validate_suggestions
from radhouse.chat.store import ChatStore
from radhouse.domain.tasks import Rejected


@pytest.fixture
def pilot(tmp_path):
    clock = [1000000.0]
    allowed = [True]
    chat = ChatStore(tmp_path / "chat.db")
    review = CommitmentReview(tmp_path / "review.db", chat, "owner", lambda *_: allowed[0], clock=lambda: clock[0])
    review.set_active("conversation", 1, True)
    return review, chat, clock, allowed


def message(chat, clock, text="I intend to send the draft tomorrow.", owner="owner"):
    identifier = str(uuid4())
    chat.reserve(owner, identifier, text, clock[0], ())
    return identifier


def suggestion(source, **extra):
    return json.dumps({"suggestions": [{"source_request_id": source, "quote": "send the draft",
        "title": "Prepare the draft", "reason": "You mentioned an intention that may need follow-up.",
        "preparation": "Check whether the draft is ready before deciding to send it.", **extra}]})


def test_review_publishes_only_cited_candidates_and_never_a_user_turn(pilot):
    review, chat, clock, _ = pilot
    source = message(chat, clock)
    claim = review.claim()
    assert claim["status"] == "claimed"
    assert review.complete(claim["review_id"], suggestion(source)) == {"status": "ready"}
    with chat.connection() as db:
        assert db.execute("SELECT count(*) FROM turns").fetchone()[0] == 1
    candidate = review.status()["suggestions"][0]
    assert candidate["state"] == "suggested"
    assert candidate["source_request_id"] == source
    assert review.claim() == {"status": "unchanged"}
    assert review.decide(candidate["id"], "confirmed") == {"status": "confirmed"}


def test_restart_and_duplicate_completion_do_not_repeat_suggestions(pilot):
    review, chat, clock, _ = pilot
    source = message(chat, clock)
    claim = review.claim()
    review.complete(claim["review_id"], suggestion(source))
    restarted = CommitmentReview(review.path, chat, "owner", lambda *_: True, clock=lambda: clock[0])
    assert restarted.complete(claim["review_id"], suggestion(source)) == {"status": "ready"}
    assert len(restarted.status()["suggestions"]) == 1
    assert restarted.claim() == {"status": "unchanged"}


@pytest.mark.parametrize("change", ["pause", "revoke", "correction", "expire"])
def test_publication_rechecks_authority_and_new_evidence(pilot, change):
    review, chat, clock, allowed = pilot
    source = message(chat, clock)
    claim = review.claim()
    if change == "pause":
        review.set_active("conversation", 1, False)
    elif change == "revoke":
        allowed[0] = False
    elif change == "correction":
        message(chat, clock, "That draft is cancelled. Do not follow up.")
    else:
        clock[0] += 601
    if change == "correction":
        assert review.complete(claim["review_id"], suggestion(source)) == {"status": "stale"}
    else:
        with pytest.raises(Rejected):
            review.complete(claim["review_id"], suggestion(source))
    assert review.status()["suggestions"] == []


def test_quiet_success_is_distinct_from_failure_and_interruption(pilot):
    review, chat, clock, _ = pilot
    message(chat, clock)
    first = review.claim()
    assert review.complete(first["review_id"], '{"suggestions":[]}') == {"status": "quiet"}
    message(chat, clock, "A different intention.")
    second = review.claim()
    assert review.complete(second["review_id"], "", failed=True) == {"status": "failed"}
    assert review.status()["last_review"]["error"] == "runtime_review_failed"
    third = review.claim()
    assert third["status"] == "claimed"
    clock[0] += 601
    review.claim()
    with review.connection() as db:
        assert db.execute("SELECT state FROM reviews WHERE id=?", (third["review_id"],)).fetchone()[0] == "interrupted"


def test_scope_excludes_other_owner_old_text_and_attachment_context(pilot):
    review, chat, clock, _ = pilot
    message(chat, [clock[0] - 8 * 86400], "old secret")
    message(chat, clock, "other owner secret", owner="someone-else")
    source = message(chat, clock)
    with chat.connection() as db:
        db.execute("UPDATE turns SET input_text='PRIVATE ATTACHMENT CONTENT' WHERE request_id=?", (source,))
    prompt = review.claim()["prompt"]
    assert "old secret" not in prompt
    assert "other owner secret" not in prompt
    assert "PRIVATE ATTACHMENT CONTENT" not in prompt
    assert "send the draft" in prompt


@pytest.mark.parametrize("extra", [{"tool": "send_email"}, {"quote": "invented evidence"}, {"source_request_id": "foreign"}])
def test_model_cannot_expand_authority_or_fabricate_a_citation(pilot, extra):
    review, chat, clock, _ = pilot
    source = message(chat, clock)
    snapshot = {"exchanges": [{"request_id": source, "text": "send the draft"}]}
    with pytest.raises(Rejected, match="invalid_commitment_evidence"):
        validate_suggestions(suggestion(source, **extra), snapshot)


def test_dismissal_is_durable_and_same_source_cannot_realert(pilot):
    review, chat, clock, _ = pilot
    source = message(chat, clock)
    claim = review.claim()
    review.complete(claim["review_id"], suggestion(source))
    candidate = review.status()["suggestions"][0]
    review.decide(candidate["id"], "dismissed")
    message(chat, clock, "Here is an unrelated update.")
    next_claim = review.claim()
    assert 'dismissed' in next_claim["prompt"]
    assert review.complete(next_claim["review_id"], suggestion(source)) == {"status": "quiet"}
    assert len(review.status()["suggestions"]) == 1


def test_review_budget_and_single_inflight_claim(pilot):
    review, chat, clock, _ = pilot
    message(chat, clock)
    first = review.claim()
    assert review.claim() == {"status": "running"}
    review.complete(first["review_id"], "", failed=True)
    for _ in range(3):
        claim = review.claim()
        review.complete(claim["review_id"], "", failed=True)
    assert review.claim() == {"status": "budget_wait"}


@pytest.fixture
def worker():
    path = Path(__file__).resolve().parents[1] / "runtime/hermes/commitment_worker.py"
    spec = importlib.util.spec_from_file_location("commitment_worker_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_relays_success_without_native_platform_message(worker):
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("claim"):
            return httpx.Response(200, json={"status": "claimed", "review_id": "synthetic", "prompt": "bounded evidence"})
        assert json.loads(request.content)["output"] == '{"suggestions":[]}'
        return httpx.Response(200, json={"status": "quiet"})
    config = {"endpoint": "https://fixture.test", "worker_bearer": "synthetic"}
    result = worker.run_once(config, infer=lambda *_: '{"suggestions":[]}', transport=httpx.MockTransport(handler))
    assert result == "quiet"
    assert len(requests) == 2


@pytest.mark.parametrize("status", ["unchanged", "running", "budget_wait"])
def test_worker_cheap_gate_never_calls_model(worker, status):
    def never(*_):
        pytest.fail("model must not run")
    config = {"endpoint": "https://fixture.test", "worker_bearer": "synthetic"}
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"status": status}))
    assert worker.run_once(config, infer=never, transport=transport) == status


def test_worker_records_failure_without_leaking_exception(worker):
    bodies = []
    def handler(request):
        if request.url.path.endswith("claim"):
            return httpx.Response(200, json={"status": "claimed", "review_id": "synthetic", "prompt": "bounded"})
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "failed"})
    def fail(*_):
        raise RuntimeError("private provider diagnostic")
    config = {"endpoint": "https://fixture.test", "worker_bearer": "synthetic"}
    with pytest.raises(ValueError, match="review_failed"):
        worker.run_once(config, infer=fail, transport=httpx.MockTransport(handler))
    assert bodies == [{"review_id": "synthetic", "output": "", "failed": True}]


def test_invalid_model_output_is_recorded_as_failure(pilot):
    review, chat, clock, _ = pilot
    source = message(chat, clock)
    claim = review.claim()
    assert review.complete(claim["review_id"], suggestion(source, recipient="someone else")) == {"status": "failed"}
    assert review.status()["last_review"]["error"] == "invalid_commitment_evidence"
    assert review.status()["suggestions"] == []


def test_pending_notification_cannot_survive_pause_and_resume(pilot):
    review, chat, clock, _ = pilot
    source = message(chat, clock)
    claim = review.claim()
    review.complete(claim["review_id"], suggestion(source))
    item = review.notification_items()[0]
    assert review.notification_decision(item["id"]) == "allow"
    review.set_active("conversation", 1, False)
    review.set_active("conversation", 1, True)
    assert review.notification_items() == []
    assert review.notification_decision(item["id"]) == "discard"


@pytest.fixture
def web_pilot(pilot):
    from datetime import datetime, timezone
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient
    from radhouse.auth.local import LocalSession
    from radhouse.chat.commitment_routes import install_commitment_review
    from radhouse.chat.worker_control import DispatchGate
    review, chat, clock, _ = pilot
    current = LocalSession("synthetic-session", "synthetic-csrf", "owner", "owner",
        datetime.fromtimestamp(clock[0], timezone.utc), "conversation", 1, "project",
        datetime.fromtimestamp(clock[0]+86400, timezone.utc))
    def authenticate(request):
        if request.headers.get("authorization") != "synthetic-session":
            raise Rejected("authentication_required", 401)
        if request.method == "POST" and request.headers.get("x-radhouse-csrf") != "synthetic-csrf":
            raise Rejected("csrf_denied", 403)
        return current
    app = FastAPI()
    @app.exception_handler(Rejected)
    async def rejected(_request, error):
        return JSONResponse({"error": error.code}, status_code=error.status)
    service = SimpleNamespace(store=chat, owner_id="owner", authorize=lambda _: "owner", dispatch_gate=DispatchGate())
    auth = SimpleNamespace(session=authenticate)
    bearer = "w" * 43
    install_commitment_review(app, auth, service, review, bearer)
    with TestClient(app) as client:
        yield client, {"authorization":"synthetic-session", "x-radhouse-csrf":"synthetic-csrf"}, bearer, service


def test_owner_controls_require_auth_and_csrf_worker_is_separate(web_pilot):
    client, headers, bearer, _ = web_pilot
    route = "/chat/responsibilities/commitments"
    assert client.get(route).status_code == 401
    assert client.post(route, headers={"authorization":"synthetic-session"}, json={"active":False}).status_code == 403
    assert client.post(route, headers=headers, json={"active":False}).status_code == 200
    assert client.post("/internal/commitment-review/claim", headers=headers).status_code == 403
    result = client.post("/internal/commitment-review/claim", headers={"authorization":"Bearer "+bearer})
    assert result.json() == {"error":"responsibility_paused"}
    assert client.get(route, headers={"authorization":"Bearer "+bearer}).status_code == 401


def test_native_worker_to_real_routes_persists_cited_result(web_pilot, pilot, worker):
    client, headers, bearer, _ = web_pilot
    review, chat, clock, _ = pilot
    source = message(chat, clock)
    def transport(request):
        result = client.request(request.method, request.url.path, content=request.content,
                                headers={"authorization":request.headers["authorization"], "content-type":"application/json"})
        return httpx.Response(result.status_code, json=result.json())
    config = {"endpoint":"https://fixture.test", "worker_bearer":bearer}
    result = worker.run_once(config, infer=lambda *_: suggestion(source), transport=httpx.MockTransport(transport))
    assert result == "ready"
    item = review.status()["suggestions"][0]
    response = client.get("/chat/responsibilities/commitments/"+item["id"], headers=headers)
    assert response.json()["item"]["quote"] == "send the draft"
    assert client.get("/chat/responsibilities/commitments/"+str(uuid4()), headers=headers).status_code == 404
    assert client.post("/chat/responsibilities/commitments/"+item["id"], headers=headers, json={"decision":"confirmed"}).status_code == 200


def test_worker_cannot_publish_extra_authority_or_oversized_request(web_pilot):
    client, _, bearer, _ = web_pilot
    headers = {"authorization":"Bearer "+bearer}
    path = "/internal/commitment-review/complete"
    assert client.post(path, headers=headers, json={"review_id":"id", "output":"", "failed":False, "owner":"foreign"}).status_code == 422
    assert client.post(path, headers=headers, content=b"x" * 16001).status_code == 413


def test_push_is_opt_in_private_quiet_hours_and_revocable(pilot, tmp_path):
    from cryptography.fernet import Fernet
    from radhouse.chat.push import PushBinding, PushOutbox, PushResult
    from radhouse.chat.push_fcm import _payload
    review, chat, clock, _ = pilot
    outbox = PushOutbox(tmp_path / "push.db", Fernet.generate_key().decode(), clock=lambda:clock[0])
    binding = PushBinding("owner", "conversation", 1, "a" * 64, clock[0]+86400)
    installation = str(uuid4())
    outbox.register(installation, binding, "ios", "synthetic-token-123456789", latest_seq=0)
    source = message(chat, clock)
    claim = review.claim()
    review.complete(claim["review_id"], suggestion(source))
    items = review.notification_items()
    outbox.enqueue_commitments("owner", items)
    assert not outbox.dispatch_one(lambda _:True, lambda *_:pytest.fail("not opted in"))
    outbox.register(installation, binding, "ios", "synthetic-token-123456789", latest_seq=0, commitments=True)
    outbox.enqueue_commitments("owner", items)
    sent=[]
    def send(token, platform, data):
        sent.append(_payload(token, platform, data)["message"])
        return PushResult("sent")
    assert outbox.dispatch_one(lambda _:True, send, commitment_decision=lambda _:"hold")
    assert sent == []
    clock[0]+=61
    assert outbox.dispatch_one(lambda _:True, send, commitment_decision=review.notification_decision)
    assert sent[0]["data"]["kind"] == "commitment_ready"
    assert sent[0]["data"]["item_id"] == items[0]["id"]
    assert "send the draft" not in json.dumps(sent)
    assert not outbox.dispatch_one(lambda _:True, send, commitment_decision=review.notification_decision)


def test_push_never_replays_pre_consent_items_and_caps_daily_attention(pilot, tmp_path):
    from cryptography.fernet import Fernet
    from radhouse.chat.push import PushBinding, PushOutbox
    _, _, clock, _ = pilot
    outbox=PushOutbox(tmp_path/"push.db", Fernet.generate_key().decode(), clock=lambda:clock[0])
    binding=PushBinding("owner","conversation",1,"b"*64,clock[0]+86400)
    outbox.register(str(uuid4()),binding,"android","synthetic-token-123456789",latest_seq=0,commitments=True)
    items=[{"id":str(uuid4()),"created_at":clock[0]-1}]+[{"id":str(uuid4()),"created_at":clock[0]} for _ in range(4)]
    outbox.enqueue_commitments("owner",items)
    with outbox.connection() as db:
        saved=db.execute("SELECT request_id FROM deliveries").fetchall()
    assert len(saved)==2
    assert items[0]["id"] not in {row[0] for row in saved}


def test_native_review_has_no_memory_context_tools_or_fallback(worker, monkeypatch):
    import sys
    from types import ModuleType
    received = {}
    closed = []
    agent = SimpleNamespace(tools=[], valid_tool_names=set(), _memory_store=None, _memory_manager=None,
        run_conversation=lambda _: {"final_response":'{"suggestions":[]}'}, close=lambda:closed.append(True))
    def create(**kwargs):
        received.update(kwargs)
        return agent
    native = ModuleType("run_agent")
    native.__file__ = "/synthetic/run_agent.py"
    native.AIAgent = create
    gateway = ModuleType("gateway.run")
    gateway._resolve_runtime_agent_kwargs_for_provider = lambda *_: {"provider":"synthetic", "api_mode":"chat_completions",
        "request_overrides":{"messages":["unscoped context"]}}
    monkeypatch.setitem(sys.modules,"run_agent",native)
    monkeypatch.setitem(sys.modules,"gateway.run",gateway)
    env_loader = ModuleType("hermes_cli.env_loader")
    env_loader.load_hermes_dotenv = lambda: None
    monkeypatch.setitem(sys.modules,"hermes_cli.env_loader",env_loader)
    monkeypatch.setattr(worker,"_guard_installed_runtime",lambda _:None)
    assert worker.native_review("bounded evidence",{"provider":"synthetic","model":"synthetic", "hermes_root":"/synthetic"}) == '{"suggestions":[]}'
    assert received["enabled_toolsets"] == []
    assert received["skip_memory"] is True
    assert received["skip_context_files"] is True
    assert received["load_soul_identity"] is False
    assert received["skip_background_review"] is True
    assert received["fallback_model"] is None
    assert "request_overrides" not in received
    assert agent._allowed_tool_names == frozenset()
    assert closed == [True]


def test_actual_quiet_hours_keep_pending_items_for_morning(pilot):
    from datetime import datetime, timezone
    review, chat, clock, _ = pilot
    clock[0] = datetime(2026, 11, 3, 23, tzinfo=timezone.utc).timestamp()
    source = message(chat, clock)
    claim = review.claim()
    review.complete(claim["review_id"], suggestion(source))
    item = review.notification_items()[0]
    assert review.notification_decision(item["id"]) == "hold"
    clock[0] += 9 * 3600
    assert review.notification_decision(item["id"]) == "allow"


def test_status_does_not_claim_active_after_binding_revocation(pilot):
    review, _, _, allowed = pilot
    assert review.status()["active"] is True
    allowed[0] = False
    assert review.status()["active"] is False


def test_new_conversation_suppresses_a_previously_queued_suggestion(pilot):
    review, chat, clock, _ = pilot
    source = message(chat, clock)
    claim = review.claim()
    review.complete(claim["review_id"], suggestion(source))
    item = review.notification_items()[0]
    assert review.notification_decision(item["id"]) == "allow"
    message(chat, clock, "Cancel that draft, I no longer plan to send it.")
    assert review.notification_decision(item["id"]) == "discard"
