"""Retire a prior-boot SPACE guest once, before cold template replacement.

No browser operation is replayed. An acknowledged lifecycle operation may be
observed again; a lost mutation acknowledgement requires operator reconciliation.
The caller stops the fixed gateway and verifies its pinned startup source first.
"""
import json
import os
from pathlib import Path
import re
import stat
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4


API = 'http://127.0.0.1:18080'
UUID = r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def private_json(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW)) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError('private_retirement_receipt_required')
        return json.loads(stream.read(65537))


def save(path, value):
    temporary = path.with_suffix('.new')
    with temporary.open('x') as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def request(root, method, path, *, key=None, opener=None):
    if opener is None:
        opener = build_opener(ProxyHandler({}), NoRedirect()).open
    headers = {'Authorization': 'Bearer ' + (root / 'space-api-credential').read_text().strip()}
    if key:
        headers['Idempotency-Key'] = key
    req = Request(API + path, method=method, headers=headers)
    try:
        with opener(req, timeout=20) as response:
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError('retirement_response_too_large')
            return json.loads(raw)
    except HTTPError as error:
        if method == 'GET' and error.code == 404:
            return None
        raise


def retire(root, current, boot, *, call=request, sleep=time.sleep):
    root = Path(root)
    sid = current['sandbox_id']
    if (not re.fullmatch('sbx_' + UUID, sid)
            or not re.fullmatch(UUID, boot) or not re.fullmatch(UUID, current['boot_id'])
            or boot == current['boot_id']):
        raise ValueError('cold_retirement_requires_new_boot')
    path = root / ('retirement-' + boot + '.json')
    if path.exists():
        receipt = private_json(path)
        if (receipt.get('sandbox_id') != sid or receipt.get('boot_id') != boot
                or receipt.get('prior_boot_id') != current['boot_id']):
            raise ValueError('retirement_identity_changed')
        if receipt.get('state') == 'retired':
            if call(root, 'GET', '/v1/sandboxes/' + sid) is not None:
                raise ValueError('retirement_no_longer_confirmed')
            return receipt
        if receipt.get('state') != 'accepted' or not re.fullmatch('op_' + UUID, str(receipt.get('operation_id'))):
            raise ValueError('retirement_outcome_unknown')
    else:
        observed = call(root, 'GET', '/v1/sandboxes/' + sid)
        if not isinstance(observed, dict) or observed.get('id') != sid:
            raise ValueError('prior_sandbox_unconfirmed')
        receipt = {'state': 'intent', 'sandbox_id': sid, 'boot_id': boot,
                   'prior_boot_id': current['boot_id'], 'key': 'radhouse-cold-retire-' + uuid4().hex}
        save(path, receipt)
        accepted = call(root, 'DELETE', '/v1/sandboxes/' + sid, key=receipt['key'])
        if (not isinstance(accepted, dict) or accepted.get('sandbox_id') != sid
                or not re.fullmatch('op_' + UUID, str(accepted.get('operation_id')))):
            raise ValueError('retirement_outcome_unknown')
        receipt.update(state='accepted', operation_id=accepted['operation_id'])
        save(path, receipt)
    for _ in range(60):
        operation = call(root, 'GET', '/v1/operations/' + receipt['operation_id'])
        if (not isinstance(operation, dict) or operation.get('id') != receipt['operation_id']
                or operation.get('target_type') != 'sandbox' or operation.get('target_id') != sid
                or operation.get('kind') != 'delete_sandbox'):
            raise ValueError('retirement_operation_mismatch')
        state = operation.get('state')
        if state == 'succeeded':
            if call(root, 'GET', '/v1/sandboxes/' + sid) is not None:
                raise ValueError('retirement_not_confirmed')
            receipt['state'] = 'retired'
            save(path, receipt)
            return receipt
        if state not in {'queued', 'running'}:
            raise ValueError('retirement_failed')
        sleep(1)
    raise ValueError('retirement_still_pending')
