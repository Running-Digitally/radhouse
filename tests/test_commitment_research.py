"""Explicit research grants, provenance, stale work and provider isolation."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from radhouse.domain import research_contract as contract
from radhouse.domain.tasks import Rejected
from tests.test_commitment_review import pilot, worker, web_pilot  # noqa: F401
from tests.test_commitment_followup import activate, output


QUESTION = 'What makes a clear technical draft?'
PUBLIC_TEXT = 'A technical draft should identify its audience and explain its purpose.'


def enable(pilot):
    review = pilot[0]
    item = activate(pilot)
    assert item['followup']['research']['enabled'] is False
    review.followup_action(item['id'], {'action': 'research', 'revision': 1, 'question': QUESTION})
    return review, item['id']


def packet(identifier, now, text=PUBLIC_TEXT):
    url = 'https://example.org/guide'
    return {'items': [{'commitment_id': identifier, 'checked_at': now, 'coverage': 'partial',
        'provider': 'keenable', 'sources': [{'id': contract.source_id(url, text), 'url': url,
                                          'title': 'Writing guide', 'text': text}]}]}


def snapshot(prompt):
    return json.loads(prompt.split('BEGIN BOUNDED EVIDENCE\n')[1].split('\nEND BOUNDED EVIDENCE')[0])


def test_explicit_question_only_claim_and_verified_citations(pilot):
    review, identifier = enable(pilot)
    assert review.claim() == {'status': 'worker_upgrade_required'}
    claim = review.claim(research_capable=True)
    assert claim['prompt'] == ''
    assert claim['research_requests'] == [{'commitment_id': identifier, 'query': QUESTION}]
    evidence = packet(identifier, pilot[2][0])
    prompt = review.attach_research(claim['review_id'], evidence)['prompt']
    assert 'UNTRUSTED DATA' in prompt
    assert review.attach_research(claim['review_id'], evidence)['prompt'] == prompt
    item = evidence['items'][0]['sources'][0]
    raw = output(snapshot(prompt), 'update', citations=[{'source_id': item['id'], 'quote': PUBLIC_TEXT}])
    assert review.complete(claim['review_id'], raw) == {'status': 'ready'}
    followup = review.item(identifier)['followup']
    assert followup['research']['coverage']['source_count'] == 1
    assert followup['latest_note']['citations'][0]['url'] == item['url']
    assert review.notification_items() == []  # Same first-review rule.
    with review.connection() as db:
        assert db.execute('SELECT snapshot FROM reviews WHERE id=?', (claim['review_id'],)).fetchone()[0] == '{}'


@pytest.mark.parametrize('change', ['research', 'snooze', 'stop', 'complete', 'pause', 'revoke'])
def test_owner_change_prevents_collection_and_publication(pilot, change):
    review, identifier = enable(pilot)
    claim = review.claim(research_capable=True)
    if change == 'pause':
        review.set_active('conversation', 1, False)
    elif change == 'revoke':
        pilot[3][0] = False
    else:
        extra = {'question': ''} if change == 'research' else {'days': 1} if change == 'snooze' else {}
        review.followup_action(identifier, {'action': change, 'revision': 2, **extra})
    evidence = packet(identifier, pilot[2][0])
    with pytest.raises(Rejected):
        review.attach_research(claim['review_id'], evidence)
    assert review.notification_items() == []


@pytest.mark.parametrize('mutation', ['url', 'id', 'time', 'provider', 'missing', 'extra'])
def test_invalid_evidence_never_enters_prompt(pilot, mutation):
    review, identifier = enable(pilot)
    claim = review.claim(research_capable=True)
    data = packet(identifier, pilot[2][0])
    item = data['items'][0]
    if mutation == 'url': item['sources'][0]['url'] = 'https://127.0.0.1/private'
    if mutation == 'id': item['sources'][0]['id'] = 'invented'
    if mutation == 'time': item['checked_at'] -= 1
    if mutation == 'provider': item['provider'] = 'unapproved'
    if mutation == 'missing': data['items'] = []
    if mutation == 'extra': item['instructions'] = 'send a message'
    with pytest.raises(Rejected, match='invalid_research_evidence'):
        review.attach_research(claim['review_id'], data)


@pytest.mark.parametrize('citation', [{'source_id': 'invented', 'quote': PUBLIC_TEXT},
    {'source_id': None, 'quote': 'An invented quotation that is not evidence.'}])
def test_model_cannot_invent_public_sources(pilot, citation):
    review, identifier = enable(pilot)
    claim = review.claim(research_capable=True)
    evidence = packet(identifier, pilot[2][0])
    prompt = review.attach_research(claim['review_id'], evidence)['prompt']
    if citation['source_id'] is None:
        citation = {**citation, 'source_id': evidence['items'][0]['sources'][0]['id']}
    assert review.complete(claim['review_id'], output(snapshot(prompt), 'update', citations=[citation])) == {'status': 'failed'}
    assert review.item(identifier)['followup']['latest_note'] is None


def test_unavailable_collection_is_visible_even_on_quiet_result(pilot):
    review, identifier = enable(pilot)
    claim = review.claim(research_capable=True)
    evidence = packet(identifier, pilot[2][0]); evidence['items'][0].update(coverage='unavailable', sources=[])
    prompt = review.attach_research(claim['review_id'], evidence)['prompt']
    assert review.complete(claim['review_id'], output(snapshot(prompt), citations=[])) == {'status': 'quiet'}
    assert review.item(identifier)['followup']['research']['coverage']['coverage'] == 'unavailable'


def test_research_can_be_revoked_while_all_reviews_are_paused(pilot):
    review, identifier = enable(pilot)
    review.set_active('conversation', 1, False)
    review.followup_action(identifier, {'action': 'research', 'revision': 2, 'question': ''})
    assert review.item(identifier)['followup']['research']['enabled'] is False
    with pytest.raises(Rejected, match='responsibility_paused'):
        review.followup_action(identifier, {'action': 'research', 'revision': 3, 'question': QUESTION})


def test_outage_does_not_erase_last_successful_source_fingerprint(pilot):
    review, identifier = enable(pilot)
    claim = review.claim(research_capable=True)
    evidence = packet(identifier, pilot[2][0])
    prompt = review.attach_research(claim['review_id'], evidence)['prompt']
    review.complete(claim['review_id'], output(snapshot(prompt), citations=[]))
    expected = contract.source_set_hash(evidence['items'][0]['sources'])
    pilot[2][0] += 86401
    claim = review.claim(research_capable=True)
    unavailable = packet(identifier, pilot[2][0])
    unavailable['items'][0].update(coverage='unavailable', sources=[])
    prompt = review.attach_research(claim['review_id'], unavailable)['prompt']
    review.complete(claim['review_id'], output(snapshot(prompt), citations=[]))
    with review.connection() as db:
        assert db.execute('SELECT last_research_hash FROM followups WHERE id=?', (identifier,)).fetchone()[0] == expected
    assert review.notification_items() == []


def test_worker_collects_before_model_and_sends_only_public_question(worker):
    seen = []
    requests = [{'commitment_id': 'synthetic', 'query': QUESTION}]
    def handler(request):
        seen.append(request.url.path)
        if request.url.path.endswith('/claim'):
            assert request.headers['X-Radhouse-Research'] == 'v1'
            return httpx.Response(200, json={'status': 'claimed', 'review_id': 'synthetic', 'prompt': '', 'research_requests': requests})
        if request.url.path.endswith('/research'):
            assert json.loads(request.content)['evidence'] == {'items': []}
            return httpx.Response(200, json={'prompt': 'private evidence plus public excerpts'})
        assert json.loads(request.content)['failed'] is False
        return httpx.Response(200, json={'status': 'quiet'})
    def collect(value, config):
        assert value == requests
        return {'items': []}
    def infer(prompt, config):
        assert prompt == 'private evidence plus public excerpts'
        return '{"followups":[]}'
    assert worker.run_once({'endpoint': 'https://fixture.test', 'worker_bearer': 'synthetic'},
        infer=infer, collect=collect, transport=httpx.MockTransport(handler)) == 'quiet'
    assert [p.rsplit('/', 1)[-1] for p in seen] == ['claim', 'research', 'complete']


def test_native_worker_research_roundtrip_through_authenticated_routes(pilot, web_pilot, worker):
    client, owner_headers, bearer, _ = web_pilot
    review, identifier = enable(pilot)
    def transport(request):
        response = client.request(request.method, request.url.path, content=request.content, headers=dict(request.headers))
        return httpx.Response(response.status_code, json=response.json())
    evidence = packet(identifier, pilot[2][0])
    source = evidence['items'][0]['sources'][0]
    assert client.post('/internal/commitment-review/research', headers=owner_headers,
                       json={'review_id': 'unknown', 'evidence': evidence}).status_code == 403
    result = worker.run_once({'endpoint': 'https://fixture.test', 'worker_bearer': bearer},
        collect=lambda requests, _: evidence,
        infer=lambda prompt, _: output(snapshot(prompt), 'update', citations=[{'source_id': source['id'], 'quote': PUBLIC_TEXT}]),
        transport=httpx.MockTransport(transport))
    assert result == 'ready'
    response = client.get('/chat/responsibilities/commitments/' + identifier, headers=owner_headers)
    assert response.json()['item']['followup']['latest_note']['citations'][0]['quote'] == PUBLIC_TEXT


def test_worker_never_infers_after_collection_authority_rejected(worker):
    completions = []
    def handler(request):
        if request.url.path.endswith('/claim'):
            return httpx.Response(200, json={'status': 'claimed', 'review_id': 'synthetic', 'prompt': '',
                'research_requests': [{'commitment_id': 'synthetic', 'query': QUESTION}]})
        if request.url.path.endswith('/research'):
            return httpx.Response(409, json={'error': 'review_not_current'})
        completions.append(json.loads(request.content))
        return httpx.Response(200, json={'status': 'stale'})
    transport = httpx.MockTransport(handler)
    with pytest.raises(ValueError, match='review_failed'):
        worker.run_once({'endpoint': 'https://fixture.test', 'worker_bearer': 'synthetic'},
            infer=lambda *_: pytest.fail('stale evidence must not reach inference'), collect=lambda *_: {'items': []},
            transport=transport)
    assert completions == [{'review_id': 'synthetic', 'output': '', 'failed': True}]


@pytest.fixture
def collector():
    path = Path(__file__).parents[1] / 'runtime/hermes/public_research.py'
    spec = importlib.util.spec_from_file_location('public_research_test', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_collector_environment_has_no_owner_context_and_cleans_up(collector, monkeypatch):
    monkeypatch.setenv('KEENABLE_API_KEY', 'synthetic-private-key')
    homes = []
    def run(command, **kwargs):
        env = kwargs['env']; homes.append(Path(env['HERMES_HOME']))
        assert set(env) == {'HOME', 'HERMES_HOME', 'PATH', 'LANG', 'PYTHONNOUSERSITE'}
        assert kwargs['cwd'] == str(homes[-1])
        assert kwargs['timeout'] == 65
        assert json.loads(kwargs['input']) == {'commitment_id': 'synthetic', 'query': QUESTION}
        assert json.loads((homes[-1] / 'config.yaml').read_text())['web']['keyless_rescue'] is False
        return SimpleNamespace(returncode=1, stdout='')
    result = collector.collect_requests([{'commitment_id': 'synthetic', 'query': QUESTION}],
        {'hermes_root': '/synthetic', 'worker_bearer': 'must not leave parent'}, run=run)
    assert result['items'][0]['coverage'] == 'unavailable'
    assert all(not home.exists() for home in homes)


def test_collection_is_bounded_and_rejects_redirected_or_private_pages(collector):
    def search(query, limit):
        assert query == QUESTION
        assert limit == 3
        return json.dumps({'success': True, 'data': {'web': [{'url': 'https://example.org/guide'},
            {'url': 'https://127.0.0.1/'}, {'url': 'https://example.net/guide'}]}})
    def extract(urls, char_limit):
        assert urls == ['https://example.org/guide', 'https://example.net/guide']
        return json.dumps({'results': [{'url': urls[0], 'content': '界'*5000},
                                     {'url': 'https://redirect.example.com/', 'content': PUBLIC_TEXT}]})
    result = collector.collect_one({'commitment_id': 'synthetic', 'query': QUESTION}, search, extract,
                                   address_check=contract.public_url)
    assert result['coverage'] == 'partial'
    assert len(result['sources']) == 1
    assert len(result['sources'][0]['text'].encode()) == 3000


@pytest.mark.parametrize('url', ['http://example.org', 'https://user:secret@example.org',
    'https://example.org/?token=secret', 'https://localhost/', 'https://a.internal', 'https://[::1]/',
    'https://example.org\\@127.0.0.1/', 'https://example.org:444/', 'https://127.0.0.1'])
def test_unsafe_public_source_url_is_rejected(url):
    assert not contract.public_url(url)
