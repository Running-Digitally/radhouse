"""A new reply may reuse agent control, but cannot acquire a human lease."""
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from radhouse.chat.app import create_app
from radhouse.chat.service import ChatService
from radhouse.domain.tasks import Rejected
from tests.test_browser_session_web import app, dispatch_client, HEADERS  # noqa: F401


@pytest.mark.parametrize('mode', ['agent', 'human', 'paused', 'recovering'])
@pytest.mark.parametrize('url', ['about:blank', 'https://example.org/'])
def test_ordinary_message_continues_only_agent_control(app, mode, url):
    client, auth, native, store, browser = app
    assert client.post('/chat/browser/open', headers=HEADERS).status_code == 200
    native.page = {'url': url, 'title': 'Synthetic page'}
    original = native.browser_session

    def status(*args):
        value = original(*args)
        value['control'] = {'mode': mode, 'revision': 3, 'can_take': False}
        return value

    native.browser_session = status
    runtime, calls, _ = dispatch_client()
    service = ChatService(store, runtime, owner_id='alice', clock=lambda: 1000,
                          browser_enabled=True, browser_control=True)
    identifier = str(uuid4())
    body = {'request_id': identifier, 'text': 'Read the public page'}
    try:
        with TestClient(create_app(auth, service, browser=browser), base_url='http://127.0.0.1') as fresh:
            fresh.cookies.set(auth.cookie_name, 'synthetic-cookie')
            response = fresh.post('/chat/messages', headers=HEADERS, json=body)
            assert response.status_code == 200
            sent = calls[0][1]
            if mode == 'agent':
                assert sent['browser_context']['generation'] == 'generation-1'
                assert sent['browser_context']['revision'] == 3
                assert sent['browser_context']['lease_id'] is None
            else:
                assert 'browser_context' not in sent
            saved = store.find('alice', identifier)
            assert 'page' not in json.loads(saved['browser_context'])
            assert 'Synthetic page' not in saved['input_text']
            # Network replay keeps the frozen authority; it must not resample
            # a changed browser or require the client to invent a page binding.
            native.browser_session = lambda *_: pytest.fail('replay read browser state')
            again = fresh.post('/chat/messages', headers=HEADERS, json=body)
            assert again.status_code == 200
            assert len(calls) == 1
    finally:
        runtime.close()


@pytest.mark.parametrize('error,previous,allowed', [
    ('browser_unavailable', False, True), ('browser_unavailable', True, False),
    ('browser_control_changed', False, False), ('authentication_required', False, False),
])
def test_optional_browser_outage_does_not_block_chat_or_infer_authority(app, monkeypatch, error, previous, allowed):
    _, auth, _, _, browser = app
    session = auth.login('alice', 'synthetic-password', '123456', 'local', remember_browser=False)
    # Use the fixture's current bounded authenticated lifetime.
    from dataclasses import replace
    from datetime import datetime, timezone
    session = replace(session, expires_at=datetime.fromtimestamp(2000, timezone.utc))
    def fail(*_):
        raise Rejected(error, 503)
    monkeypatch.setattr(browser, 'status', fail)
    if allowed:
        data = browser.dispatch_data(session, HEADERS['X-Radhouse-Browser-Tab'])
        assert set(data) == {'browser_owner'}
    else:
        with pytest.raises(Rejected, match=error):
            browser.dispatch_data(session, HEADERS['X-Radhouse-Browser-Tab'], use_previous=previous)
