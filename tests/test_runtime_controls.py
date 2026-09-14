from dataclasses import replace
import pytest

from radhouse.domain.tasks import InputFile, Rejected, RuntimeFailure, RuntimeResult, runtime_input

pytestmark = pytest.mark.postgres


def active_task(service, fake_work, alice, envelope, start):
    fake_work.result = lambda *_: RuntimeResult("running")
    return service.run(service.admit(alice, envelope(), start).task_id)


def test_guidance_stays_on_current_run_and_does_not_mutate_dispatch_input(service, fake_work, alice, envelope, start):
    task = active_task(service, fake_work, alice, envelope, start)
    calls = []
    fake_work.steer = lambda task, run, text: calls.append((run.run_id, text)) or True
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
    def lose(*args):
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
