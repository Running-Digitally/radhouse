"""Server-only Google Auth credentials; fixed token endpoint and bounded refresh."""
import json
import os
from pathlib import Path
import stat
from threading import Lock
import time

from google.auth.transport.requests import Request
from google.oauth2 import service_account
import requests

from .push_proxy import push_proxy


TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


class GooglePushToken:
    def __init__(self, path: Path, project_id: str, *, proxy_url: str | None = None):
        self.lock = Lock()
        proxy = push_proxy(proxy_url)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "r") as source:
                info = os.fstat(source.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                        or info.st_size > 65536 or info.st_uid != os.getuid()):
                    raise ValueError
                data = json.load(source)
            if (data.get("type") != "service_account" or data.get("project_id") != project_id
                    or data.get("token_uri") != TOKEN_URI):
                raise ValueError
            self.credentials = service_account.Credentials.from_service_account_info(data, scopes=[SCOPE])
        except Exception:
            raise ValueError("invalid_push_credentials") from None
        self.session = requests.Session()
        self.session.trust_env = False
        if proxy is not None:
            self.session.proxies = {"https": proxy}
        self.request = Request(session=self.session)

    def close(self):
        self.session.close()

    def __call__(self):
        with self.lock:
            if not self.credentials.valid:
                deadline = time.monotonic() + 8

                def bounded_request(url, method="GET", body=None, headers=None, **_ignored):
                    remaining = deadline - time.monotonic()
                    if url != TOKEN_URI or remaining <= 0:
                        raise ValueError("push_token_refresh_unavailable")
                    return self.request(url, method=method, body=body, headers=headers,
                                        timeout=min(5, remaining), allow_redirects=False)

                self.credentials.refresh(bounded_request)
            return self.credentials.token
