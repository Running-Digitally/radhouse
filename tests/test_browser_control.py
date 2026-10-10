"""Ownership races, lost ACKs, restart and trusted-generation retirement."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import importlib.util
import os
from pathlib import Path
import sqlite3
import stat
import sys
import threading

import pytest

spec = importlib.util.spec_from_file_location("radhouse_browser_control",
    Path(__file__).resolve().parents[1] / "runtime/hermes/browser_control.py")
control = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = control
spec.loader.exec_module(control)


def make_controller(path, **kwargs):
    kwargs.setdefault("maintenance_held", lambda: False)
    return control.BrowserController(path, **kwargs)


@pytest.fixture
def fixture(tmp_path):
    clock = [100.0]
    path = tmp_path / "browser.sqlite3"
    controller = make_controller(path, clock=lambda: clock[0])
    identity = control.BrowserIdentity("conversation", "session", "generation-1")
    run = control.RunBinding("run-1", "session", "dispatch-1")
    owner = control.OwnerBinding("owner", "a"*64, 1, "tab-1")
    controller.bind_browser(identity, run, owner.principal_id)
    return controller, identity, run, owner, clock, path


def human(fixture):
    controller, identity, _, owner, _, _ = fixture
    pending = controller.request_takeover(identity, owner, "request-1", revision=1, auth_expires_at=300)
    observation = control.FenceObservation(identity, pending.takeover_after, True)
    return controller.confirm_takeover(identity, pending.revision, observation)


def test_takeover_blocks_later_agent_actions_until_ack_and_same_channel_fence(fixture):
    c, identity, run, owner, _, _ = fixture
    admitted = c.reserve_agent(identity, run, "agent-click")
    pending = c.request_takeover(identity, owner, "request-1", revision=1, auth_expires_at=300)
    assert pending.mode == "takeover_pending"
    assert pending.active_command == admitted
    with pytest.raises(control.ControlRejected, match="browser_control_blocked"):
        c.reserve_agent(identity, run, "next-click")
    with pytest.raises(control.ControlRejected, match="quiescence_unproven"):
        c.confirm_takeover(identity, pending.revision,
            control.FenceObservation(identity, "agent-click", True))
    c.complete_agent(identity, run, "agent-click", outcome="completed")
    with pytest.raises(control.ControlRejected, match="quiescence_unproven"):
        c.confirm_takeover(identity, pending.revision,
            control.FenceObservation(identity, None, True))
    with pytest.raises(control.ControlRejected, match="quiescence_unproven"):
        c.confirm_takeover(identity, pending.revision,
            control.FenceObservation(replace(identity, generation="other"), "agent-click", True))
    with pytest.raises(control.ControlRejected, match="quiescence_unproven"):
        c.confirm_takeover(identity, pending.revision, {"quiescent":True})
    taken = c.confirm_takeover(identity, pending.revision,
        control.FenceObservation(identity, "agent-click", True))
    assert taken.mode == "human"
    assert taken.revision > pending.revision
    assert taken.active_command is None


def test_two_tabs_race_for_control_only_one_has_a_lease(fixture):
    c, identity, _, owner, _, path = fixture
    barrier = threading.Barrier(2)
    other = replace(owner, tab_id="tab-2")
    def request(binding):
        independent = make_controller(path, clock=lambda:100)
        barrier.wait()
        try:
            return independent.request_takeover(identity, binding, binding.tab_id, revision=1, auth_expires_at=300)
        except control.ControlRejected as error:
            return str(error)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(request, [owner, other]))
    winners = [result for result in results if isinstance(result, control.ControlState)]
    assert len(winners) == 1
    assert results.count("browser_control_busy") == 1
    assert c.state(identity).lease.owner == winners[0].lease.owner


def test_agent_reservation_race_and_duplicate_completion_is_rejected(fixture):
    c, identity, run, _, _, path = fixture
    barrier = threading.Barrier(2)
    def reserve(command_id):
        independent = make_controller(path, clock=lambda:100)
        barrier.wait()
        try:
            return independent.reserve_agent(identity, run, command_id)
        except control.ControlRejected as error:
            return str(error)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(reserve, ["click-1", "click-2"]))
    winners = [result for result in results if isinstance(result, control.ActiveCommand)]
    assert len(winners) == 1
    assert results.count("browser_control_blocked") == 1
    c.complete_agent(identity, run, winners[0].command_id, outcome="completed")
    with pytest.raises(control.ControlRejected, match="command_mismatch"):
        c.complete_agent(identity, run, winners[0].command_id, outcome="completed")


def test_pending_takeover_retry_is_idempotent_but_another_login_cannot_reuse_it(fixture):
    c, identity, _, owner, _, _ = fixture
    first = c.request_takeover(identity, owner, "same-request", revision=1, auth_expires_at=300)
    assert c.request_takeover(identity, owner, "same-request", revision=1, auth_expires_at=300) == first
    for other in [replace(owner, auth_session_digest="b"*64), replace(owner, binding_revision=2),
                  replace(owner, tab_id="tab-2")]:
        with pytest.raises(control.ControlRejected, match="browser_control_busy"):
            c.request_takeover(identity, other, "same-request", revision=1, auth_expires_at=300)
    with pytest.raises(control.ControlRejected, match="owner_mismatch"):
        c.request_takeover(identity, replace(owner, principal_id="other"), "same-request", revision=1, auth_expires_at=300)


def test_input_is_durable_before_send_and_lost_http_ack_does_not_repeat_click(fixture):
    c, identity, _, owner, _, path = fixture
    taken = human(fixture)
    lease = taken.lease.lease_id
    first = c.reserve_input(identity, owner, lease, taken.revision, 1)
    assert first.execute
    # Another DB connection observes the reservation before any native send.
    other = make_controller(path, clock=lambda:100)
    duplicate = other.reserve_input(identity, owner, lease, taken.revision, 1)
    assert not duplicate.execute and duplicate.command_id == first.command_id
    assert duplicate.outcome == "reserved"
    assert other.state(identity).active_command.command_id == first.command_id
    with pytest.raises(control.ControlRejected, match="browser_control_busy"):
        c.reserve_input(identity, owner, lease, taken.revision, 2)
    applied = c.complete_input(identity, lease, 1, first.command_id, outcome="applied")
    assert applied.outcome == "applied" and not applied.execute
    retry = other.reserve_input(identity, owner, lease, taken.revision, 1)
    assert retry == applied
    next_action = c.reserve_input(identity, owner, lease, taken.revision, 2)
    assert next_action.execute and next_action.command_id != first.command_id


def test_duplicate_input_race_has_one_external_execution_permission(fixture):
    _, identity, _, owner, _, path = fixture
    taken = human(fixture)
    barrier = threading.Barrier(2)
    def reserve(_):
        independent = make_controller(path, clock=lambda:100)
        barrier.wait()
        return independent.reserve_input(identity, owner, taken.lease.lease_id, taken.revision, 1)
    with ThreadPoolExecutor(2) as pool:
        acks = list(pool.map(reserve, [1,2]))
    assert sum(ack.execute for ack in acks) == 1
    assert len({ack.command_id for ack in acks}) == 1


def test_owner_run_generation_and_revision_are_checked_before_input(fixture):
    c, identity, run, owner, _, _ = fixture
    taken = human(fixture)
    lease = taken.lease.lease_id
    for other in [replace(owner, auth_session_digest="b"*64), replace(owner, binding_revision=2),
                  replace(owner, tab_id="tab-2")]:
        with pytest.raises(control.ControlRejected, match="control_lease_unavailable"):
            c.reserve_input(identity, other, lease, taken.revision, 1)
    with pytest.raises(control.ControlRejected, match="owner_mismatch"):
        c.reserve_input(identity, replace(owner, principal_id="other"), lease, taken.revision, 1)
    with pytest.raises(control.ControlRejected, match="stale_control"):
        c.reserve_input(identity, owner, lease, taken.revision-1, 1)
    with pytest.raises(control.ControlRejected, match="stale_browser"):
        c.reserve_input(replace(identity, generation="generation-2"), owner, lease, taken.revision, 1)
    with pytest.raises(control.ControlRejected, match="run_mismatch"):
        c.reserve_agent(identity, replace(run, dispatch_key="other"), "old-action")
    with pytest.raises(control.ControlRejected, match="input_sequence_mismatch"):
        c.reserve_input(identity, owner, lease, taken.revision, 2)
    with pytest.raises(control.ControlRejected, match="invalid_binding"):
        c.reserve_input(identity, owner, lease, taken.revision, True)
    assert c.state(identity).active_command is None


def test_restart_with_reserved_input_is_uncertain_and_never_replayed(fixture):
    c, identity, _, owner, _, path = fixture
    taken = human(fixture)
    first = c.reserve_input(identity, owner, taken.lease.lease_id, taken.revision, 1)
    restarted = make_controller(path, clock=lambda:100)
    # Merely constructing another worker does not recover/reset shared state.
    assert restarted.state(identity).mode == "human"
    restarted.recover_startup()
    assert restarted.state(identity).mode == "recovering"
    assert restarted.state(identity).lease is None
    with pytest.raises(control.ControlRejected, match="control_lease_unavailable"):
        restarted.reserve_input(identity, owner, taken.lease.lease_id, taken.revision, 1)
    assert restarted.state(identity).last_input.outcome == "uncertain"
    # A late positive native ACK resolves the receipt, never grants new control.
    resolved = restarted.complete_input(identity, taken.lease.lease_id, 1, first.command_id, outcome="applied")
    assert resolved.outcome == "applied" and not resolved.execute
    assert restarted.state(identity).mode == "recovering"


def test_caller_timeout_remains_recovering_after_late_agent_ack(fixture):
    c, identity, run, owner, _, _ = fixture
    c.reserve_agent(identity, run, "slow-action")
    c.request_takeover(identity, owner, "request", revision=1, auth_expires_at=300)
    uncertain = c.complete_agent(identity, run, "slow-action", outcome="uncertain")
    assert uncertain.mode == "recovering" and uncertain.active_command is not None
    with pytest.raises(control.ControlRejected, match="browser_control_blocked"):
        c.reserve_agent(identity, run, "retry")
    with pytest.raises(control.ControlRejected, match="quiescence_unproven"):
        c.confirm_takeover(identity, uncertain.revision,
            control.FenceObservation(identity, "slow-action", True))
    c.complete_agent(identity, run, "slow-action", outcome="completed")
    assert c.state(identity).mode == "recovering"


def test_input_timeout_and_conflicting_ack_cannot_silently_undo_a_click(fixture):
    c, identity, _, owner, _, _ = fixture
    taken = human(fixture)
    ack = c.reserve_input(identity, owner, taken.lease.lease_id, taken.revision, 1)
    with pytest.raises(control.ControlRejected, match="command_mismatch"):
        c.complete_input(identity, taken.lease.lease_id, 1, "wrong-command", outcome="applied")
    c.complete_input(identity, taken.lease.lease_id, 1, ack.command_id, outcome="uncertain")
    assert c.state(identity).mode == "recovering"
    c.complete_input(identity, taken.lease.lease_id, 1, ack.command_id, outcome="applied")
    with pytest.raises(control.ControlRejected, match="ack_conflict"):
        c.complete_input(identity, taken.lease.lease_id, 1, ack.command_id, outcome="rejected")
    assert c.state(identity).mode == "recovering"


def test_heartbeat_cannot_outlive_owner_authentication_and_expiry_never_returns_agent(fixture):
    c, identity, run, owner, clock, _ = fixture
    pending = c.request_takeover(identity, owner, "short-login", revision=1, auth_expires_at=180)
    taken = c.confirm_takeover(identity, pending.revision, control.FenceObservation(identity, None, True))
    clock[0] = 150
    renewed = c.heartbeat(identity, owner, taken.lease.lease_id, taken.revision)
    assert renewed.lease.expires_at == 180
    assert renewed.revision == taken.revision
    clock[0] = 180
    with pytest.raises(control.ControlRejected, match="control_lease_unavailable"):
        c.heartbeat(identity, owner, taken.lease.lease_id, taken.revision)
    expired = c.state(identity)
    assert expired.mode == "paused" and expired.lease is None
    with pytest.raises(control.ControlRejected, match="browser_control_blocked"):
        c.reserve_agent(identity, run, "auto-resume")


def test_return_revokes_input_while_native_action_finishes_and_defers_followup(fixture):
    c, identity, run, owner, _, _ = fixture
    taken = human(fixture)
    ack = c.reserve_input(identity, owner, taken.lease.lease_id, taken.revision, 1)
    returned = c.begin_return(identity, owner, taken.lease.lease_id, taken.revision)
    assert returned.mode == "paused" and returned.lease is None
    assert returned.active_command.command_id == ack.command_id
    with pytest.raises(control.ControlRejected, match="control_lease_unavailable"):
        c.reserve_input(identity, owner, taken.lease.lease_id, taken.revision, 2)
    with pytest.raises(control.ControlRejected, match="browser_control_blocked"):
        c.reserve_agent(identity, run, "old-turn-action")
    c.complete_input(identity, taken.lease.lease_id, 1, ack.command_id, outcome="applied")
    assert c.state(identity).mode == "paused"
    with pytest.raises(control.ControlRejected, match="stale_control"):
        c.request_takeover(identity, owner, "request-1", revision=1, auth_expires_at=300)
    with pytest.raises(control.ControlRejected, match="run_mismatch"):
        c.bind_browser(identity, replace(run, run_id="followup"), owner.principal_id)


def test_missing_generation_is_unknown_until_positive_retirement_and_new_generation(fixture):
    c, identity, run, owner, clock, _ = fixture
    human(fixture)
    clock[0] = 200
    assert c.state(identity).mode == "paused"
    assert not c.activity_snapshot([]).known
    assert not c.activity_snapshot([identity]).idle
    with pytest.raises(control.ControlRejected, match="retirement_unproven"):
        c.retire_browser(identity, control.RetirementObservation(identity, True, False))
    retired = c.retire_browser(identity, control.RetirementObservation(identity, True, True))
    assert retired.retired and retired.admitted_run is None
    assert c.activity_snapshot([]).idle
    # Contradictory native presence is unknown, never idle.
    assert not c.activity_snapshot([identity]).known
    with pytest.raises(control.ControlRejected, match="browser_retired"):
        c.bind_browser(identity, run, owner.principal_id)
    with pytest.raises(control.ControlRejected, match="run_mismatch"):
        c.reserve_agent(identity, run, "late-old-run")
    new_identity = replace(identity, generation="generation-2")
    new_run = replace(run, run_id="run-2")
    c.bind_browser(new_identity, new_run, owner.principal_id)
    assert not c.activity_snapshot([]).known
    assert c.activity_snapshot([new_identity]).known
    with pytest.raises(control.ControlRejected, match="stale_browser"):
        c.state(identity)
    with pytest.raises(control.ControlRejected, match="previous_generation_unresolved"):
        c.bind_browser(identity, run, owner.principal_id)


def test_retirement_preserves_uncertain_receipt_without_recreating_browser(fixture):
    c, identity, _, owner, _, path = fixture
    taken = human(fixture)
    ack = c.reserve_input(identity, owner, taken.lease.lease_id, taken.revision, 1)
    c.retire_browser(identity, control.RetirementObservation(identity, True, True))
    assert c.activity_snapshot([]).idle
    receipt = c.state(identity).last_input
    assert (receipt.command_id, receipt.outcome) == (ack.command_id, "uncertain")


def test_generation_rotation_without_retirement_is_denied_and_restart_has_no_auto_resume(fixture):
    c, identity, run, owner, _, path = fixture
    human(fixture)
    with pytest.raises(control.ControlRejected, match="previous_generation_unresolved"):
        c.bind_browser(replace(identity, generation="generation-2"), run, owner.principal_id)
    restarted = make_controller(path, clock=lambda:100)
    restarted.recover_startup()
    assert restarted.state(identity).mode == "paused"
    with pytest.raises(control.ControlRejected, match="browser_control_blocked"):
        restarted.reserve_agent(identity, run, "auto-resume")


def test_store_and_events_cannot_contain_input_payloads(fixture):
    c, identity, _, owner, _, path = fixture
    taken = human(fixture)
    with pytest.raises(TypeError):
        c.reserve_input(identity, owner, taken.lease.lease_id, taken.revision, 1,
                        text="DO-NOT-PERSIST")
    with sqlite3.connect(path) as db:
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert tables == ["browser_control_state"]
        assert "DO-NOT-PERSIST" not in db.execute("SELECT body FROM browser_control_state").fetchone()[0]
    assert "DO-NOT-PERSIST" not in repr(c.state(identity))


def test_failed_native_input_can_be_rejected_without_replaying_sequence(fixture):
    c, identity, _, owner, _, _ = fixture
    taken = human(fixture)
    ack = c.reserve_input(identity, owner, taken.lease.lease_id, taken.revision, 1)
    c.complete_input(identity, taken.lease.lease_id, 1, ack.command_id, outcome="rejected")
    duplicate = c.reserve_input(identity, owner, taken.lease.lease_id, taken.revision, 1)
    assert duplicate.outcome == "rejected" and not duplicate.execute
    assert c.reserve_input(identity, owner, taken.lease.lease_id, taken.revision, 2).execute


def test_expired_old_takeover_request_never_reacquires_control_on_retry(fixture):
    c, identity, _, owner, clock, _ = fixture
    human(fixture)
    clock[0] = 200
    assert c.state(identity).mode == "paused"
    with pytest.raises(control.ControlRejected, match="stale_control"):
        c.request_takeover(identity, owner, "request-1", revision=1, auth_expires_at=300)
    pending = c.request_takeover(identity, owner, "new-owner-intent", revision=c.state(identity).revision, auth_expires_at=300)
    assert pending.mode == "takeover_pending"


@pytest.mark.parametrize("generation", ["generation-1", "different-claimed-generation"])
def test_two_conversations_cannot_claim_the_same_live_native_session(fixture, generation):
    c, identity, run, owner, _, _ = fixture
    alias = replace(identity, conversation_id="another-conversation", generation=generation)
    with pytest.raises(control.ControlRejected, match="native_session_already_bound"):
        c.bind_browser(alias, replace(run, run_id="other-run"), "another-owner")
    assert c.reserve_agent(identity, run, "original-command").command_id == "original-command"
    with pytest.raises(control.ControlRejected, match="browser_unknown"):
        c.reserve_agent(alias, replace(run, run_id="other-run"), "conflicting-command")


def test_aliases_racing_for_initial_native_binding_have_one_winner(tmp_path):
    path = tmp_path / "alias.sqlite3"
    make_controller(path, clock=lambda:100)
    barrier = threading.Barrier(2)
    def bind(conversation):
        independent = make_controller(path, clock=lambda:100)
        barrier.wait()
        identity = control.BrowserIdentity(conversation, "one-native-session", "generation")
        run = control.RunBinding(conversation, "one-native-session", conversation)
        try:
            independent.bind_browser(identity, run, conversation)
            return independent.reserve_agent(identity, run, conversation)
        except control.ControlRejected as error:
            return str(error)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(bind, ["conversation-a", "conversation-b"]))
    assert sum(isinstance(result, control.ActiveCommand) for result in results) == 1
    assert results.count("native_session_already_bound") == 1


def test_private_store_creation_and_rejection_of_world_readable_file(tmp_path):
    private = tmp_path / "private.sqlite3"
    old_umask = os.umask(0o022)
    try:
        make_controller(private)
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(private.stat().st_mode) == 0o600
    private.chmod(0o644)
    with pytest.raises(control.ControlRejected, match="control_store_requires_private_regular_file"):
        make_controller(private)
    assert stat.S_IMODE(private.stat().st_mode) == 0o644


def test_store_symlink_and_later_permission_drift_fail_closed(fixture, tmp_path):
    c, identity, run, _, _, path = fixture
    alias = tmp_path / "alias.sqlite3"
    alias.symlink_to(path)
    with pytest.raises(control.ControlRejected, match="control_store_requires_private_regular_file"):
        make_controller(alias)
    path.chmod(0o640)
    with pytest.raises(control.ControlRejected, match="control_store_requires_private_regular_file"):
        c.reserve_agent(identity, run, "permission-drift")


def test_only_latest_input_ack_is_retained_and_older_sequences_never_execute(fixture):
    c, identity, _, owner, _, path = fixture
    taken = human(fixture)
    for sequence in range(1, 33):
        ack = c.reserve_input(identity, owner, taken.lease.lease_id, taken.revision, sequence)
        c.complete_input(identity, taken.lease.lease_id, sequence, ack.command_id, outcome="applied")
    with pytest.raises(control.ControlRejected, match="stale_input"):
        c.reserve_input(identity, owner, taken.lease.lease_id, taken.revision, 1)
    latest = c.reserve_input(identity, owner, taken.lease.lease_id, taken.revision, 32)
    assert latest.outcome == "applied" and not latest.execute
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM browser_control_state").fetchone()[0] == 1
    assert c.state(identity).last_input.sequence == 32


def test_existing_maintenance_hold_blocks_admission_while_completion_can_drain(fixture):
    c, identity, run, owner, _, _ = fixture
    c.reserve_agent(identity, run, "in-flight")
    c.maintenance_held = lambda: True
    for operation in [
        lambda: c.bind_browser(identity, run, owner.principal_id),
        lambda: c.reserve_agent(identity, run, "late"),
        lambda: c.request_takeover(identity, owner, "request", revision=1, auth_expires_at=300),
    ]:
        with pytest.raises(control.ControlRejected, match="maintenance_held"):
            operation()
    assert c.activity_snapshot([identity]).active_commands == 1
    assert c.complete_agent(identity, run, "in-flight", outcome="completed").active_command is None


def test_existing_hold_also_blocks_human_admission_and_heartbeat(fixture):
    c, identity, _, owner, _, _ = fixture
    taken = human(fixture)
    ack = c.reserve_input(identity, owner, taken.lease.lease_id, taken.revision, 1)
    c.maintenance_held = lambda: True
    for operation in [
        lambda: c.reserve_input(identity, owner, taken.lease.lease_id, taken.revision, 2),
        lambda: c.heartbeat(identity, owner, taken.lease.lease_id, taken.revision),
        lambda: c.confirm_takeover(identity, taken.revision, control.FenceObservation(identity, None, True)),
    ]:
        with pytest.raises(control.ControlRejected, match="maintenance_held"):
            operation()
    assert c.complete_input(identity, taken.lease.lease_id, 1, ack.command_id, outcome="applied").outcome == "applied"
    assert not c.activity_snapshot([identity]).idle


@pytest.mark.parametrize("observation", [None, 0, "false"])
def test_unknown_existing_maintenance_authority_denies_admission(fixture, observation):
    c, identity, run, _, _, _ = fixture
    c.maintenance_held = lambda: observation
    with pytest.raises(control.ControlRejected, match="maintenance_unknown"):
        c.reserve_agent(identity, run, "command")


def test_root_hold_then_status_observes_a_reservation_admitted_just_before_hold(tmp_path):
    entered, release = threading.Event(), threading.Event()
    hold = [False]
    def maintenance():
        admitted_before_hold = hold[0]
        entered.set()
        assert release.wait(2)
        return admitted_before_hold
    path = tmp_path / "ordered.sqlite3"
    c = make_controller(path, maintenance_held=maintenance, clock=lambda: 100)
    observer = make_controller(path, clock=lambda: 100)
    identity = control.BrowserIdentity("conversation", "session", "generation")
    run = control.RunBinding("run", "session", "dispatch")
    with ThreadPoolExecutor(2) as pool:
        reservation = pool.submit(c.bind_browser, identity, run, "owner")
        assert entered.wait(2)
        hold[0] = True  # The existing root hold is created before status is read.
        status = pool.submit(observer.activity_snapshot, [])
        release.set()
        assert reservation.result().identity == identity
        snapshot = status.result()
    assert not snapshot.known and not snapshot.idle
    with pytest.raises(control.ControlRejected, match="maintenance_held"):
        c.reserve_agent(identity, run, "after-hold")
