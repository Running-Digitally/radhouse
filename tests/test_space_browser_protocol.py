import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("space_browser_protocol_test",
    Path(__file__).parents[1] / "runtime/selkies/space_protocol.py")
protocol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)
HOLDER = "a" * 43
VIEWER = "b" * 43
TABLE = {HOLDER: {"role": "viewer", "slot": None, "mk_control": True},
         VIEWER: {"role": "viewer", "slot": None}}


def test_expired_grant_cannot_be_resurrected_by_late_renewal():
    now = [10.0]
    fence = protocol.GrantFence(clock=lambda: now[0])
    fence.publish(TABLE, 3)
    assert fence.allowed(HOLDER) and not fence.allowed(VIEWER)
    now[0] = 13
    assert not fence.allowed(HOLDER)
    with pytest.raises(protocol.Rejected, match="grant_expired"):
        fence.renew(3)
    with pytest.raises(protocol.Rejected, match="grant_expired"):
        fence.publish(TABLE, 3)
    assert not fence.allowed(HOLDER)


def test_freeze_survives_renewal_and_rejects_stale_release():
    fence = protocol.GrantFence()
    fence.publish(TABLE, 3)
    freeze = "a" * 32
    fence.freeze(freeze)
    assert not fence.allowed(HOLDER)
    fence.renew(3)
    with pytest.raises(protocol.Rejected, match="input_release_unconfirmed"):
        fence.thaw("b" * 32)
    assert not fence.allowed(HOLDER)
    fence.thaw(freeze)
    assert fence.allowed(HOLDER)


def test_rotating_holder_retires_old_input_even_after_freeze():
    fence = protocol.GrantFence()
    fence.publish(TABLE, 3)
    fence.freeze("c" * 32)
    fence.publish({VIEWER: {"role": "viewer", "slot": None, "mk_control": True}}, 3)
    fence.thaw("c" * 32)
    assert not fence.allowed(HOLDER) and fence.allowed(VIEWER)
    fence.revoke()
    assert not fence.allowed(VIEWER) and not fence.table


@pytest.mark.parametrize("ttl", [0, -1, 4, True, float("nan"), float("inf"), "3"])
def test_invalid_grant_duration_rejected(ttl):
    with pytest.raises(protocol.Rejected):
        protocol.GrantFence().publish(TABLE, ttl)


@pytest.mark.parametrize("table", [
    {HOLDER: {"role": "admin", "slot": None}},
    {HOLDER: {"role": "viewer", "slot": None, "command": True}},
    {HOLDER: {"role": "viewer", "slot": None, "mk_control": False}},
    {HOLDER: TABLE[HOLDER], VIEWER: TABLE[HOLDER]},
    {"malformed": TABLE[HOLDER]},
])
def test_guest_permissions_cannot_expand_the_input_allowlist(table):
    with pytest.raises(protocol.Rejected):
        protocol.grants(table)


def test_protocol_accepts_only_fixed_operations_and_fields():
    value = {"schema": protocol.SCHEMA, "launch_id": "a" * 32,
             "request_id": "b" * 32, "sequence": 1, "op": "status", "body": {}}
    assert protocol.request(value) == value
    for changes in ({"op": "exec"}, {"body": {"path": "/etc/passwd"}},
                    {"launch_id": "../"}, {"sequence": True}, {"destination": "https://elsewhere.test"}):
        with pytest.raises(protocol.Rejected):
            protocol.request({**value, **changes})
