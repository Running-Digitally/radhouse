"""Native Buzz adds live signed membership to the existing MFA/cookie boundary."""
import json
import time

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse

from radhouse.channels.nostr import encoded, nip98, sha256, verify_event
from radhouse.domain.access import AuthContext
from radhouse.domain.tasks import Rejected


class BuzzBoundary:
    def __init__(self, service, local_auth, config, controller_origin, *, transport=None):
        self.service, self.local_auth, self.config = service, local_auth, config
        self.controller_origin = controller_origin
        self.transport = transport

    def membership(self, header, pubkey, channel, now):
        # Native signs this exact fixed query. No user-selected destination or
        # query reaches the relay; the relay enforces current admission/replay.
        body = encoded([{"kinds": [39002], "authors": [self.config.relay_pubkey], "#d": [channel], "limit": 1}])
        url = self.config.relay_origin + "/query"
        event, _ = nip98(header, url, "POST", body, now)
        if event["pubkey"] != pubkey:
            raise Rejected("buzz_identity_denied", 403)
        try:
            deadline = time.monotonic() + 10
            with httpx.Client(timeout=5, follow_redirects=False, trust_env=False, transport=self.transport) as client:
                with client.stream("POST", url, content=body, headers={"Authorization": header, "Content-Type": "application/json"}) as response:
                    data = bytearray()
                    if response.status_code != 200:
                        raise Rejected("buzz_membership_denied", 403)
                    for chunk in response.iter_bytes():
                        if time.monotonic() > deadline:
                            raise Rejected("buzz_membership_unavailable", 503)
                        data.extend(chunk)
                        if len(data) > 524288:
                            raise Rejected("buzz_membership_unavailable", 503)
            values = json.loads(data)
            if not isinstance(values, list) or len(values) != 1:
                raise Rejected("buzz_membership_denied", 403)
            snapshot = verify_event(values[0], 39002)
            if snapshot["pubkey"] != self.config.relay_pubkey:
                raise Rejected("buzz_membership_denied", 403)
            channels = [tag for tag in snapshot["tags"] if tag[0] == "d"]
            members = [tag for tag in snapshot["tags"] if tag[0] == "p" and len(tag) >= 2 and tag[1] == pubkey]
            if (channels != [["d", channel]] or len(members) != 1 or len(members[0]) != 4
                    or members[0][3] not in {"owner", "admin", "member"}):
                raise Rejected("buzz_membership_denied", 403)
        except (httpx.HTTPError, ValueError, UnicodeError):
            raise Rejected("buzz_membership_unavailable", 503) from None

    def verify(self, request, body):
        now = int(self.service._now().timestamp())
        event, tags = nip98(request.headers.get("authorization", ""),
            self.controller_origin + request.url.path + ("?" + request.url.query if request.url.query else ""),
            request.method, body, now)
        membership = request.headers.get("x-buzz-membership", "")
        channel = tags.get("h")
        configured = next((item for item in self.config.conversations if item.channel_id == channel), None)
        if (configured is None or tags.get("relay") != self.config.relay_origin
                or tags.get("membership") != sha256(membership.encode()) or tags.get("thread", "") != ""):
            raise Rejected("buzz_conversation_denied", 403)
        self.membership(membership, event["pubkey"], channel, now)
        with self.service.store.transaction() as tx:
            binding = tx.binding("buzz", event["pubkey"], configured.conversation_id)
            if binding is None or not binding.active:
                raise Rejected("binding_denied", 403)
            access = tx.access(binding.principal_id)
            if access is None or not access.active or binding.project_id not in access.projects:
                raise Rejected("access_denied", 403)
        # A signed command cannot move this authenticated channel to another
        # otherwise-valid project/conversation binding.
        value = json.loads(body) if body else {}
        envelope = value.get("envelope", {}) if isinstance(value, dict) else {}
        if (envelope and (envelope.get("conversation_id") != binding.conversation_id
                          or envelope.get("channel") != "buzz")
                or request.query_params.get("conversation_id", binding.conversation_id) != binding.conversation_id):
            raise Rejected("buzz_conversation_denied", 403)
        request.state.buzz_binding = binding
        return binding

    def authenticate(self, request):
        # Cookie/session, exact Origin and CSRF still cross LocalAuthService.
        local = self.local_auth.auth_context(request)
        binding = request.state.buzz_binding
        if local.principal_id != binding.principal_id:
            raise Rejected("buzz_identity_denied", 403)
        return AuthContext(local.principal_id, "buzz", binding.subject, local.assurance_until)


def create_buzz_app(service, local_auth, config, controller_origin, *, transport=None):
    from radhouse.api.app import create_app
    boundary = BuzzBoundary(service, local_auth, config, controller_origin, transport=transport)
    app = create_app(service, boundary.authenticate, local_auth=local_auth,
                     login_principal=lambda request: request.state.buzz_binding.principal_id,
                     session_binding=lambda request: request.state.buzz_binding)

    @app.middleware("http")
    async def signed_request(request: Request, call_next):
        try:
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 262144:
                    raise Rejected("request_too_large", 413)
            # Starlette caches this bounded body for downstream validation.
            request._body = bytes(body)
            from starlette.concurrency import run_in_threadpool
            await run_in_threadpool(boundary.verify, request, bytes(body))
            return await call_next(request)
        except Rejected as error:
            return JSONResponse({"code": error.code}, status_code=error.status, headers={"Cache-Control": "no-store"})
        except (ValueError, UnicodeError):
            return JSONResponse({"code": "invalid_request"}, status_code=422)
    return app
