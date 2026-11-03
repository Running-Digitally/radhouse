import hashlib
import json

import pytest

from scripts.space_startup_manifest import reconcile


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def staged(tmp_path):
    (tmp_path / 'recovery.py').write_bytes(b'new release')
    (tmp_path / 'gateway.py').write_bytes(b'unchanged')
    manifest = json.dumps({'sources': {'recovery.py': sha(b'old release'), 'gateway.py': sha(b'unchanged')},
                           'containers': {}, 'external_sources': {}}).encode()
    (tmp_path / 'startup-manifest.json').write_bytes(manifest)
    approval = {'manifest_sha256': sha(manifest), 'files': {
        'recovery.py': {'before': sha(b'old release'), 'after': sha(b'new release')}}}
    return tmp_path, approval, manifest


def test_release_reconciles_full_closure_and_retains_preimage(staged):
    root, approval, original = staged
    expected = reconcile(root, approval)
    assert (root / 'startup-manifest.json').read_bytes() == original
    result = reconcile(root, approval, apply=True)
    assert result['sha256'] == expected['sha256'] == sha((root / 'startup-manifest.json').read_bytes())
    assert (root / ('startup-manifest.before-' + approval['manifest_sha256'] + '.json')).read_bytes() == original
    with pytest.raises(ValueError, match='manifest_changed'):
        reconcile(root, approval, apply=True)


@pytest.mark.parametrize('name', ['recovery.py', 'gateway.py'])
def test_unreviewed_source_drift_does_not_change_manifest(staged, name):
    root, approval, original = staged
    (root / name).write_bytes(b'unexpected source')
    with pytest.raises(ValueError):
        reconcile(root, approval, apply=True)
    assert (root / 'startup-manifest.json').read_bytes() == original


def test_external_dependency_is_checked(staged):
    root, approval, _ = staged
    manifest = json.loads((root / 'startup-manifest.json').read_text())
    dependency = root / 'dependency.py'
    dependency.write_bytes(b'drift')
    manifest['external_sources'][str(dependency)] = sha(b'expected')
    raw = json.dumps(manifest).encode()
    (root / 'startup-manifest.json').write_bytes(raw)
    approval['manifest_sha256'] = sha(raw)
    with pytest.raises(ValueError, match='dependency_changed'):
        reconcile(root, approval, apply=True)
