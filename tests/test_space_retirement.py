import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('space_retirement', Path(__file__).parents[1] / 'runtime/selkies/space_retirement.py')
retirement = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retirement)
SID = 'sbx_11111111-1111-4111-8111-111111111111'
OP = 'op_22222222-2222-4222-8222-222222222222'
BOOT = '33333333-3333-4333-8333-333333333333'
CURRENT = {'sandbox_id': SID, 'boot_id': '44444444-4444-4444-8444-444444444444'}


def test_retire_observes_acknowledged_operation_without_replaying(tmp_path):
    calls = []
    responses = iter([{'id': SID, 'state': 'running'}, {'sandbox_id': SID, 'operation_id': OP},
                      {'id': OP, 'target_type': 'sandbox', 'target_id': SID, 'kind': 'delete_sandbox', 'state': 'running'},
                      {'id': OP, 'target_type': 'sandbox', 'target_id': SID, 'kind': 'delete_sandbox', 'state': 'succeeded'}, None, None])

    def call(root, method, path, **kwargs):
        calls.append(method)
        return next(responses)

    receipt = retirement.retire(tmp_path, CURRENT, BOOT, call=call, sleep=lambda _: None)
    assert receipt['state'] == 'retired'
    assert retirement.retire(tmp_path, CURRENT, BOOT, call=call) == receipt
    assert calls.count('DELETE') == 1
    assert (tmp_path / ('retirement-' + BOOT + '.json')).stat().st_mode & 0o777 == 0o600


def test_lost_ack_is_not_retried(tmp_path):
    def call(root, method, path, **kwargs):
        if method == 'DELETE':
            raise TimeoutError
        return {'id': SID}

    with pytest.raises(TimeoutError):
        retirement.retire(tmp_path, CURRENT, BOOT, call=call)
    with pytest.raises(ValueError, match='outcome_unknown'):
        retirement.retire(tmp_path, CURRENT, BOOT, call=call)


@pytest.mark.parametrize('change', [{'sandbox_id': 'sbx_other'}, {'boot_id': CURRENT['boot_id']}])
def test_refuses_wrong_identity_or_same_boot(tmp_path, change):
    current, boot = {**CURRENT, **{k: v for k, v in change.items() if k == 'sandbox_id'}}, change.get('boot_id', BOOT)
    with pytest.raises(ValueError, match='new_boot'):
        retirement.retire(tmp_path, current, boot, call=lambda *a, **k: pytest.fail('no call'))


def test_rejects_foreign_operation_and_does_not_replay(tmp_path):
    replies = iter([{'id': SID}, {'sandbox_id': SID, 'operation_id': OP},
                    {'id': OP, 'target_type': 'sandbox', 'target_id': 'other', 'kind': 'delete_sandbox', 'state': 'succeeded'}])
    with pytest.raises(ValueError, match='operation_mismatch'):
        retirement.retire(tmp_path, CURRENT, BOOT, call=lambda *a, **k: next(replies))
    receipt = json.loads((tmp_path / ('retirement-' + BOOT + '.json')).read_text())
    assert receipt['state'] == 'accepted'


def accepted_receipt(tmp_path):
    path = tmp_path / ('retirement-' + BOOT + '.json')
    retirement.save(path, {'state': 'accepted', 'sandbox_id': SID, 'boot_id': BOOT,
                          'prior_boot_id': CURRENT['boot_id'], 'operation_id': OP})
    return path


def test_pending_operation_can_resume_without_a_second_delete(tmp_path):
    path = accepted_receipt(tmp_path)
    operation = {'id': OP, 'target_type': 'sandbox', 'target_id': SID, 'kind': 'delete_sandbox'}
    calls = []

    def call(root, method, url, **kwargs):
        calls.append((method, url))
        return {**operation, 'state': 'running'}

    with pytest.raises(ValueError, match='still_pending'):
        retirement.retire(tmp_path, CURRENT, BOOT, call=call, sleep=lambda _: None)
    assert json.loads(path.read_text())['state'] == 'accepted'
    replies = iter([{**operation, 'state': 'succeeded'}, None])
    result = retirement.retire(tmp_path, CURRENT, BOOT, call=lambda *a, **k: next(replies))
    assert result['state'] == 'retired'
    assert all(method == 'GET' for method, _ in calls)


@pytest.mark.parametrize('tamper', ['readable', 'symlink'])
def test_refuses_untrusted_receipt_before_any_lifecycle_request(tmp_path, tamper):
    path = accepted_receipt(tmp_path)
    if tamper == 'readable':
        path.chmod(0o644)
    else:
        target = path.with_suffix('.target')
        path.rename(target)
        path.symlink_to(target)
    with pytest.raises((ValueError, OSError)):
        retirement.retire(tmp_path, CURRENT, BOOT, call=lambda *a, **k: pytest.fail('no request'))


def test_operation_success_requires_confirmed_guest_absence(tmp_path):
    path = accepted_receipt(tmp_path)
    replies = iter([{'id': OP, 'target_type': 'sandbox', 'target_id': SID,
                     'kind': 'delete_sandbox', 'state': 'succeeded'}, {'id': SID}])
    with pytest.raises(ValueError, match='not_confirmed'):
        retirement.retire(tmp_path, CURRENT, BOOT, call=lambda *a, **k: next(replies))
    assert json.loads(path.read_text())['state'] == 'accepted'
