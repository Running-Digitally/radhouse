"""Exercise the actual browser sources with deterministic DOM/storage substitutes."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_chat_client_and_formatter_regressions():
    node = shutil.which("node")
    if node is None:
        pytest.skip("chat JavaScript regression tests require Node.js")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "--test", "tests/chat-client.test.mjs", "tests/chat-format.test.mjs", "tests/browser-address.test.mjs"],
        cwd=root, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
