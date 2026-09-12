"""API boundaries run without a database; end-to-end approvals use PostgreSQL."""
from dataclasses import asdict, replace
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi.testclient import TestClient
import pytest

from radhouse.api.app import create_app
from radhouse.channels.commands import Envelope
from radhouse.channels.mapping import verify_envelope
from radhouse.domain.access import AuthContext, Binding
from radhouse.domain.tasks import Rejected, StartTask, Task
from tests.fakes import SimulatedChannelDriver, channel_actor


def _identity():
    return AuthContext("alice", "radhouse", "alice@radhouse", datetime(2026, 9, 10, 13, tzinfo=timezone.utc))


def _envelope():
    return Envelope("radhouse", "event-one", "personal-alice:alice:radhouse", 1, "command-one")


def _start():
    return StartTask("bot-alpha", "personal-alice", "A synthetic report", "provider-synthetic")


class BoundaryService:
    """Call recorder for HTTP boundary tests, never a substitute task store."""
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def admit(self, actor, envelope, start):
        self.calls.append(("admit", actor, envelope, start))
        if self.error:
            raise self.error
        return Task("task-one", actor.principal_id, start.bot_id, start.project_id,
                    start.brief, start.provider_binding, start.resource_key, start.budget)

    def get(self, actor, task_id, *, envelope):
        self.calls.append(("get", actor, task_id, envelope))
        return Task(task_id, actor.principal_id, "bot-alpha", "personal-alice", "report", "synthetic", None, 3)


@pytest.mark.parametrize("adapter", [None, False, "fixture-auth"])
def test_factory_requires_explicit_callable_authentication(adapter):
    with pytest.raises(TypeError):
        create_app(BoundaryService(), adapter)
    with pytest.raises(TypeError):
        create_app(BoundaryService())


def test_invalid_authentication_result_fails_closed():
    service = BoundaryService()
    with TestClient(create_app(service, lambda request: {"principal_id": "alice"})) as client:
        response = client.post("/tasks", json={"envelope": asdict(_envelope()), "start": asdict(_start())})
    assert response.status_code == 401
    assert response.json() == {"code": "authentication_required"}
    assert not service.calls


@pytest.mark.parametrize("level,key,value", [
    ("root", "actor", "admin"),
    ("root", "role", "admin"),
    ("root", "assurance_until", "2099-01-01T00:00:00Z"),
    ("envelope", "principal_id", "admin"),
    ("envelope", "subject", "admin@radhouse"),
    ("start", "role", "admin"),
])
def test_raw_payload_cannot_assert_actor_role_or_assurance(level, key, value):
    service = BoundaryService()
    body = {"envelope": asdict(_envelope()), "start": asdict(_start())}
    (body if level == "root" else body[level])[key] = value
    with TestClient(create_app(service, lambda request: _identity())) as client:
        response = client.post("/tasks", json=body)
    assert response.status_code == 422
    assert response.json() == {"code": "invalid_request"}
    assert value not in response.text
    assert not service.calls


@pytest.mark.parametrize("part,key,value", [
    ("start", "budget", True), ("start", "budget", "3"),
    ("start", "budget", 0), ("start", "brief", ""),
    ("envelope", "binding_revision", "1"),
    ("envelope", "binding_revision", True),
    ("envelope", "mirrored", "false"),
])
def test_request_values_are_strict_and_bounded(part, key, value):
    service = BoundaryService()
    body = {"envelope": asdict(_envelope()), "start": asdict(_start())}
    body[part][key] = value
    with TestClient(create_app(service, lambda request: _identity())) as client:
        response = client.post("/tasks", json=body)
    assert response.status_code == 422
    assert not service.calls


def test_api_passes_only_injected_identity_and_typed_command():
    actor, envelope, start = _identity(), _envelope(), _start()
    service = BoundaryService()
    seen_requests = []

    def authenticate(request):
        seen_requests.append(request.url.path)
        return actor

    with TestClient(create_app(service, authenticate)) as client:
        response = client.post("/tasks", json={"envelope": asdict(envelope), "start": asdict(start)})
    assert response.status_code == 200
    assert response.json()["owner_id"] == "alice"
    assert seen_requests == ["/tasks"]
    assert service.calls == [("admit", actor, envelope, start)]


def test_reads_require_bound_conversation_context():
    service = BoundaryService()
    actor, envelope = _identity(), _envelope()
    with TestClient(create_app(service, lambda request: actor)) as client:
        assert client.get("/tasks/task-one").status_code == 422
        assert not service.calls
        response = client.get("/tasks/task-one", params={
            "conversation_id": envelope.conversation_id, "binding_revision": 1})
    assert response.status_code == 200
    read_context = Envelope(actor.channel, "read", envelope.conversation_id, 1, "read")
    assert service.calls == [("get", actor, "task-one", read_context)]


def test_errors_expose_only_bounded_public_code():
    service = BoundaryService(Rejected("binding_denied", 403))
    with TestClient(create_app(service, lambda request: _identity())) as client:
        response = client.post("/tasks", json={"envelope": asdict(_envelope()), "start": asdict(_start())})
    assert response.status_code == 403
    assert response.json() == {"code": "binding_denied"}


def test_internal_worker_controls_have_no_operator_route():
    routes = create_app(BoundaryService(), lambda request: _identity()).openapi()["paths"]
    assert set(routes) == {
        "/tasks", "/tasks/{task_id}", "/tasks/{task_id}/cancel", "/tasks/{task_id}/pause",
        "/tasks/{task_id}/resume", "/tasks/{task_id}/review", "/reviews/{review_id}/publish",
        "/tasks/{task_id}/publication", "/tasks/{task_id}/events",
    }


@pytest.mark.parametrize("change", [
    {"channel": "buzz"}, {"subject": "bob@radhouse"}, {"principal_id": "bob"},
    {"conversation_id": "other-conversation"}, {"project_id": "project-shared"},
    {"revision": 2}, {"active": False},
])
def test_mapping_rejects_every_mismatched_current_binding_dimension(change):
    actor, envelope = _identity(), _envelope()
    binding = Binding(actor.channel, actor.subject, envelope.conversation_id, actor.principal_id, "personal-alice", 1)
    with pytest.raises(Rejected, match="binding_denied"):
        verify_envelope(actor, envelope, replace(binding, **change), "personal-alice")


def test_mapping_requires_binding_and_rejects_mirrors_and_forged_channel():
    actor, envelope = _identity(), _envelope()
    binding = Binding(actor.channel, actor.subject, envelope.conversation_id, actor.principal_id, "personal-alice", 1)
    verify_envelope(actor, envelope, binding, "personal-alice")
    with pytest.raises(Rejected, match="binding_denied"):
        verify_envelope(actor, envelope, None, "personal-alice")
    with pytest.raises(Rejected, match="binding_denied"):
        verify_envelope(actor, replace(envelope, channel="buzz"), binding, "personal-alice")
    with pytest.raises(Rejected, match="mirrored_event"):
        verify_envelope(actor, replace(envelope, mirrored=True), binding, "personal-alice")


@contextmanager
def _driver(service, actor, channel="radhouse"):
    verified_actor = channel_actor(actor, channel)
    with TestClient(create_app(service, lambda request: verified_actor)) as client:
        yield SimulatedChannelDriver(client, channel)


def _query(envelope):
    return {"conversation_id": envelope.conversation_id, "binding_revision": envelope.binding_revision}


def _completed(service, actor, envelope, start):
    task = service.admit(actor, envelope, start)
    task = service.run(task.task_id, "approval-worker")
    assert task.outcome == "completed"
    return task


@pytest.mark.postgres
@pytest.mark.parametrize("first,second", [("radhouse", "buzz"), ("buzz", "radhouse")])
def test_two_channel_reverse_review_and_duplicate_publication(
    service, alice, envelope, start, fake_operations, first, second,
):
    source, destination = envelope(first), envelope(second)
    with _driver(service, alice, first) as originating, _driver(service, alice, second) as reviewing:
        admitted = originating.admit(source, start)
        assert admitted.status_code == 200, admitted.text
        task_id = admitted.json()["task_id"]
        assert originating.admit(source, start).json()["task_id"] == task_id
        completed = service.run(task_id, "approval-worker")
        viewed = reviewing.get(task_id, destination)
        assert viewed.status_code == 200, viewed.text
        assert viewed.json()["result"] == completed.result
        review_response = reviewing.review(task_id, destination,
            expected_state_revision=completed.state_revision, audience=["alice"])
        assert review_response.status_code == 200, review_response.text
        review = review_response.json()
        publication_envelope = envelope(second)
        publication = reviewing.publish(review["review_id"], publication_envelope,
            expected_revision=review["revision"], content=completed.result, audience=["alice"])
        assert publication.status_code == 200, publication.text
        duplicate = reviewing.publish(review["review_id"], publication_envelope,
            expected_revision=review["revision"], content=completed.result, audience=["alice"])
        assert duplicate.status_code == 200
        assert duplicate.json() == publication.json()
        cross_channel_duplicate = originating.publish(review["review_id"], envelope(first),
            expected_revision=review["revision"], content=completed.result, audience=["alice"])
        assert cross_channel_duplicate.status_code == 200
        assert cross_channel_duplicate.json() == publication.json()
        # The original surface observes the same publication and durable event stream.
        published_read = originating.client.get(f"/tasks/{task_id}/publication", params=_query(source))
        assert published_read.json() == publication.json()
        events = originating.client.get(f"/tasks/{task_id}/events", params=_query(source))
        assert events.status_code == 200
        assert events.json()["task"]["task_id"] == task_id
        assert sum(event["kind"] == "published" for event in events.json()["events"]) == 1
    assert fake_operations.effect_count == 1
    assert fake_operations.execute_count == 1


@pytest.mark.postgres
def test_publication_command_key_cannot_authorize_another_task(
    service, store, alice, envelope, start,
):
    source_one, source_two = envelope(), envelope()
    first = _completed(service, alice, source_one, start)
    second = _completed(service, alice, source_two, start)
    first_review = service.prepare_review(alice, first.task_id, first.state_revision,
        ("alice",), envelope=source_one)
    second_review = service.prepare_review(alice, second.task_id, second.state_revision,
        ("alice",), envelope=source_two)
    original = envelope(command_key="publish-one-command")
    reused = envelope("buzz", command_key="publish-one-command")
    assert original.event_id != reused.event_id
    with _driver(service, alice) as originating, _driver(service, alice, "buzz") as other_channel:
        accepted = originating.publish(first_review.review_id, original,
            expected_revision=first_review.revision, content=first.result, audience=["alice"])
        assert accepted.status_code == 200, accepted.text
        denied = other_channel.publish(second_review.review_id, reused,
            expected_revision=second_review.revision, content=second.result, audience=["alice"])
        assert denied.status_code == 409
        assert denied.json() == {"code": "command_conflict"}
    with store.transaction() as tx:
        assert tx.publication(first.task_id).publication_id == accepted.json()["publication_id"]
        assert tx.publication(second.task_id) is None
        assert tx.review(second_review.review_id) == second_review
        assert tx.command(alice.principal_id, original.command_key).task_id == first.task_id
        assert tx.delivery(reused.channel, reused.event_id) is None


@pytest.mark.postgres
@pytest.mark.parametrize("case,code", [
    ("viewer", "write_denied"), ("wrong_actor", "binding_denied"),
    ("stale_binding", "binding_denied"), ("mirror", "mirrored_event"),
    ("missing_grant", "access_denied"),
])
def test_denied_channel_admission_has_no_task_or_dispatch(
    service, store, alice, viewer, envelope, start, fake_runtime, fake_operations, case, code,
):
    actor = viewer if case == "viewer" else alice
    source = envelope(principal=actor.principal_id, project_id="project-shared")
    command = replace(start, project_id="project-shared")
    if case == "wrong_actor":
        actor = replace(actor, subject="bob@radhouse")
    elif case == "stale_binding":
        source = replace(source, binding_revision=2)
    elif case == "mirror":
        source = replace(source, mirrored=True)
    elif case == "missing_grant":
        command = replace(command, bot_id="bot-unallocated")
    # Keep the exact injected subject; the fixture driver normally changes it
    # when crossing channels, which would repair this deliberately bad binding.
    with TestClient(create_app(service, lambda request: actor)) as client:
        response = client.post("/tasks", json={"envelope": asdict(source), "start": asdict(command)})
    assert response.status_code in {403, 409}
    assert response.json() == {"code": code}
    with store.transaction() as tx:
        assert tx.tasks() == []
        assert tx.delivery(source.channel, source.event_id) is None
    assert fake_runtime.start_count == fake_operations.effect_count == 0


@pytest.mark.postgres
@pytest.mark.parametrize("case,code", [
    ("content", "review_scope_changed"), ("audience", "review_scope_changed"),
    ("revision", "review_conflict"), ("expiry", "review_expired"),
    ("assurance", "fresh_assurance_required"), ("mirror", "mirrored_event"),
    ("stale_binding", "binding_denied"), ("changed_task", "review_task_changed"),
])
def test_protected_review_denials_preserve_pending_decision(
    service, store, alice, envelope, start, clock, case, code,
):
    source = envelope(project_id="project-shared")
    task = _completed(service, alice, source, replace(start, project_id="project-shared"))
    review = service.prepare_review(alice, task.task_id, task.state_revision,
        ("alice",), envelope=source)
    actor, content, audience, revision = alice, task.result, ["alice"], review.revision
    delivery = envelope("buzz", project_id="project-shared")
    if case == "content":
        content += " altered"
    elif case == "audience":
        audience.append("viewer")
    elif case == "revision":
        revision += 1
    elif case == "expiry":
        clock.advance(seconds=301)
    elif case == "assurance":
        actor = replace(actor, assurance_until=clock())
    elif case == "mirror":
        delivery = replace(delivery, mirrored=True)
    elif case == "stale_binding":
        delivery = replace(delivery, binding_revision=2)
    elif case == "changed_task":
        with store.transaction() as tx:
            tx.save_task(task.evolve(), task.state_revision)
    with _driver(service, actor, "buzz") as driver:
        response = driver.publish(review.review_id, delivery,
            expected_revision=revision, content=content, audience=audience)
    assert response.status_code in {403, 409}
    assert response.json() == {"code": code}
    with store.transaction() as tx:
        assert tx.publication(task.task_id) is None
        assert tx.review(review.review_id) == review
        assert tx.delivery(delivery.channel, delivery.event_id) is None


@pytest.mark.postgres
@pytest.mark.parametrize("principal,bot,code", [("bob", "bot-beta", "private_task"), ("viewer", "bot-alpha", "write_denied")])
def test_eligible_other_principal_cannot_approve_owners_result(
    service, store, alice, bob, viewer, envelope, start, principal, bot, code,
):
    source = envelope(project_id="project-shared")
    task = _completed(service, alice, source, replace(start, bot_id=bot, project_id="project-shared"))
    review = service.prepare_review(alice, task.task_id, task.state_revision, ("alice",), envelope=source)
    actor = {"bob": bob, "viewer": viewer}[principal]
    delivery = envelope("buzz", principal=principal, project_id="project-shared")
    with _driver(service, actor, "buzz") as driver:
        response = driver.publish(review.review_id, delivery,
            expected_revision=review.revision, content=task.result, audience=["alice"])
    assert response.status_code == 403
    assert response.json() == {"code": code}
    with store.transaction() as tx:
        assert tx.publication(task.task_id) is None


@pytest.mark.postgres
def test_publication_audience_never_releases_private_task_history_and_revocation_applies(
    service, store, alice, viewer, envelope, start,
):
    source = envelope(project_id="project-shared")
    task = _completed(service, alice, source, replace(start, project_id="project-shared"))
    review = service.prepare_review(alice, task.task_id, task.state_revision,
        ("alice", "viewer"), envelope=source)
    service.publish(alice, envelope(project_id="project-shared"), review.review_id,
        review.revision, task.result, ("alice", "viewer"))
    viewer_context = envelope("buzz", principal="viewer", project_id="project-shared")
    with _driver(service, viewer, "buzz") as driver:
        read = driver.client.get(f"/tasks/{task.task_id}/publication", params=_query(viewer_context))
        assert read.status_code == 200
        assert read.json()["content"] == task.result
        assert driver.get(task.task_id, viewer_context).status_code == 403
        assert driver.client.get(f"/tasks/{task.task_id}/events", params=_query(viewer_context)).status_code == 403
        with store.transaction() as tx:
            tx._connection.execute("DELETE FROM project_members WHERE principal_id=%s AND project_id=%s", ("viewer", "project-shared"))
        denied = driver.client.get(f"/tasks/{task.task_id}/publication", params=_query(viewer_context))
        assert denied.status_code == 403
        assert task.result not in denied.text


@pytest.mark.postgres
def test_current_binding_checked_before_duplicate_publication_and_read_replay(
    service, store, alice, envelope, start,
):
    source = envelope()
    task = _completed(service, alice, source, start)
    review = service.prepare_review(alice, task.task_id, task.state_revision, ("alice",), envelope=source)
    delivery = envelope()
    service.publish(alice, delivery, review.review_id, review.revision, task.result, ("alice",))
    with store.transaction() as tx:
        tx._connection.execute("UPDATE channel_bindings SET revision=revision+1 WHERE principal_id=%s", ("alice",))
    with _driver(service, alice) as driver:
        for path in (f"/tasks/{task.task_id}", f"/tasks/{task.task_id}/events", f"/tasks/{task.task_id}/publication"):
            response = driver.client.get(path, params=_query(source))
            assert response.status_code == 403
            assert response.json() == {"code": "binding_denied"}
        repeated = driver.publish(review.review_id, delivery,
            expected_revision=review.revision, content=task.result, audience=["alice"])
        assert repeated.status_code == 403
        assert repeated.json() == {"code": "binding_denied"}
