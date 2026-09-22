from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import pytest

from radhouse.domain.tasks import InputFile, Rejected, RuntimeFailure, RuntimeGuidanceReceipt, RuntimeResult, runtime_input

pytestmark = pytest.mark.postgres


def active_task(service, fake_work, alice, envelope, start):
    fake_work.result = lambda *_: RuntimeResult("running")
    return service.run(service.admit(alice, envelope(), start).task_id)


def receipt(run, control_id, text, state="accepted", revision=1):
    return RuntimeGuidanceReceipt(run.run_id, control_id, sha256(text.encode()).hexdigest(),
        state != "too_late", state, revision, None,
        "checkpoint-1" if state == "applied" else None,
        "request-2" if state == "applied" else None)


def test_guidance_stays_on_current_run_and_does_not_mutate_dispatch_input(service, fake_work, alice, envelope, start):
    task = active_task(service, fake_work, alice, envelope, start)
    calls = []
    fake_work.steer = lambda task, run, text, control_id: calls.append((run.run_id, text)) or receipt(run, control_id, text)
    command = envelope()
    updated = service.guide(alice, task.task_id, task.state_revision, "Focus on costs", envelope=command)
    replay = service.guide(alice, task.task_id, task.state_revision, "Focus on costs", envelope=command)
    assert replay == updated
    assert len(calls) == 1 and updated.guidance[0]["state"] == "accepted"
    assert updated.brief == task.brief and updated.budget_remaining == task.budget_remaining
    assert updated.attempt_id == task.attempt_id
    recovered = service.recover(task.task_id)
    assert "operation_unknown" not in recovered.blockers


def test_lost_guidance_reply_is_durable_and_never_replayed(service, service_factory, fake_work, alice, envelope, start):
    task = active_task(service, fake_work, alice, envelope, start)
    calls = []
    def lose(*args, **kwargs):
        calls.append(args)
        raise RuntimeFailure("runtime_timeout")
    fake_work.steer = lose
    command = envelope()
    task2 = service.guide(alice, task.task_id, task.state_revision, "Use the attached figures", envelope=command)
    assert task2.guidance[0]["state"] == "unknown"
    restarted = service_factory()
    restarted.guide(alice, task.task_id, task.state_revision, "Use the attached figures", envelope=command)
    assert len(calls) == 1
    with pytest.raises(Rejected, match="control_outcome_unknown"):
        restarted.guide(alice, task.task_id, task2.state_revision, "Try again", envelope=envelope())


def test_guidance_applied_reconciles_across_restart_without_post_or_result_duplication(
    service, service_factory, fake_work, alice, envelope, start, store,
):
    task = active_task(service, fake_work, alice, envelope, start)
    admitted = []
    def steer(task, run, text, control_id):
        value = receipt(run, control_id, text)
        admitted.append(value)
        return value
    fake_work.steer = steer
    queued = service.guide(alice, task.task_id, task.state_revision, "  Prefer cost.\n", envelope=envelope())
    assert queued.guidance[0]["application_state"] == "accepted"
    assert not queued.guidance[0]["application_final"]
    applied = replace(admitted[0], state="applied", revision=2, checkpoint_id="checkpoint-1", api_request_id="request-2")
    fake_work.result = lambda *_: RuntimeResult("completed", "Guided result", guidance_receipts=(applied,))
    restarted = service_factory()
    done = restarted.recover(task.task_id)
    assert done.phase == "closed" and done.result == "Guided result"
    assert done.guidance[0]["application_state"] == "applied"
    assert done.guidance[0]["application_final"]
    assert restarted.advance(task.task_id, "worker") == done
    assert task.task_id not in restarted.coordination_candidates(100)
    assert len(admitted) == 1 and fake_work.start_count == 1
    with store.transaction() as tx:
        assert tx.operation(applied.control_id).state == "confirmed"


def test_terminal_get_before_lost_post_receipt_remains_reconcilable(
    service, service_factory, fake_work, alice, envelope, start, clock, store,
):
    task = active_task(service, fake_work, alice, envelope, start)
    observed = []
    def steer(task, run, text, control_id):
        observed.append(receipt(run, control_id, text, "too_late"))
        raise RuntimeFailure("lost_reply")
    fake_work.steer = steer
    service.guide(alice, task.task_id, task.state_revision, "Update", envelope=envelope())
    fake_work.result = lambda *_: RuntimeResult("completed", "Original result", guidance_receipts=())
    done = service.recover(task.task_id)
    assert done.guidance[0]["application_state"] == "unknown"
    assert not done.guidance[0]["application_final"]
    assert task.task_id in service.coordination_candidates(100)
    fake_work.result = lambda *_: RuntimeResult("completed", "Original result", guidance_receipts=tuple(observed))
    recovered = service_factory().advance(task.task_id, "worker")
    assert recovered.guidance[0]["application_state"] == "too_late"
    assert recovered.result_digest == done.result_digest and recovered.attempt_id == done.attempt_id
    assert len(observed) == 1 and fake_work.start_count == 1


def test_concurrent_poll_newer_than_post_never_regresses_receipt_or_operation(
    service, fake_work, alice, envelope, start, store,
):
    from radhouse.application.guidance import reconcile
    task = active_task(service, fake_work, alice, envelope, start)
    def steer(task, run, text, control_id):
        reconcile(service, task.task_id, run.run_id, (receipt(run, control_id, text, "applied", 2),))
        raise RuntimeFailure("lost_post_reply")
    fake_work.steer = steer
    updated = service.guide(alice, task.task_id, task.state_revision, "Update", envelope=envelope())
    assert updated.guidance[0]["application_state"] == "applied"
    assert updated.guidance[0]["state"] == "accepted"
    with store.transaction() as tx:
        assert tx.operation(updated.guidance[0]["id"]).state == "confirmed"


def test_receipt_correlation_conflicts_fail_before_completion(service, fake_work, alice, envelope, start):
    from radhouse.application.guidance import reconcile
    task = active_task(service, fake_work, alice, envelope, start)
    values = []
    fake_work.steer = lambda task, run, text, control_id: values.append(receipt(run, control_id, text)) or values[-1]
    guided = service.guide(alice, task.task_id, task.state_revision, "Update", envelope=envelope())
    accepted = values[0]
    for bad in (replace(accepted, run_id="another-run"), replace(accepted, input_sha256="0" * 64),
                replace(accepted, control_id="control:" + "0" * 64), replace(accepted, reason="changed")):
        with pytest.raises(RuntimeFailure):
            reconcile(service, task.task_id, accepted.run_id, (bad,))
        assert service.get(alice, task.task_id, envelope=envelope()) == guided
    with pytest.raises(RuntimeFailure):
        reconcile(service, task.task_id, accepted.run_id, (object(),))
    with pytest.raises(RuntimeFailure):
        reconcile(service, task.task_id, accepted.run_id, (accepted, accepted))


def test_missing_receipt_expires_without_runtime_send_or_reopening(service, fake_work, alice, envelope, start, clock):
    task = active_task(service, fake_work, alice, envelope, start)
    def lose(*args, **kwargs):
        raise RuntimeFailure("lost_reply")
    fake_work.steer = lose
    service.guide(alice, task.task_id, task.state_revision, "Update", envelope=envelope())
    fake_work.result = lambda *_: RuntimeResult("completed", "Result", guidance_receipts=())
    done = service.recover(task.task_id)
    clock.advance(days=2)
    fake_work.result = lambda *_: pytest.fail("expired receipt must not query runtime")
    expired = service.advance(task.task_id, "worker")
    assert expired.guidance[0]["application_state"] == "unknown"
    assert expired.guidance[0]["application_reason"] == "receipt_retention_expired"
    assert expired.guidance[0]["application_final"]
    assert expired.result_digest == done.result_digest
    assert task.task_id not in service.coordination_candidates(100)


def test_legacy_runtime_refuses_new_guidance_before_saving_or_posting(service, fake_work, alice, envelope, start):
    task = active_task(service, fake_work, alice, envelope, start)
    capabilities = fake_work.capabilities(task)
    fake_work.capabilities = lambda _: replace(capabilities, guidance_receipts=False)
    fake_work.steer = lambda *args, **kwargs: pytest.fail("unsupported guidance must not post")
    with pytest.raises(Rejected, match="runtime_guidance_receipts_unavailable"):
        service.guide(alice, task.task_id, task.state_revision, "Update", envelope=envelope())
    assert service.get(alice, task.task_id, envelope=envelope()) == task


def test_paused_task_reconciles_original_run_without_starting_another(service, fake_work, alice, envelope, start):
    task = active_task(service, fake_work, alice, envelope, start)
    values = []
    def lose(task, run, text, control_id):
        values.append(receipt(run, control_id, text, "not_applied", 2))
        raise RuntimeFailure("lost_reply")
    fake_work.steer = lose
    guided = service.guide(alice, task.task_id, task.state_revision, "Update", envelope=envelope())
    service.pause(alice, task.task_id, guided.state_revision, envelope=envelope())
    fake_work.result = lambda *_: RuntimeResult("cancelled", guidance_receipts=())
    paused = service.recover(task.task_id)
    assert paused.phase == "queued" and paused.attempt_id is None and "human_pause" in paused.blockers
    fake_work.result = lambda task, dispatch: (
        RuntimeResult("cancelled", guidance_receipts=tuple(values))
        if dispatch.run_id == values[0].run_id else pytest.fail("wrong attempt queried")
    )
    assert task.task_id in service.coordination_candidates(100)
    reconciled = service.advance(task.task_id, "worker")
    assert reconciled.phase == "queued" and reconciled.attempt_id is None
    assert reconciled.guidance[0]["application_state"] == "not_applied"
    assert fake_work.start_count == 1
    assert task.task_id not in service.coordination_candidates(100)


def test_permission_requires_exact_request_existing_grant_and_fresh_assurance(service, fake_work, alice, envelope, start, clock):
    permission = {"request_id": "approval-1", "command": "cat /approved/report.txt", "run_id": "run-1"}
    fake_work.result = lambda *_: RuntimeResult("running", permission_request=permission)
    task = service.run(service.admit(alice, envelope(), start).task_id)
    called = []
    fake_work.approve = lambda *args: called.append(args) or True
    def respond(actor, choice, command=None):
        return service.respond_permission(actor, task.task_id, task.state_revision, permission["request_id"],
            task.permission_request["digest"], choice, envelope=command or envelope())
    with pytest.raises(Rejected, match="resource_grant_required"):
        respond(alice, "once")
    service.approval_commands = {start.bot_id: (permission["command"],)}
    with pytest.raises(Rejected, match="fresh_assurance_required"):
        respond(replace(alice, assurance_until=clock()), "once")
    command = envelope()
    result = respond(alice, "once", command)
    respond(alice, "once", command)
    assert len(called) == 1 and result.guidance[-1]["choice"] == "once"


def test_lost_denial_retries_once_when_exact_request_remains_pending(
    service, fake_work, alice, envelope, start,
):
    admitted = service.admit(alice, envelope(), start)
    claimed = service.claim(admitted.task_id, "worker")
    permission = {
        "request_id": "approval-1", "command": "cat /unapproved/report.txt",
        "run_id": "run-" + claimed.attempt_id,
    }
    current_permission = [permission]
    fake_work.result = lambda *_: RuntimeResult(
        "running", permission_request=current_permission[0]
    )
    task = service.run(admitted.task_id)
    from radhouse.application.service import fingerprint
    assert task.permission_request == {
        **permission, "digest": fingerprint(permission), "allow_once": False,
    }
    calls = []

    def approve_lost(*args):
        calls.append(args)
        raise RuntimeFailure("runtime_timeout")

    fake_work.approve = approve_lost
    unknown = service.respond_permission(
        alice, task.task_id, task.state_revision, permission["request_id"],
        task.permission_request["digest"], "deny", envelope=envelope(),
    )
    assert {
        key: unknown.guidance[-1].get(key)
        for key in ("kind", "choice", "state", "request_id", "run_id", "permission_digest",
                    "expected_revision", "reconcile_attempted")
    } == {
        "kind": "permission", "choice": "deny", "state": "unknown",
        "request_id": permission["request_id"], "run_id": permission["run_id"],
        "permission_digest": task.permission_request["digest"],
        "expected_revision": task.state_revision,
        "reconcile_attempted": None,
    }

    def approve_reconciled(*args):
        calls.append(args)
        current_permission[0] = None
        return True

    fake_work.approve = approve_reconciled
    reconciled = service.recover(task.task_id)
    assert len(calls) == 2
    assert reconciled.guidance[-1]["state"] == "accepted"
    assert reconciled.guidance[-1]["reconcile_attempted"] is True
    assert reconciled.permission_request is None
    service.recover(task.task_id)
    assert len(calls) == 2


def test_lost_approval_is_never_retried(
    service, fake_work, alice, envelope, start,
):
    permission = {"request_id": "approval-1", "command": "cat /approved/report.txt", "run_id": "run-1"}
    fake_work.result = lambda *_: RuntimeResult("running", permission_request=permission)
    task = service.run(service.admit(alice, envelope(), start).task_id)
    service.approval_commands = {start.bot_id: (permission["command"],)}
    calls = []

    def lose(*args):
        calls.append(args)
        raise RuntimeFailure("runtime_timeout")

    fake_work.approve = lose
    unknown = service.respond_permission(
        alice, task.task_id, task.state_revision, permission["request_id"],
        task.permission_request["digest"], "once", envelope=envelope(),
    )
    fake_work.approve = lambda *args: pytest.fail("lost approval must never retry")
    service.recover(task.task_id)
    assert len(calls) == 1 and unknown.guidance[-1]["state"] == "unknown"


def test_lost_denial_is_not_retried_after_the_request_changes(
    service, fake_work, alice, envelope, start,
):
    admitted = service.admit(alice, envelope(), start)
    claimed = service.claim(admitted.task_id, "worker")
    permission = {
        "request_id": "approval-1", "command": "cat /first/report.txt",
        "run_id": "run-" + claimed.attempt_id,
    }
    current_permission = [permission]
    fake_work.result = lambda *_: RuntimeResult(
        "running", permission_request=current_permission[0]
    )
    task = service.run(admitted.task_id)
    calls = []

    def lose(*args):
        calls.append(args)
        raise RuntimeFailure("runtime_timeout")

    fake_work.approve = lose
    service.respond_permission(
        alice, task.task_id, task.state_revision, permission["request_id"],
        task.permission_request["digest"], "deny", envelope=envelope(),
    )
    current_permission[0] = {
        "request_id": "approval-1", "command": "cat /changed/report.txt", "run_id": permission["run_id"],
    }
    fake_work.approve = lambda *args: pytest.fail("changed denial must never retry")
    recovered = service.recover(task.task_id)
    recovered = service.recover(task.task_id)
    assert len(calls) == 1
    assert recovered.guidance[-1]["state"] == "unknown"
    assert recovered.permission_request["command"] == "cat /changed/report.txt"


def test_legacy_lost_denial_requires_original_operation_fingerprint(
    service, fake_work, alice, envelope, start,
):
    admitted = service.admit(alice, envelope(), start)
    claimed = service.claim(admitted.task_id, "worker")
    permission = {
        "request_id": "approval-1", "command": "cat /legacy/report.txt",
        "run_id": "run-" + claimed.attempt_id,
    }
    current_permission = [permission]
    fake_work.result = lambda *_: RuntimeResult(
        "running", permission_request=current_permission[0]
    )
    task = service.run(admitted.task_id)
    calls = []

    def lose(*args):
        calls.append(args)
        raise RuntimeFailure("runtime_timeout")

    fake_work.approve = lose
    service.respond_permission(
        alice, task.task_id, task.state_revision, permission["request_id"],
        task.permission_request["digest"], "deny", envelope=envelope(),
    )
    with service.store.transaction() as tx:
        current = tx.task(task.task_id)
        legacy = tuple(
            {key: value for key, value in item.items()
             if key not in {"permission_digest", "expected_revision"}}
            for item in current.guidance
        )
        tx.save_task(current.evolve(guidance=legacy), current.state_revision)

    def approve_reconciled(*args):
        calls.append(args)
        current_permission[0] = None
        return True

    fake_work.approve = approve_reconciled
    recovered = service.recover(task.task_id)
    assert len(calls) == 2
    assert recovered.guidance[-1]["state"] == "accepted"


def test_files_and_followup_context_are_selected_snapshots(service, alice, bob, envelope, start):
    first = service.run(service.admit(alice, envelope(), start).task_id)
    second = service.admit(alice, envelope(), replace(start, brief="Summarize this", follows_task_id=first.task_id,
        files=(InputFile("numbers.txt", "42"),)))
    assert second.previous_result == first.result
    assert first.result in runtime_input(second) and "numbers.txt\n42" in runtime_input(second)
    assert service.get(alice, second.task_id, envelope=envelope()).files == second.files
    with pytest.raises(Rejected):
        service.admit(bob, envelope(principal="bob"), replace(start, follows_task_id=first.task_id))


def test_files_exceeding_total_byte_limit_are_refused(service, alice, envelope, start):
    with pytest.raises(Rejected, match="invalid_input_files"):
        service.admit(alice, envelope(), replace(start, files=(InputFile("data.txt", "é" * 40000),)))


def test_image_digest_is_required_to_match_the_decoded_pixels(service, alice, envelope, start):
    import base64
    image = InputFile(
        "screen.png", base64.b64encode(b"pixels").decode(),
        "image/png", "base64", "0" * 64,
    )
    with pytest.raises(Rejected, match="invalid_input_files"):
        service.admit(alice, envelope(), replace(start, files=(image,)))
