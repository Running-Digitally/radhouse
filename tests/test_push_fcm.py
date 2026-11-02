import json
from uuid import uuid4

import httpx
import pytest

from radhouse.chat.push import PushResult, notification
from radhouse.chat.push_fcm import APP_ID, FCMSender


TOKEN = "synthetic-registration-token-0001"
DATA = notification("synthetic-owner", str(uuid4()))


@pytest.mark.parametrize("platform", ["ios", "android"])
def test_fixed_provider_generic_content_and_app_scope(platform):
    calls = []
    def provider(request):
        calls.append(request)
        return httpx.Response(200, json={"name": "projects/synthetic-project/messages/test"})
    sender = FCMSender("synthetic-project", lambda: "synthetic-oauth", transport=httpx.MockTransport(provider))
    try:
        assert sender(TOKEN, platform, DATA) == PushResult("sent")
    finally:
        sender.close()
    request = calls[0]
    assert str(request.url) == "https://fcm.googleapis.com/v1/projects/synthetic-project/messages:send"
    assert request.headers["authorization"] == "Bearer synthetic-oauth"
    message = json.loads(request.content)["message"]
    assert message["data"] == DATA
    assert message["notification"] == {"title": "Radhouse", "body": "Your Radhouse reply is ready"}
    if platform == "ios":
        assert message["apns"]["headers"]["apns-topic"] == APP_ID
        assert message["apns"]["headers"]["apns-collapse-id"] == DATA["event_id"]
    else:
        assert message["android"]["restricted_package_name"] == APP_ID
        assert message["android"]["notification"]["tag"] == DATA["event_id"]


@pytest.mark.parametrize("status,body,expected", [
    (404, {"error": {"details": [{"@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError",
                                   "errorCode": "UNREGISTERED"}]}}, "invalid"),
    (404, {"error": {"status": "NOT_FOUND"}}, "blocked"),
    (401, {"error": {"status": "THIRD_PARTY_AUTH_ERROR"}}, "blocked"),
    (403, {"error": {"status": "SENDER_ID_MISMATCH"}}, "blocked"),
    (400, {"error": {"status": "INVALID_ARGUMENT"}}, "blocked"),
    (429, {}, "retry"),
    (503, {}, "retry"),
    (200, {}, "blocked"),
])
def test_token_rejection_is_distinct_from_config_failure(status, body, expected):
    sender = FCMSender("synthetic-project", lambda: "synthetic-oauth",
        transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body)))
    try:
        assert sender(TOKEN, "ios", DATA).outcome == expected
    finally:
        sender.close()


def test_provider_redirect_never_forwards_credentials_to_another_host():
    calls = []
    def provider(request):
        calls.append(request)
        return httpx.Response(307, headers={"location": "https://foreign.invalid"}, json={})
    sender = FCMSender("synthetic-project", lambda: "synthetic-oauth", transport=httpx.MockTransport(provider))
    try:
        assert sender(TOKEN, "ios", DATA).outcome == "blocked"
    finally:
        sender.close()
    assert len(calls) == 1


@pytest.mark.parametrize("body", [b"invalid-json", b"x" * 65537])
def test_malformed_or_large_provider_response_is_sanitized(body):
    sender = FCMSender("synthetic-project", lambda: "synthetic-oauth",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body)))
    try:
        assert sender(TOKEN, "ios", DATA).outcome == "retry"
    finally:
        sender.close()


def test_invalid_content_never_reaches_provider():
    def provider(_):
        pytest.fail("Must not transmit an arbitrary notification payload")
    sender = FCMSender("synthetic-project", lambda: "synthetic-oauth", transport=httpx.MockTransport(provider))
    try:
        with pytest.raises(ValueError, match="invalid_push_message"):
            sender(TOKEN, "ios", {**DATA, "text": "Private conversation"})
    finally:
        sender.close()


def test_rate_limit_retry_after_and_credentials_failure():
    sender = FCMSender("synthetic-project", lambda: "synthetic-oauth",
        transport=httpx.MockTransport(lambda _: httpx.Response(429, json={}, headers={"retry-after": "300"})))
    try:
        assert sender(TOKEN, "android", DATA) == PushResult("retry", 300)
    finally:
        sender.close()
    def credentials():
        raise RuntimeError("private credential detail")
    sender = FCMSender("synthetic-project", credentials)
    try:
        assert sender(TOKEN, "ios", DATA).outcome == "retry"
    finally:
        sender.close()
