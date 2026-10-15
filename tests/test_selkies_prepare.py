import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pytest

spec = importlib.util.spec_from_file_location('review_prepare', Path(__file__).parents[1]/'runtime/selkies/prepare.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def fixture(root):
    variant = root/'native-page-only-lock.json'
    variant.write_text('{}')
    lock = {'native_variant':'page_only', 'native_binary_sha256':'frozen-native',
            'native_variant_lock_sha256':p.sha(variant)}
    receipt = root/'native-page-only-build.json'
    receipt.write_text(json.dumps({'native_binary_sha256':'frozen-native',
        'variant_source_lock_sha256':lock['native_variant_lock_sha256']}))
    lock['native_variant_build_receipt_sha256'] = p.sha(receipt)
    return lock


def test_build_receipt_and_source_lock_name_the_same_native_artifact():
    with TemporaryDirectory() as d:
        root = Path(d)
        lock = fixture(root)
        with patch.object(p, 'HERE', root):
            p.verify_native_provenance(lock)
            lock['native_binary_sha256'] = 'different-native'
            with pytest.raises(ValueError, match='native_provenance_mismatch'):
                p.verify_native_provenance(lock)


def test_corrupted_provenance_aborts_before_creating_build_context():
    with TemporaryDirectory() as d:
        root = Path(d)
        lock = fixture(root)
        archive, native = root/'source.tar', root/'native'
        archive.write_bytes(b'dummy archive')
        native.write_bytes(b'dummy native')
        lock.update(selkies_archive_sha256=p.sha(archive), native_binary_sha256=p.sha(native))
        (root/'source-lock.json').write_text(json.dumps(lock))
        (root/'native-page-only-build.json').write_text('corrupted')
        with patch.object(p, 'HERE', root), pytest.raises(ValueError, match='native_provenance_mismatch'):
            p.prepare(archive, native, root/'unused-chrome.tar', root/'output')
        assert not (root/'output').exists()
