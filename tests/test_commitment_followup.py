"""Consequential lifecycle, source, migration and delivery regressions."""
import json
import sqlite3
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from radhouse.chat.commitment_review import CommitmentReview
from radhouse.chat.push import PushBinding, PushOutbox, PushResult
from radhouse.domain.tasks import Rejected
from tests.test_commitment_review import pilot, message, suggestion, web_pilot, worker  # noqa: F401

DAY = 86400


def activate(pilot):
    review, chat, clock, _ = pilot
    source = message(chat, clock)
    claim = review.claim()
    review.complete(claim['review_id'], suggestion(source))
    item = review.status()['suggestions'][0]
    review.decide(item['id'], 'confirmed_followup')
    return review.item(item['id'])


def claim_followup(review):
    claim = review.claim()
    if claim.get('prompt') and 'BEGIN CONVERSATION EVIDENCE' in claim['prompt']:
        review.complete(claim['review_id'], '{"suggestions":[]}')
        claim = review.claim()
    assert claim['status'] == 'claimed'
    snapshot = json.loads(claim['prompt'].split('BEGIN BOUNDED EVIDENCE\n')[1].split('\nEND BOUNDED EVIDENCE')[0])
    return claim, snapshot


def output(snapshot, action='quiet', **changes):
    return json.dumps({'followups': [dict(commitment_id=item['id'], action=action,
        source_request_id=item['source_request_id'] if action != 'quiet' else '',
        quote=item['quote'] if action != 'quiet' else '',
        reason='A useful check on your saved intention.' if action != 'quiet' else '',
        preparation='Is the draft ready? Review the opening paragraph next.' if action != 'quiet' else '',
        **changes) for item in snapshot['followups']]})


def finish(review, action='quiet'):
    claim, snapshot = claim_followup(review)
    result = review.complete(claim['review_id'], output(snapshot, action))
    return result, snapshot


def test_confirmed_commitment_continues_after_source_window_and_restart(pilot):
    review, chat, clock, _ = pilot
    item = activate(pilot)
    result, _ = finish(review, 'update')
    assert result == {'status': 'ready'}
    assert review.notification_items() == []  # Initial preparation is private.
    clock[0] += 8 * DAY
    restarted = CommitmentReview(review.path, chat, 'owner', lambda *_: True, clock=lambda: clock[0])
    claim, snapshot = claim_followup(restarted)
    assert snapshot['exchanges'] == []
    assert snapshot['followups'][0]['quote'] == item['quote']
    assert restarted.complete(claim['review_id'], output(snapshot, 'check_in')) == {'status': 'ready'}
    assert restarted.item(item['id'])['state'] == 'confirmed'
    assert restarted.item(item['id'])['followup']['state'] == 'active'


def test_legacy_confirmation_never_silently_starts_tracking(pilot):
    review, chat, clock, _ = pilot
    source = message(chat, clock)
    claim = review.claim()
    review.complete(claim['review_id'], suggestion(source))
    identifier = review.status()['suggestions'][0]['id']
    review.decide(identifier, 'confirmed')
    assert review.item(identifier)['followup'] is None
    review.set_active('conversation', 1, False)
    review.set_active('conversation', 1, True)
    review.decide(identifier, 'confirmed_followup')
    first = review.item(identifier)['followup']
    review.decide(identifier, 'confirmed_followup')
    assert review.item(identifier)['followup'] == first


@pytest.mark.parametrize('action,extra', [('progress', {'progress': 'The introduction is finished.'}),
    ('snooze', {'days': 3}), ('complete', {}), ('stop', {})])
def test_owner_edit_invalidates_inflight_followup(pilot, action, extra):
    review, _, _, _ = pilot
    item = activate(pilot)
    claim, snapshot = claim_followup(review)
    review.followup_action(item['id'], {'action': action, 'revision': 1, **extra})
    assert review.complete(claim['review_id'], output(snapshot, 'update')) == {'status': 'stale'}
    assert review.item(item['id'])['followup']['latest_note'] is None
    with pytest.raises(Rejected, match='followup_changed'):
        review.followup_action(item['id'], {'action': action, 'revision': 1, **extra})


def test_snooze_blocks_reviews_and_resume_keeps_ongoing_tracking(pilot):
    review, _, clock, _ = pilot
    item = activate(pilot)
    review.followup_action(item['id'], {'action': 'snooze', 'revision': 1, 'days': 3})
    assert review.claim() == {'status': 'unchanged'}
    clock[0] += 2 * DAY
    assert review.claim() == {'status': 'unchanged'}
    review.followup_action(item['id'], {'action': 'resume', 'revision': 2})
    _, snapshot = finish(review)
    assert snapshot['followups'][0]['revision'] == 3
    assert not snapshot['followups'][0]['check_in_due']


def test_progress_is_bounded_owner_evidence_and_can_be_cited(pilot):
    review, _, _, _ = pilot
    item = activate(pilot)
    review.followup_action(item['id'], {'action': 'progress', 'revision': 1, 'progress': 'The introduction is finished.'})
    claim, snapshot = claim_followup(review)
    result = json.loads(output(snapshot, 'update'))
    result['followups'][0].update(source_request_id='progress:' + item['id'], quote='introduction is finished')
    assert review.complete(claim['review_id'], json.dumps(result)) == {'status': 'ready'}


@pytest.mark.parametrize('change', ['binding', 'pause', 'revoke', 'new_message'])
def test_followup_rechecks_live_authority_and_source(pilot, change):
    review, chat, clock, allowed = pilot
    item = activate(pilot)
    claim, snapshot = claim_followup(review)
    if change == 'binding':
        review.set_active('other-conversation', 2, True)
        assert review.item(item['id'])['followup']['state'] == 'scope_changed'
    elif change == 'pause':
        review.set_active('conversation', 1, False)
    elif change == 'revoke':
        allowed[0] = False
    else:
        message(chat, clock, 'I have stopped work on that draft.')
    if change == 'new_message':
        assert review.complete(claim['review_id'], output(snapshot)) == {'status': 'stale'}
    else:
        raw = output(snapshot)
        with pytest.raises(Rejected):
            review.complete(claim['review_id'], raw)
    assert review.notification_items() == []


@pytest.mark.parametrize('tamper', ['extra', 'uncited', 'unknown', 'duplicate', 'missing', 'complete', 'early_checkin'])
def test_model_cannot_change_authority_or_skip_batch_members(pilot, tamper):
    review, _, _, _ = pilot
    activate(pilot)
    claim, snapshot = claim_followup(review)
    data = json.loads(output(snapshot, 'update'))
    item = data['followups'][0]
    if tamper == 'extra': item['recipient'] = 'someone else'
    elif tamper == 'uncited': item['quote'] = 'Invented evidence'
    elif tamper == 'unknown': item['commitment_id'] = str(uuid4())
    elif tamper == 'duplicate': data['followups'].append(item)
    elif tamper == 'missing': data['followups'] = []
    elif tamper == 'complete': item['action'] = 'completed'
    else: item['action'] = 'check_in'
    assert review.complete(claim['review_id'], json.dumps(data)) == {'status': 'failed'}
    assert review.status()['last_review']['error'] == 'invalid_commitment_evidence'
    assert review.status()['suggestions'][0]['followup']['state'] == 'active'
    with review.connection() as db:
        assert db.execute('SELECT snapshot FROM reviews WHERE id=?', (claim['review_id'],)).fetchone()[0] == '{}'


def test_quiet_checks_do_not_alert_and_checkins_back_off(pilot):
    review, _, clock, _ = pilot
    item = activate(pilot)
    finish(review)
    assert review.claim() == {'status': 'unchanged'}
    clock[0] += DAY
    finish(review, 'check_in')
    first = review.notification_items()[0]
    assert review.item(item['id'])['followup']['attention_at'] == clock[0] + 3 * DAY
    clock[0] += DAY
    finish(review)
    assert review.notification_items() == []
    clock[0] += 2 * DAY
    finish(review, 'check_in')
    second = review.notification_items()[0]
    assert second['id'] == first['id']
    assert second['event_id'] != first['event_id']
    assert review.item(item['id'])['followup']['attention_at'] == clock[0] + 7 * DAY


def test_distinct_occurrences_deliver_same_item_and_stop_invalidates_queue(pilot, tmp_path):
    review, _, clock, _ = pilot
    item = activate(pilot)
    finish(review)
    outbox = PushOutbox(tmp_path/'push.db', Fernet.generate_key().decode(), clock=lambda: clock[0])
    binding = PushBinding('owner', 'conversation', 1, 'a'*64, clock[0] + 20*DAY)
    outbox.register(str(uuid4()), binding, 'ios', 'synthetic-token-123456789', latest_seq=0, commitments=True)
    clock[0] += DAY
    finish(review, 'check_in')
    first = review.notification_items()[0]
    outbox.enqueue_commitments('owner', review.notification_items())
    sent = []
    def send(_token, _platform, data):
        sent.append(data)
        return PushResult('sent')
    assert outbox.dispatch_one(lambda _: True, send, commitment_decision=review.notification_decision)
    assert sent[0]['event_id'] == first['event_id']
    assert sent[0]['item_id'] == item['id']
    clock[0] += 3 * DAY
    finish(review, 'check_in')
    outbox.enqueue_commitments('owner', review.notification_items())
    review.followup_action(item['id'], {'action': 'complete', 'revision': 1})
    assert outbox.dispatch_one(lambda _: True, send, commitment_decision=review.notification_decision)
    assert len(sent) == 1
    assert review.notification_items() == [] or all(review.notification_decision(i['id'], event_id=i.get('event_id')) == 'discard' for i in review.notification_items())


def test_discovery_and_followup_share_budget_and_failure_is_visible(pilot):
    review, chat, clock, _ = pilot
    item = activate(pilot)
    for _ in range(3):
        claim, _ = claim_followup(review)
        assert review.complete(claim['review_id'], '', failed=True) == {'status': 'failed'}
    message(chat, clock, 'Another intention to review.')
    assert review.claim() == {'status': 'budget_wait'}
    assert review.item(item['id'])['followup']['last_review_at'] is None


def test_schema_one_migrates_without_auto_starting_old_confirmations(tmp_path):
    from radhouse.chat.store import ChatStore
    path = tmp_path/'old.db'
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE mandate(id INTEGER PRIMARY KEY,owner TEXT,conversation TEXT,binding_revision INTEGER,epoch INTEGER,active INTEGER,created_at REAL);
        CREATE TABLE suggestions(id TEXT PRIMARY KEY,source_request_id TEXT,quote TEXT,title TEXT,reason TEXT,preparation TEXT,state TEXT,created_at REAL,reviewed_at REAL,epoch INTEGER,input_hash TEXT);
        CREATE TABLE reviews(id TEXT PRIMARY KEY,epoch INTEGER,input_hash TEXT,snapshot TEXT,created_at REAL,expires_at REAL,state TEXT,error TEXT,result_hash TEXT);
        CREATE TABLE coverage(id INTEGER PRIMARY KEY,checked_at REAL,outcome TEXT);
        INSERT INTO mandate VALUES(1,'owner','conversation',1,1,1,1);
        INSERT INTO suggestions VALUES('saved','source','quote','title','reason','prep','confirmed',1,1,1,'hash');
        PRAGMA user_version=1;''')
    db.close(); path.chmod(0o600)
    review = CommitmentReview(path, ChatStore(tmp_path/'chat.db'), 'owner', lambda *_: True)
    assert review.item('saved')['followup'] is None
    assert review.item('saved')['conversation'] == 'conversation'
    with review.connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2


def test_authenticated_route_accepts_lifecycle_but_worker_bearer_cannot_decide(web_pilot):
    client, review, bearer, _ = web_pilot
    # Worker authority is separate from an owner session.
    response = client.post('/chat/responsibilities/commitments/'+str(uuid4()),
        headers={'Authorization': 'Bearer '+bearer}, json={'action': 'complete', 'revision': 1})
    assert response.status_code in {401,403}


def test_oversized_evidence_fails_visibly_without_claiming_coverage(pilot, monkeypatch):
    from radhouse.chat import commitment_followup
    review, _, _, _ = pilot
    item = activate(pilot)
    monkeypatch.setattr(commitment_followup, 'prompt', lambda _: 'x' * 60000)
    assert review.claim() == {'status': 'failed'}
    status = review.status()
    assert status['last_review']['error'] == 'review_evidence_too_large'
    assert status['coverage']['outcome'] == 'failed'
    assert review.item(item['id'])['followup']['last_review_at'] is None
    with review.connection() as db:
        assert db.execute("SELECT snapshot FROM reviews WHERE kind='followup'").fetchone()[0] == '{}'


def test_repeated_old_evidence_update_is_private_and_does_not_nag(pilot):
    review, _, clock, _ = pilot
    activate(pilot)
    finish(review, 'update')
    clock[0] += DAY
    finish(review, 'update')
    assert review.notification_items() == []


def test_fresh_cited_progress_can_prompt_completion_without_completing(pilot):
    review, chat, clock, _ = pilot
    item = activate(pilot)
    finish(review)
    clock[0] += DAY / 4 + 1
    source = message(chat, clock, 'The draft is finished.')
    claim, snapshot = claim_followup(review)
    data = json.loads(output(snapshot, 'completion_check'))
    data['followups'][0].update(source_request_id=source, quote='draft is finished')
    assert review.complete(claim['review_id'], json.dumps(data)) == {'status': 'ready'}
    assert review.item(item['id'])['followup']['state'] == 'active'
    assert review.notification_items()[0]['id'] == item['id']


def test_pause_resume_cannot_revive_queued_followup(pilot):
    review, _, clock, _ = pilot
    activate(pilot); finish(review)
    clock[0] += DAY
    finish(review, 'check_in')
    notice = review.notification_items()[0]
    review.set_active('conversation', 1, False)
    review.set_active('conversation', 1, True)
    assert review.notification_decision(notice['id'], event_id=notice['event_id']) == 'discard'
    assert review.notification_items() == []


def test_lifecycle_routes_enforce_csrf_revision_and_maintenance(web_pilot, pilot, monkeypatch):
    from contextlib import contextmanager
    client, headers, _, service = web_pilot
    review, _, _, _ = pilot
    item = activate(pilot)
    path = '/chat/responsibilities/commitments/' + item['id']
    body = {'action': 'snooze', 'revision': 1, 'days': 3}
    assert client.post(path, headers={'authorization': 'synthetic-session'}, json=body).status_code == 403
    assert client.post(path, headers=headers, json=body).status_code == 200
    assert client.post(path, headers=headers, json=body).status_code == 409
    @contextmanager
    def held():
        raise Rejected('assistant_maintenance', 503)
        yield  # pragma: no cover
    monkeypatch.setattr(service.dispatch_gate, 'admission', held)
    assert client.post(path, headers=headers, json={'action': 'complete', 'revision': 2}).status_code == 503
    assert client.post('/chat/responsibilities/commitments', headers=headers, json={'active': False}).status_code == 503
    assert review.item(item['id'])['followup']['state'] == 'snoozed'


def test_native_worker_uses_same_callback_for_followup_without_user_turn(web_pilot, pilot, worker):
    import httpx
    client, _, bearer, _ = web_pilot
    review, chat, _, _ = pilot
    item = activate(pilot)
    with chat.connection() as db:
        before = db.execute('SELECT count(*) FROM turns').fetchone()[0]
    def transport(request):
        response = client.request(request.method, request.url.path, content=request.content,
            headers={'authorization': request.headers['authorization'], 'content-type': 'application/json'})
        return httpx.Response(response.status_code, json=response.json())
    def infer(prompt, _):
        snapshot = json.loads(prompt.split('BEGIN BOUNDED EVIDENCE\n')[1].split('\nEND BOUNDED EVIDENCE')[0])
        return output(snapshot, 'update')
    assert worker.run_once({'endpoint': 'https://fixture.test', 'worker_bearer': bearer},
        infer=infer, transport=httpx.MockTransport(transport)) == 'ready'
    assert review.item(item['id'])['followup']['last_review_at'] is not None
    with chat.connection() as db:
        assert db.execute('SELECT count(*) FROM turns').fetchone()[0] == before
