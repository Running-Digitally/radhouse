"""Owned-cluster cleanup refuses ambiguous resources before invoking lifecycle commands."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from vs0_native import NativeRun
from vs0 import FixtureError


def test_native_fixture_requires_explicit_absolute_binary_path(monkeypatch):
    monkeypatch.delenv('RADHOUSE_VS0_NATIVE_BIN',raising=False)
    with pytest.raises(FixtureError, match='absolute native'):
        NativeRun().preflight()


@pytest.mark.parametrize('mode,marker', [(0o755,'correct'), (0o700,'wrong')])
def test_native_cleanup_preserves_cluster_with_ambiguous_ownership(tmp_path,mode,marker):
    run=NativeRun();run.output=tmp_path;run.manifest_path=tmp_path/'manifest.json'
    run.cluster=tmp_path/'data';run.cluster.mkdir(mode=mode)
    (run.cluster/'radhouse-fixture-id').write_text(run.run_id if marker=='correct' else 'another-run')
    run.cleanup()
    assert run.cluster.exists()
    assert run.manifest['cleanup']=='residual resources'
