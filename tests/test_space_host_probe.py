"""Host screening must never masquerade as real Firecracker qualification."""
import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location("space_host_probe", Path(__file__).parents[1] / "scripts/space_host_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@pytest.fixture
def linux_screen(monkeypatch):
    monkeypatch.setattr(probe.platform, "system", lambda: "Linux")
    monkeypatch.setattr(probe.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(probe, "device_access", lambda _: True)
    monkeypatch.setattr(probe, "kvm_api_available", lambda: True)
    monkeypatch.setattr(probe, "btrfs_registered", lambda: True)
    monkeypatch.setattr(probe.shutil, "which", lambda _: "/synthetic/tool")


def test_all_local_checks_pass_still_requires_privileged_and_browser_qualification(linux_screen):
    result = probe.collect()
    assert result["state"] == "needs_privileged_qualification"
    assert result["qualified"] is False
    assert len(result["not_tested"]) == 6


@pytest.mark.parametrize("system,machine", [("Darwin", "arm64"), ("Linux", "aarch64"), ("Windows", "AMD64")])
def test_unsupported_host_never_passes_screen(linux_screen, monkeypatch, system, machine):
    monkeypatch.setattr(probe.platform, "system", lambda: system)
    monkeypatch.setattr(probe.platform, "machine", lambda: machine)
    result = probe.collect()
    assert result["state"] == "prerequisites_missing" and not result["qualified"]


def test_inaccessible_kvm_is_reported_without_trying_to_install_or_elevate(linux_screen, monkeypatch):
    monkeypatch.setattr(probe, "kvm_api_available", lambda: False)
    assert probe.collect()["state"] == "prerequisites_missing"


def test_absent_devices_are_a_failed_screen():
    assert probe.device_access("/nonexistent-space-test-device") is False
