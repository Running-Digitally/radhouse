"""FCM v1 transport with a fixed destination and generic notification content."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import re
import time
from typing import Callable
from uuid import UUID

import httpx

from .push import PushResult
from .push_proxy import push_proxy


APP_ID = "com.runningdigitally.radhouse"


def _payload(token, platform, data):
    if not isinstance(data, dict):
        raise ValueError("invalid_push_message")
    commitment = data.get("version") == "2" and data.get("kind") == "commitment_ready"
    target = "item_id" if commitment else "request_id"
    if (platform not in {"ios", "android"} or not isinstance(token, str)
            or not re.fullmatch(r"[A-Za-z0-9_:.-]{20,4096}", token)
            or set(data) != {"version", "kind", "event_id", target}
            or not commitment and (data["version"] != "1" or data["kind"] != "reply_ready")):
        raise ValueError("invalid_push_message")
    for field in ("event_id", target):
        value = UUID(data[field])
        if value.version not in range(1, 9) or str(value) != data[field]:
            raise ValueError("invalid_push_message")
    message = {"token": token, "data": data,
               "notification": {"title": "Radhouse", "body": "Radhouse has a suggestion for you" if commitment else "Your Radhouse reply is ready"}}
    if platform == "android":
        message["android"] = {"restricted_package_name": APP_ID, "ttl": "3600s",
                              "collapse_key": data["kind"], "priority": "normal",
                              "notification": {"tag": data["event_id"]}}
    else:
        message["apns"] = {"headers": {"apns-topic": APP_ID, "apns-push-type": "alert",
                                        "apns-priority": "10", "apns-collapse-id": data["event_id"],
                                        "apns-expiration": str(int(time.time()) + 3600)},
                           "payload": {"aps": {"sound": "default"}}}
    return {"message": message}


def _retry_after(value):
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            seconds = 60
    return max(60, min(3600, int(seconds)))


def _result(status, data, retry):
    if status == 200 and isinstance(data, dict) and isinstance(data.get("name"), str):
        return PushResult("sent")
    error = data.get("error", {}) if isinstance(data, dict) else {}
    details = error.get("details", []) if isinstance(error, dict) else []
    if isinstance(details, list) and any(isinstance(item, dict)
            and item.get("@type") == "type.googleapis.com/google.firebase.fcm.v1.FcmError"
            and item.get("errorCode") == "UNREGISTERED" for item in details):
        return PushResult("invalid")
    if status == 429 or status >= 500:
        return PushResult("retry", _retry_after(retry))
    # Configuration/APNs/credential errors must not delete otherwise valid tokens.
    return PushResult("blocked")


class FCMSender:
    def __init__(self, project_id: str, access_token: Callable[[], str], *, transport=None,
                 proxy_url: str | None = None):
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", project_id):
            raise ValueError("invalid_firebase_project")
        self.url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
        self.access_token = access_token
        self.client = httpx.Client(timeout=5, follow_redirects=False, trust_env=False,
                                   transport=transport, proxy=push_proxy(proxy_url))

    def close(self):
        self.client.close()

    def __call__(self, token, platform, data):
        payload = _payload(token, platform, data)
        try:
            access = self.access_token()
            if not isinstance(access, str) or not access or len(access) > 16384 or "\n" in access or "\r" in access:
                return PushResult("blocked")
            with self.client.stream("POST", self.url, json=payload,
                                    headers={"Authorization": "Bearer " + access}) as response:
                content = bytearray()
                for chunk in response.iter_bytes(chunk_size=8192):
                    content.extend(chunk)
                    if len(content) > 65536:
                        return PushResult("retry")
                try:
                    result = json.loads(content)
                except ValueError:
                    return PushResult("retry")
                return _result(response.status_code, result, response.headers.get("retry-after"))
        except Exception:
            # Exceptions from credentials/transports can include tokens or key paths.
            return PushResult("retry")
