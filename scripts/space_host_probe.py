#!/usr/bin/env python3
"""Read-only SPACE host screening. Does not install, mount, run Docker or create VMs.

Run on the proposed Linux host as the identity intended for later qualification.
Output contains no hostnames, addresses, environment values or credentials.
A successful screen is explicitly NOT host or isolation qualification.
"""
import json
import os
from pathlib import Path
import platform
import shutil
import stat


def device_access(path):
    try:
        return stat.S_ISCHR(os.stat(path).st_mode) and os.access(path, os.R_OK | os.W_OK)
    except OSError:
        return False


def kvm_api_available():
    if platform.system() != "Linux":
        return False
    try:
        import fcntl
        # KVM_GET_API_VERSION is read-only: no VM/vCPU is allocated.
        fd = os.open("/dev/kvm", os.O_RDWR | os.O_CLOEXEC)
        try:
            return fcntl.ioctl(fd, 0xAE00, 0) == 12
        finally:
            os.close(fd)
    except OSError:
        return False


def btrfs_registered():
    try:
        return any(line.split()[-1:] == ["btrfs"]
                   for line in Path("/proc/filesystems").read_text().splitlines())
    except OSError:
        return False


def collect():
    checks = {
        "linux_x86_64": platform.system() == "Linux" and platform.machine() == "x86_64",
        "kvm_device_access": device_access("/dev/kvm"),
        "kvm_api_version_12": kvm_api_available(),
        "tun_device_access": device_access("/dev/net/tun"),
        "loop_control_access": device_access("/dev/loop-control"),
        "btrfs_registered": btrfs_registered(),
        "btrfs_tool_present": shutil.which("btrfs") is not None,
        "docker_cli_present": shutil.which("docker") is not None,
    }
    return {
        "schema": "radhouse.space.host-screen.v1",
        "state": "needs_privileged_qualification" if all(checks.values()) else "prerequisites_missing",
        "qualified": False,
        "checks": checks,
        "not_tested": ["privileged Docker/device operations", "btrfs mount and snapshot operations",
                       "Firecracker boot and nested virtualization", "host capacity and recovery",
                       "effective network policy and isolation", "browser streaming and profile restore"],
    }


def main():
    result = collect()
    print(json.dumps(result, indent=2))
    return 0 if result["state"] == "needs_privileged_qualification" else 1


if __name__ == "__main__":
    raise SystemExit(main())
