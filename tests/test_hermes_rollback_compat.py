"""Fail-closed packaging for the previously qualified old/schema31 recovery pair."""
import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).parents[1] / "runtime/hermes/rollback_compat.py"
spec = importlib.util.spec_from_file_location("radhouse_rollback_compat", PATH)
rollback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollback)


def test_unknown_old_source_is_rejected_before_output_is_created(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in ("hermes_state.py", "hermes_state_sessions.py"):
        (source / name).write_text("# unexpected source\n")
    destination = tmp_path / "output"
    with pytest.raises(ValueError, match="hermes_rollback_source_mismatch"):
        rollback.write(source, destination)
    assert not destination.exists()
