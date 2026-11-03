"""The native canvas has a fixed public shell; private data stays behind auth."""
import pytest
from tests.test_chat_browser_api import api
from scripts.release import STATIC, static_route


@pytest.mark.parametrize('path,media', [('/mobile/browser','text/html'),
    ('/mobile-browser.js','text/javascript'),('/mobile-browser.css','text/css')])
def test_native_canvas_assets_are_fixed_and_do_not_grant_browser_access(api, path, media):
    client, _, store, relay = api
    response = client.get(path)
    assert response.status_code == 200
    assert media in response.headers['content-type']
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert store.owners == []
    assert relay.calls == []
    assert client.get('/chat/browser').status_code == 401
    name = 'mobile-browser.html' if path == '/mobile/browser' else path[1:]
    assert static_route(STATIC + name) == path


def test_native_canvas_shell_has_no_workspace_navigation_or_inline_code(api):
    client, _, _, _ = api
    html = client.get('/mobile/browser').text
    assert '<script src="/mobile-browser.js">' in html
    assert '<script>' not in html
    assert 'id="compose"' not in html
    assert 'id="chat-view"' not in html
