"""Capability facts are current for new turns and immutable on dispatch retry."""
from uuid import uuid4

import pytest

from radhouse.chat.service import ChatService
from radhouse.chat.store import ChatStore
from radhouse.domain.tasks import Rejected
from tests.test_minimal_chat import SyntheticHermes


def test_capability_context_is_frozen_without_changing_owner_text_or_tools(tmp_path):
    hermes = SyntheticHermes()
    service = ChatService(ChatStore(tmp_path / 'chat.db'), hermes.client, owner_id='owner', clock=lambda: 1000)
    context = ['Responsibility permission enabled; review failed.']
    service.responsibility_context = lambda: context[0]
    request_id = str(uuid4())
    hermes.lose_ack = True
    try:
        with pytest.raises(Rejected, match='assistant_unavailable'):
            service.send('owner', request_id, 'What can you do?')
        context[0] = 'Responsibility paused.'
        service.retry('owner', request_id)
        first, retried = [body for _, body in hermes.requests]
        assert first['input'] == retried['input']
        assert 'permission enabled; review failed' in first['input']
        assert first['disable_tools'] is True
        assert service.store.find('owner', request_id)['text'] == 'What can you do?'
        hermes.status = 'completed'
        service.poll('owner')
        service.send('owner', str(uuid4()), 'And now?')
        assert 'Responsibility paused.' in hermes.requests[-1][1]['input']
    finally:
        hermes.client.close()
