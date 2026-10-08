"""Informational network evidence never implies unverified firewall coverage."""
from datetime import datetime, timedelta, timezone

import pytest

from radhouse.chat.admin import AdminService, EffectiveSettings
from radhouse.chat.store import ChatStore
from radhouse.integrations.hermes import browser_network_policy


def policy():
    return {"schema": "radhouse.browser-network-policy.v1", "verified": True,
        "source": "VM270 effective firewall receipt sha256:fixture",
        "verified_at": "2026-10-07T01:00:00+00:00", "enforcement": "vm_firewall",
        "allowed": ["Public HTTP(S) and permitted LAN routes"], "denied": ["As defined by the recorded VM firewall"]}


@pytest.mark.parametrize("change", [
    {"schema": "unknown"}, {"verified": "yes"}, {"source": None},
    {"verified_at": None}, {"verified_at": "no date"}, {"verified_at": "2026-10-07T01:00:00"},
    {"verified_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
    {"allowed": ["x"] * 17}, {"allowed": ["a\nsecond instruction"]}, {"denied": ["x" * 257]},
    {"credentials": "private"}, {"enforcement": "application_proxy"},
])
def test_malformed_policy_cannot_become_verified_evidence(change):
    assert browser_network_policy({**policy(), **change}) is None


def test_policy_preserves_source_age_without_claiming_current_reachability():
    result = browser_network_policy(policy())
    assert result == policy()
    assert result["verified_at"] == "2026-10-07T01:00:00+00:00"
    result["allowed"].append("changed")
    assert browser_network_policy(policy()) == policy()


def test_infrastructure_keeps_missing_and_failed_policy_explicitly_unverified(tmp_path):
    store = ChatStore(tmp_path / "chat.sqlite3")
    admin = AdminService(store, settings=EffectiveSettings(300, 3600, 86400, browser_enabled=True))
    assert admin.infrastructure()["browser_network_policy"]["verified"] is False
    def failed(): raise RuntimeError("secret-token")
    admin.network_policy_probe = failed
    result = admin.infrastructure()["browser_network_policy"]
    assert result['verified'] is False
    assert result['source'] is None
    assert "secret-token" not in str(result)
    admin.network_policy_probe = policy
    assert admin.infrastructure()["browser_network_policy"] == policy()
