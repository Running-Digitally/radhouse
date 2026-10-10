from dataclasses import asdict, replace
from threading import Event
from types import SimpleNamespace
import json

from fastapi.testclient import TestClient
import pytest

from radhouse.api.app import create_app
from radhouse.application.coordinator import Coordinator
from radhouse.application.controller_loops import ControllerLoops
from radhouse.application.work_service import WorkService
from radhouse.channels.buzz_conversations import BuzzConversationCycle
from radhouse.channels.project_buzz import ProjectBuzzConversationCycle
from radhouse.domain.tasks import Rejected
from radhouse.domain.conversations import ConversationMessage
from psycopg.types.json import Jsonb
from tests.test_buzz_conversations import bridge, incoming
from tests.test_work_commands import command
from tests.test_work_lifecycle import result

pytestmark = pytest.mark.postgres


@pytest.fixture
def work_bridge(bridge, service, store):
    cycle, state, owner = bridge
    service.durable_work_enabled = True
    # Fixture enrollment is replaced before any task/event exists; this does
    # not model or authorize changing an enrolled live link's workflow owner.
    link = replace(cycle.link, workflow_version='artifact-v1')
    with store.transaction() as tx:
        tx._connection.execute('UPDATE conversation_links SET snapshot=%s WHERE link_id=%s',
            (Jsonb(asdict(link)), link.link_id))
    return BuzzConversationCycle(service, cycle.relay, link), state, owner


def test_signed_buzz_request_and_web_controls_share_one_work(work_bridge, service, store, alice, envelope, start):
    cycle, relay, owner = work_bridge
    event = incoming(cycle, owner, 'Prepare an artifact.')
    relay['messages'] = [event]
    cycle.ingress()
    cycle.ingress()
    with store.transaction() as tx:
        works = tx.work_items('alice', 'personal-alice')
        assert len(works) == 1 and len(tx.tasks()) == 1
        work = works[0]
        assert tx.conversation_message(event['id'])['message'].task_id == work.task_id
    client = TestClient(create_app(service, lambda _: alice))
    view = WorkService(service).get(alice, work.work_id, envelope=envelope())
    paused = client.post(f'/v1/work/{work.work_id}/commands', json={
        'envelope': asdict(envelope()), **asdict(command(view, 'pause'))})
    assert paused.status_code == 200 and paused.json()['work']['state'] == 'paused'
    relay['messages'].append(incoming(cycle, owner, 'status', tags=[['e', event['id'], '', 'reply']], offset=1))
    cycle.ingress()
    cycle.egress()
    assert any('Paused' in e['content'] for e in relay['published'].values())
    second = WorkService(service).submit(alice, envelope(), start)
    assert second.work_id != work.work_id
    with store.transaction() as tx: assert len(tx.work_items('alice', 'personal-alice')) == 2


def test_buzz_completion_uses_verified_work_status_and_never_posts_protocol_json(work_bridge, service, store, fake_work, alice, envelope):
    cycle, relay, owner = work_bridge
    relay['messages'] = [incoming(cycle, owner)]
    cycle.ingress()
    with store.transaction() as tx: work = tx.work_items('alice', 'personal-alice')[0]
    fake_work.result_content = result(work, outcome='blocked', reason='dependency_unavailable')
    service.run(work.task_id)
    cycle.egress()
    bodies = [e['content'] for e in relay['published'].values()]
    assert any('Waiting' in value for value in bodies)
    assert not any('work-result-v1' in value or 'result is ready' in value for value in bodies)
    relay['messages'].append(incoming(cycle, owner, 'Where is my result?',
        tags=[['e', relay['messages'][0]['id'], '', 'reply']], offset=1))
    cycle.ingress()
    with store.transaction() as tx: assert len(tx.tasks()) == 1


def test_crash_after_work_admission_before_chat_ack_replays_one_original_work(work_bridge, service, store, monkeypatch):
    cycle, relay, owner = work_bridge
    relay['messages'] = [incoming(cycle, owner)]
    original = WorkService.submit
    def lose(self, *args):
        original(self, *args)
        raise RuntimeError('lost acknowledgement')
    monkeypatch.setattr(WorkService, 'submit', lose)
    with pytest.raises(RuntimeError): cycle.ingress()
    monkeypatch.setattr(WorkService, 'submit', original)
    BuzzConversationCycle(service, cycle.relay, cycle.link).ingress()
    with store.transaction() as tx:
        assert len(tx.tasks()) == 1 and len(tx.work_items('alice', 'personal-alice')) == 1
        assert tx.conversation_message(relay['messages'][0]['id'])['processed']


def test_revoked_access_cannot_deliver_prepared_work_notifications(work_bridge, service, store):
    cycle, relay, owner = work_bridge
    relay['messages'] = [incoming(cycle, owner)]
    cycle.ingress()
    cycle._prepare_outbox()
    with store.transaction() as tx:
        tx._connection.execute("DELETE FROM bot_grants WHERE principal_id='alice'")
    with pytest.raises(Rejected): cycle.egress()
    assert relay['published'] == {}


def test_artifact_enrollment_cannot_use_legacy_coordinator(work_bridge, service):
    cycle, _, _ = work_bridge
    legacy = ProjectBuzzConversationCycle(service, SimpleNamespace(link=cycle.link, relay=cycle.relay), ())
    with pytest.raises(Rejected, match='workflow_owner_conflict'): legacy.ingress()


def test_artifact_reply_to_another_specialist_cannot_use_legacy_followup_route(work_bridge):
    cycle, _, _ = work_bridge
    previous = SimpleNamespace(task_id='older-task', bot_id='another-specialist',
                               phase='closed', result='Previous report')
    tx = SimpleNamespace(conversation_pending=lambda *_a, **_k: (),
        conversation_reply=lambda *_: {'message': SimpleNamespace(link_id=cycle.link.link_id, task_id=previous.task_id)},
        conversation_link=lambda _: cycle.link, task=lambda _: previous)
    message = ConversationMessage('followup', cycle.link.link_id, 'owner', 'status',
        'buzz', cycle.link.activated_at, reply_to='older-specialist-result')
    assert cycle.conversations._route(tx, cycle.link, message).action == 'clarify'


def test_real_postgres_work_completes_while_signed_relay_is_stalled(work_bridge, service, store, fake_work, alice, envelope):
    cycle, relay, owner = work_bridge
    relay['messages'] = [incoming(cycle, owner)]
    cycle.ingress()
    with store.transaction() as tx: work = tx.work_items('alice', 'personal-alice')[0]
    fake_work.result_content = result(work)
    entered, release, done = Event(), Event(), Event()
    def stall(*_):
        entered.set()
        release.wait(5)
        return []
    cycle.relay.messages = stall
    original = service.advance
    def advance(*args):
        value = original(*args)
        if value.phase == 'closed': done.set()
        return value
    service.advance = advance
    loops = ControllerLoops(SimpleNamespace(coordinator=Coordinator(service, 'worker'),
        conversations=(cycle,), store=store), interval=0.1)
    loops.start()
    try:
        assert entered.wait(2) and done.wait(3)
        assert WorkService(service).get(alice, work.work_id, envelope=envelope()).state == 'completed'
        assert fake_work.start_count == 1
    finally:
        release.set()
        loops.stop()
