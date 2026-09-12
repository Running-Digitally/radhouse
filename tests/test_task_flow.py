"""Offline task contracts; PostgreSQL cases run only in the owned fixture."""
from dataclasses import replace
from datetime import datetime
import pytest

from radhouse.domain.tasks import Attempt, Rejected, Task
from tests.fakes import FakeOperations, FakeRuntime, FixedClock, channel_actor


def test_effect_receipt_survives_adapter_recreation(tmp_path):
    task = Task("synthetic-task", "alice", "bot-alpha", "personal-alice", "report", "fake-local", None, 3)
    path = tmp_path / "effect.sqlite3"
    target = FakeOperations(path)
    confirmed = target.execute(task, "operation-key")
    restarted = FakeOperations(path)
    assert restarted.lookup("operation-key") == confirmed
    assert restarted.effect_count == restarted.execute_count == 1
    restarted.lookup("missing-key")
    assert restarted.effect_count == restarted.execute_count == 1


def test_missing_receipt_is_unknown_and_lookup_never_executes(tmp_path):
    task = Task("synthetic-task", "alice", "bot-alpha", "personal-alice", "report", "fake-local", None, 3)
    target = FakeOperations(tmp_path / "effect.sqlite3", mode="unknown_without_receipt")
    assert target.execute(task, "uncertain").state == "unknown"
    assert target.lookup("uncertain").state == "unknown"
    assert target.execute_count == 1
    assert target.effect_count == 0


def test_runtime_attach_and_stop_survive_adapter_recreation(tmp_path):
    task = Task("synthetic-task", "alice", "bot-alpha", "personal-alice", "report", "fake-local", None, 3)
    attempt = Attempt("attempt-1", task.task_id, 1, "worker")
    path = tmp_path / "runtime.sqlite3"
    FakeRuntime(path).start_or_attach(task, attempt, "dispatch-1")
    restarted = FakeRuntime(path)
    restarted.start_or_attach(task, attempt, "dispatch-1")
    assert restarted.start_count == restarted.attach_count == 1
    assert restarted.stop(attempt)
    FakeRuntime(path).start_or_attach(task, attempt, "dispatch-1")
    assert FakeRuntime(path).state(attempt.attempt_id) == "stopped"


def test_clock_rejects_ambiguous_naive_time():
    with pytest.raises(ValueError, match="aware UTC"):
        FixedClock(datetime(2026, 9, 10))


@pytest.mark.postgres
@pytest.mark.parametrize("source,destination", [("radhouse", "buzz"), ("buzz", "radhouse")])
def test_same_task_across_channels_and_duplicate_delivery(service, store, alice, envelope, start, source, destination):
    actor = channel_actor(alice, source)
    original = envelope(source, event_id="original", command_key="same-command")
    task = service.admit(actor, original, start)
    assert service.admit(actor, original, start).task_id == task.task_id
    peer = channel_actor(alice, destination)
    equivalent = envelope(destination, command_key="same-command")
    assert service.admit(peer, equivalent, start).task_id == task.task_id
    assert service.get(peer, task.task_id, envelope=envelope(destination)).task_id == task.task_id
    with store.transaction() as tx:
        assert len(tx.tasks()) == 1
    with pytest.raises(Rejected) as error:
        service.admit(actor, envelope(source, command_key="same-command"), replace(start, brief="different intent"))
    assert error.value.code == "command_conflict"


@pytest.mark.postgres
@pytest.mark.parametrize("principal", ["bob", "viewer", "admin"])
def test_no_implicit_private_content_access(service, alice, bob, viewer, admin, envelope, start, principal):
    task = service.admit(alice, envelope(), start)
    actor = {"bob": bob, "viewer": viewer, "admin": admin}[principal]
    with pytest.raises(Rejected) as error:
        service.get(actor, task.task_id, envelope=envelope(principal=principal))
    assert error.value.status == 403


@pytest.mark.postgres
@pytest.mark.parametrize("available,compatible,expected", [(False, True, "provider_unavailable"), (True, False, "provider_incompatible")])
def test_provider_recovery_preserves_human_pause(service, alice, envelope, start, fake_provider, available, compatible, expected):
    task = service.admit(alice, envelope(), start)
    task = service.pause(alice, task.task_id, task.state_revision, envelope=envelope())
    fake_provider.available, fake_provider.compatible = available, compatible
    waiting = service.claim(task.task_id, "worker")
    assert {"human_pause", expected} <= set(waiting.blockers)
    fake_provider.available = fake_provider.compatible = True
    fake_provider.model_id = "model-B"
    recovered = service.claim(task.task_id, "worker")
    assert recovered.blockers == ("human_pause",)
    assert recovered.model_id == "model-B"
    assert recovered.provider_binding == "fake-local"
    assert recovered.budget_remaining == start.budget
    assert recovered.attempt_id is None
    resumed = service.resume(alice, task.task_id, recovered.state_revision, envelope=envelope())
    claimed = service.claim(resumed.task_id, "worker")
    assert claimed.model_id == "model-B"
    assert claimed.budget_remaining == start.budget - 1


def test_harness_rejects_docker_environment_override_before_any_command(monkeypatch):
    from scripts.vs0 import FixtureError, Run
    monkeypatch.setenv("DOCKER_HOST", "tcp://unowned.invalid:2375")
    run = Run()
    def forbidden(*args, **kwargs):
        pytest.fail("Docker must not be contacted with endpoint overrides")
    monkeypatch.setattr(run, "command", forbidden)
    with pytest.raises(FixtureError, match="overrides"):
        run.preflight()


def test_harness_requires_disk_headroom_before_any_command(monkeypatch):
    from types import SimpleNamespace
    from scripts.vs0 import FixtureError, Run
    for key in list(__import__("os").environ):
        if key.startswith(("DOCKER_", "PG")):
            monkeypatch.delenv(key)
    monkeypatch.setattr("scripts.vs0.shutil.disk_usage", lambda path: SimpleNamespace(free=1024))
    run = Run()
    monkeypatch.setattr(run, "command", lambda *args, **kwargs: pytest.fail("must check capacity first"))
    with pytest.raises(FixtureError, match="2 GiB"):
        run.preflight()


def test_harness_rejects_remote_context_before_daemon_contact(monkeypatch):
    import json
    from types import SimpleNamespace
    from scripts.vs0 import FixtureError, Run
    for key in list(__import__("os").environ):
        if key.startswith(("DOCKER_", "PG")):
            monkeypatch.delenv(key)
    monkeypatch.setattr("scripts.vs0.shutil.disk_usage", lambda path: SimpleNamespace(free=4 * 1024**3))
    run = Run()
    seen = []
    def metadata(args, **kwargs):
        seen.append(args)
        return SimpleNamespace(stdout="remote" if args[-1] == "show" else json.dumps([
            {"Endpoints": {"docker": {"Host": "tcp://unowned.invalid:2375"}}}]))
    monkeypatch.setattr(run, "command", metadata)
    with pytest.raises(FixtureError, match="remote Docker"):
        run.preflight()
    assert len(seen) == 2
    assert all(args[1] == "context" for args in seen)


def test_cleanup_never_removes_resources_with_wrong_labels(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace
    from scripts.vs0 import Run
    run = Run()
    run.output = tmp_path
    run.manifest_path = tmp_path / "manifest.json"
    seen = []
    def foreign(*args, **kwargs):
        seen.append(args)
        if args[0] == "inspect":
            value = [{"Config": {"Labels": {}}}]
        elif args[:2] == ("volume", "inspect"):
            value = [{"Name": "unowned", "Labels": {}}]
        else:
            pytest.fail("unowned fixture resource must never be removed")
        return SimpleNamespace(returncode=0, stdout=json.dumps(value))
    monkeypatch.setattr(run, "docker", foreign)
    run.cleanup()
    assert run.manifest["cleanup"] == "residual resources"
    assert len(run.manifest["residual_resources"]) == 2
    assert all("rm" not in args for args in seen)


@pytest.mark.postgres
def test_restored_grant_does_not_silently_clear_withdrawal_hold(service, store, alice, envelope, start):
    task = service.admit(alice, envelope(), start)
    with store.transaction() as tx:
        tx._connection.execute("DELETE FROM public.bot_grants WHERE principal_id='alice' AND bot_id='bot-alpha'")
    held = service.claim(task.task_id, "worker")
    assert "grant_withdrawal" in held.blockers
    with store.transaction() as tx:
        tx._connection.execute("INSERT INTO public.bot_grants VALUES ('alice','bot-alpha')")
    still_held = service.claim(task.task_id, "worker")
    assert still_held.blockers == ("grant_withdrawal",)
    assert still_held.attempt_id is None
    assert still_held.budget_remaining == start.budget
    resumed = service.resume(alice, task.task_id, still_held.state_revision, envelope=envelope())
    assert "grant_withdrawal" not in resumed.blockers


@pytest.mark.postgres
def test_viewer_cannot_admit_even_in_granted_context(service, viewer, envelope, start):
    with pytest.raises(Rejected) as error:
        service.admit(viewer, envelope(principal="viewer", project_id="project-shared"), replace(start, project_id="project-shared"))
    assert error.value.code == "write_denied"


@pytest.mark.postgres
def test_same_project_and_bot_grants_do_not_expose_another_operators_history(service, alice, bob, envelope, start):
    task = service.admit(alice, envelope(project_id="project-shared"), replace(start, bot_id="bot-beta", project_id="project-shared"))
    with pytest.raises(Rejected) as error:
        service.get(bob, task.task_id, envelope=envelope(principal="bob", project_id="project-shared"))
    assert error.value.code == "private_task"


@pytest.mark.parametrize("case", ["preexisting", "label_mismatch"])
def test_volume_guard_refuses_reuse_or_wrong_ownership_before_container_creation(monkeypatch, tmp_path, case):
    import json
    from types import SimpleNamespace
    from scripts.vs0 import FixtureError, PINNED_IMAGE, Run
    run = Run()
    run.output, run.manifest_path = tmp_path, tmp_path / "manifest.json"
    run.manifest["image"] = PINNED_IMAGE
    seen = []
    def docker(*args, **kwargs):
        seen.append(args)
        if args[0] == "pull":
            output = ""
        elif args[:2] == ("image", "inspect"):
            output = json.dumps([{"Id": "synthetic-image", "RepoDigests": [PINNED_IMAGE]}])
        elif args[:2] == ("volume", "ls"):
            output = run.manifest["volume_name"] if case == "preexisting" else ""
        elif args[:2] == ("volume", "create"):
            output = run.manifest["volume_name"]
        elif args[:2] == ("volume", "inspect"):
            output = json.dumps([{"Name": run.manifest["volume_name"], "Labels": {}}])
        elif args[0] == "inspect":
            return SimpleNamespace(returncode=1, stdout="[]")
        else:
            pytest.fail("the volume guard must run before container creation and must retain unowned storage")
        return SimpleNamespace(returncode=0, stdout=output)
    monkeypatch.setattr(run, "docker", docker)
    with pytest.raises(FixtureError, match="already exists|ownership mismatch"):
        run.start()
    run.cleanup()
    assert not any(args[0] in {"create", "start", "rm"} or args[:2] == ("volume", "rm") for args in seen)
    if case == "preexisting":
        assert not any(args[:2] == ("volume", "create") for args in seen)
