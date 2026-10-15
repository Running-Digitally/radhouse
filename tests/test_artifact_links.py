"""Exact retained artifact navigation through current signed enrollment and access."""
from dataclasses import replace
from datetime import timedelta
import json

import pytest
from fastapi.testclient import TestClient

from radhouse.api.app import create_app
from radhouse.application.conversations import Conversations
from radhouse.application.review_links import ReviewLinks, TTL
from radhouse.application.work_service import WorkService
from radhouse.channels.buzz_conversations import BuzzConversationCycle
from radhouse.domain.conversations import ConversationMessage
from radhouse.domain.tasks import Rejected
from tests.test_buzz_enrollment import enrollment
from tests.test_buzz_conversations import bridge
from tests.test_work_lifecycle import result

pytestmark = pytest.mark.postgres


@pytest.fixture
def artifact_link(enrollment, service, store, alice, envelope, start, fake_work):
    registry, configured, state, actor, command, attestation, candidate = enrollment
    configured.workflow_version = 'artifact-v1'
    registry.enroll(actor, command, candidate.link_id, candidate.channel_id, attestation)
    with store.transaction() as tx:
        link = tx.conversation_link(candidate.link_id)
    service.durable_work_enabled = True
    service.review_links = ReviewLinks(service, 'https://radhouse.test', (configured,))
    work = WorkService(service).submit(alice, envelope(), start)
    fake_work.result_content = result(work, artifact=dict(name='report.md', media_type='text/markdown',
        content='# Report\nUseful retained artifact.\n<script>window.unsafe=true</script>'))
    service.run(work.task_id)
    with store.transaction() as tx:
        work = tx.work_item(work.work_id)
        task = tx.task(work.task_id)
        url = service.review_links.issue_artifact(tx, link, task, work)
        tx.save_conversation_message(ConversationMessage('artifact-request', link.link_id, link.principal_id,
            start.brief, 'buzz', link.activated_at, task_id=task.task_id), processed=True)
    state['published'].clear()
    return url.split('#review=')[1], work, configured, state, link


def test_artifact_locator_opens_exact_bytes_without_approval_or_new_work(artifact_link, service, store, alice, envelope):
    token, work, _, _, _ = artifact_link
    target = service.review_links.resolve(alice, token)
    assert target['work_id'] == work.work_id and target['artifact_id'] == work.artifact_id
    client = TestClient(create_app(service, lambda _: alice))
    assert client.post('/reviews/resolve', json={'locator': token}).status_code == 200
    response = client.get(f'/v1/work/{work.work_id}/artifacts/{work.artifact_id}', params={
        'conversation_id': target['conversation_id'], 'binding_revision': target['binding_revision']})
    assert response.status_code == 200 and '# Report' in response.text
    with store.transaction() as tx:
        assert len(tx.tasks()) == 1 and tx.publication(work.task_id) is None
        with pytest.raises(Rejected, match='artifact_review_required'):
            service.review_links.issue(tx, tx.conversation_link('researcher'), tx.task(work.task_id))


@pytest.mark.parametrize('change', ['signature', 'expiry', 'scope', 'bytes', 'artifact', 'grant', 'binding', 'candidate', 'audience'])
def test_artifact_locator_rejects_changed_artifact_or_authority(artifact_link, service, store, alice, clock, change):
    token, work, configured, _, link = artifact_link
    if change == 'signature': token = token[:-1] + ('0' if token[-1] != '0' else '1')
    if change == 'expiry': clock.advance(seconds=TTL)
    if change == 'candidate': configured.candidate.active = False
    if change == 'audience': alice = replace(alice, principal_id='bob')
    with store.transaction() as tx:
        if change == 'grant': tx._connection.execute("DELETE FROM bot_grants WHERE principal_id='alice'")
        if change == 'binding': tx._connection.execute("UPDATE channel_bindings SET active=false WHERE channel='radhouse'")
        if change == 'scope': tx.save_work(work.evolve(clock(), scope_revision=2), work.state_revision)
        if change == 'artifact': tx.save_work(work.evolve(clock(), artifact_id=None), work.state_revision)
        if change == 'bytes': tx._connection.execute('UPDATE work_artifacts SET content=%s WHERE artifact_id=%s', ('changed', work.artifact_id))
    with pytest.raises(Rejected): service.review_links.resolve(alice, token)


def test_terminal_followup_reads_same_work_and_refreshes_expired_artifact_link(artifact_link, service, store, clock):
    _, work, configured, state, link = artifact_link
    clock.advance(seconds=TTL+1)
    app = Conversations(service)
    message = ConversationMessage('followup', link.link_id, link.principal_id, 'Where is my report?',
        'buzz', int(clock().timestamp()), reply_to='artifact-request')
    app.receive(link, message)
    assert app.process(link, message.message_id).task_id == work.task_id
    with store.transaction() as tx:
        reply = tx.conversation_message('reply:followup')['message']
        assert '#review=' in reply.content and 'Done' in reply.content and len(tx.tasks()) == 1
    assert configured.run('egress')['error_code'] is None
    original = dict(state['published'])
    assert configured.run('egress')['error_code'] is None and state['published'] == original


def test_ambiguous_message_offers_owned_work_and_reply_selects_it_without_dispatch(
        artifact_link, service, store, alice, envelope, start, clock, fake_work):
    _, original, _, _, link = artifact_link
    app = Conversations(service)
    selected = []
    for index in range(2):
        clock.advance(seconds=1)
        work = WorkService(service).submit(alice, envelope(), replace(start, brief=f'Report {index}'))
        selected.append(work)
        with store.transaction() as tx:
            tx.save_conversation_message(ConversationMessage(f'anchor-{index}', link.link_id,
                link.principal_id, f'Report {index}', 'buzz', int(clock().timestamp()),
                task_id=work.task_id), processed=True)
    # Newer work belonging to another specialist must not crowd out this bot's choices.
    for index in range(3):
        clock.advance(seconds=1)
        WorkService(service).submit(alice, envelope(), replace(start, bot_id='bot-beta', brief=f'Other {index}'))
    message = ConversationMessage('ambiguous', link.link_id, link.principal_id, 'status',
        'buzz', int(clock().timestamp()))
    app.receive(link, message)
    assert app.process(link, message.message_id).task_id is None
    assert app.process(link, message.message_id).task_id is None  # Receipt replay.
    with store.transaction() as tx:
        choices = [row['message'] for row in tx.conversation_history(link.link_id)
                   if row['message'].state == 'choice']
        assert {choice.task_id for choice in choices} == {original.task_id, *(work.task_id for work in selected)}
        chosen = next(choice for choice in choices if choice.task_id == selected[0].task_id)
    reply = ConversationMessage('chosen', link.link_id, link.principal_id, 'status', 'buzz',
        int(clock().timestamp()), reply_to=chosen.message_id)
    app.receive(link, reply)
    assert app.process(link, reply.message_id).task_id == selected[0].task_id
    with store.transaction() as tx:
        assert len(tx.tasks()) == 6
    assert fake_work.start_count == 1
