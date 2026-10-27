"""Exercise the real transfer picker and sharing controls in the owned browser."""
from pathlib import Path
import subprocess


def test_browser_library_picker():
    root = Path(__file__).parents[1]
    result = subprocess.run(["node", "tests/browser-library-browser.mjs"], cwd=root,
        capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
