import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory

spec = importlib.util.spec_from_file_location('review_resources', Path(__file__).parents[1]/'runtime/selkies/resources.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def sample(root, *, limit=6*1024**3, current=0, cache=0):
    (root/'memory.max').write_text(str(limit))
    (root/'memory.current').write_text(str(current))
    (root/'memory.stat').write_text(f'inactive_file {cache}\nanon 0\n')
    return r.pressure(root)


def test_large_reclaimable_download_cache_is_not_working_memory_pressure():
    with TemporaryDirectory() as d:
        root = Path(d)
        assert not sample(root, current=4*1024**3, cache=3*1024**3+1)
        assert sample(root, current=4*1024**3, cache=2*1024**3)


def test_smaller_container_gets_earlier_reclamation_hint():
    with TemporaryDirectory() as d:
        root = Path(d)
        assert sample(root, limit=2*1024**3, current=600*1024**2)
        assert not sample(root, limit=2*1024**3, current=500*1024**2)
        # Kernel counters need not update atomically.
        assert not sample(root, current=500, cache=1000)


def test_missing_unlimited_or_malformed_cgroup_retains_normal_browser_policy():
    with TemporaryDirectory() as d:
        root = Path(d)
        assert not r.pressure(root)
        for limit in ('max', 'invalid', 0):
            assert not sample(root, limit=limit, current=2*1024**3)
        sample(root)
        (root/'memory.stat').write_text('unrelated 0\n')
        assert not r.pressure(root)
