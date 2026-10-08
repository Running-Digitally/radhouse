"""Owner-scoped browser observation, explicit control and private vault relay."""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import base64
import binascii
import math
import re
import time
from urllib.parse import urlsplit, urlunsplit

from radhouse.domain.tasks import Rejected
from radhouse.integrations.hermes import HermesGatewayError, HermesRunsClient


BROWSER_TOOLS = (
    "browser_navigate", "browser_snapshot", "browser_click", "browser_type",
    "browser_scroll", "browser_back", "browser_press",
)
LOGIN_TOOLS = ("browser_login_list", "browser_login_fill")
MAX_FRAME_BYTES = 512 * 1024
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}")
_PERMITTED = frozenset((*BROWSER_TOOLS, "document_search", "document_read", "file_share"))
_ACTIVE = frozenset(("awaiting_dispatch", "queued", "running", "waiting_for_approval", "stopping"))
_VIEWABLE = _ACTIVE | frozenset(("completed", "failed", "cancelled", "interrupted"))


def _identifier(value):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise HermesGatewayError("browser_response_invalid")
    return value


def _display_url(value):
    """Display metadata only; the VM's firewall owns network reachability."""
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise HermesGatewayError("browser_response_invalid")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            raise ValueError
        # Accessing port validates it; omit credentials, query tokens and fragments.
        parsed.port
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except ValueError:
        raise HermesGatewayError("browser_response_invalid") from None


@dataclass(frozen=True)
class BrowserStatus:
    run_id: str
    session_id: str
    state: str
    generation: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class BrowserFrame:
    jpeg: bytes
    generation: str
    frame_id: str
    received_at: float
    run_id: str
    session_id: str
    captured_at: None = None  # The pinned native driver does not retain a reliable capture epoch.
    width: int | None = None
    height: int | None = None


class HermesBrowserClient:
    """Fixed private relay. Native stream ports and broad browser APIs stay private."""
    def __init__(self, endpoint, bearer_token, *, transport=None, clock=time.time):
        self._runs = HermesRunsClient(endpoint, bearer_token, transport=transport,
            connect_timeout=2, read_timeout=3, request_deadline=5)
        # Owner actions can wait for native launch, fencing and metadata in turn
        # (45 seconds each), then the existing 3-second stream observation. Keep
        # those acknowledgements connected without slowing observer requests or
        # retrying an action whose native outcome may already have been applied.
        self._actions = HermesRunsClient(endpoint, bearer_token, transport=transport,
            connect_timeout=2, read_timeout=150, request_deadline=155)
        self.clock = clock

    def close(self):
        self._runs.close()
        self._actions.close()

    def browser_session(self, session_id, operation, body):
        _identifier(session_id)
        paths = {"open", "status", "frame", "control/take", "control/heartbeat",
            "control/input", "control/pause", "control/close", "logins/list", "logins/save", "logins/remove"}
        if operation not in paths:
            raise ValueError("invalid_browser_operation")
        path = ("v1/browser-sessions/open" if operation == "open"
            else f"v1/browser-sessions/{session_id}/{operation}")
        client = self._runs if operation in {"status", "frame"} else self._actions
        payload, _ = client._request("POST", path, expected_status=200,
            body={**body, **({"session_id": session_id} if operation == "open" else {})})
        return payload

    def browser_status(self, run_id):
        _identifier(run_id)
        payload, _ = self._runs._request("GET", f"v1/runs/{run_id}/browser", expected_status=200)
        state = payload.get("state")
        if state not in ("starting", "live", "idle", "unavailable"):
            raise HermesGatewayError("browser_response_invalid")
        generation = payload.get("generation")
        if generation is not None:
            generation = _identifier(generation)
        if state == "live" and generation is None:
            raise HermesGatewayError("browser_response_invalid")
        status = BrowserStatus(_identifier(payload.get("run_id")),
            _identifier(payload.get("session_id")), state, generation,
            _display_url(payload.get("url")))
        if status.run_id != run_id:
            raise HermesGatewayError("browser_response_invalid")
        return status

    def browser_frame(self, run_id):
        _identifier(run_id)
        payload, _ = self._runs._request("GET", f"v1/runs/{run_id}/browser-frame", expected_status=200)
        encoded, received = payload.get("jpeg"), payload.get("received_at")
        if type(received) not in (int, float) or payload.get("captured_at") is not None:
            raise HermesGatewayError("browser_response_invalid")
        try:
            received = float(received)
        except OverflowError:
            raise HermesGatewayError("browser_response_invalid") from None
        if (not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_FRAME_BYTES + 2) // 3)
                or not math.isfinite(received) or received < 0 or received > self.clock() + 30):
            raise HermesGatewayError("browser_response_invalid")
        try:
            jpeg = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise HermesGatewayError("browser_response_invalid") from None
        if (not 4 <= len(jpeg) <= MAX_FRAME_BYTES or not jpeg.startswith(b"\xff\xd8\xff")
                or not jpeg.endswith(b"\xff\xd9")):
            raise HermesGatewayError("browser_response_invalid")
        frame = BrowserFrame(jpeg, _identifier(payload.get("generation")),
            _identifier(payload.get("frame_id")), received,
            _identifier(payload.get("run_id")), _identifier(payload.get("session_id")))
        if frame.run_id != run_id:
            raise HermesGatewayError("browser_response_invalid")
        return frame


class BrowserService:
    def __init__(self, store, hermes, *, owner_id):
        if not isinstance(owner_id, str) or not owner_id or len(owner_id) > 200:
            raise ValueError("invalid_chat_owner")
        self.store, self.hermes, self.owner_id = store, hermes, owner_id

    def _current(self, owner):
        if owner != self.owner_id:
            raise Rejected("owner_access_required", 403)
        run = self.store.browser_run(owner)
        if run is None:
            return None
        tools = run.get("allowed_tools")
        if (type(tools) is not tuple or any(type(tool) is not str for tool in tools)
                or len(tools) != len(set(tools))
                or not set(BROWSER_TOOLS) <= set(tools) or not set(tools) <= _PERMITTED
                or "file_share" in tools and not {"document_search", "document_read"} <= set(tools)
                or run.get("status") not in _VIEWABLE):
            raise Rejected("browser_scope_unavailable", 503)
        try:
            _identifier(run.get("session_id"))
            if run.get("run_id") is not None:
                _identifier(run["run_id"])
        except HermesGatewayError:
            raise Rejected("browser_scope_unavailable", 503) from None
        return run

    @staticmethod
    def _identity(run):
        return (run.get("request_id"), run["run_id"], run["session_id"], run["allowed_tools"])

    def _unchanged(self, owner, run):
        current = self._current(owner)
        return current is not None and self._identity(current) == self._identity(run)

    @staticmethod
    def _idle():
        return {"state": "idle", "run_id": None, "generation": None, "url": None}

    def status(self, owner):
        run = self._current(owner)
        if run is None:
            return self._idle()
        if run["run_id"] is None:
            if run["status"] not in _ACTIVE:
                return self._idle()
            return {"state": "starting", "run_id": None, "generation": None, "url": None}
        try:
            status = self.hermes.browser_status(run["run_id"])
            if status.run_id != run["run_id"] or status.session_id != run["session_id"]:
                raise HermesGatewayError("browser_response_invalid")
        except HermesGatewayError:
            if not self._unchanged(owner, run):
                return self._idle()
            return {"state": "unavailable", "run_id": run["run_id"], "generation": None, "url": None}
        if not self._unchanged(owner, run):
            return self._idle()
        return {"state": status.state, "run_id": status.run_id,
                "generation": status.generation, "url": status.url}

    def frame(self, owner, run_id):
        run = self._current(owner)
        if run is None or run["run_id"] is None or run["run_id"] != run_id:
            raise Rejected("browser_run_changed", 409)
        try:
            frame = self.hermes.browser_frame(run_id)
            if frame.run_id != run_id or frame.session_id != run["session_id"]:
                raise HermesGatewayError("browser_response_invalid")
        except HermesGatewayError:
            raise Rejected("browser_unavailable", 503) from None
        if not self._unchanged(owner, run):
            raise Rejected("browser_run_changed", 409)
        return frame


class BrowserSessionService:
    """The owner's browser exists independently of a chat run.

    deployment-target owns native lifetime, fencing and the encrypted vault. This relay keeps
    only durable conversation/dispatch identities, never input or login values.
    """
    control_enabled = True

    def __init__(self, store, hermes, *, owner_id, chat_service, credential_vault=False, clock=time.time):
        self.store, self.hermes, self.owner_id = store, hermes, owner_id
        self.chat_service, self.clock = chat_service, clock
        self._credential_vault = credential_vault

    @property
    def credential_vault_enabled(self):
        """A live qualified capability can return after an agent outage."""
        try:
            value = self._credential_vault() if callable(self._credential_vault) else self._credential_vault
        except HermesGatewayError:
            return False
        return value is True

    def binding(self, session, tab_id):
        if session.principal_id != self.owner_id:
            raise Rejected("owner_access_required", 403)
        if (type(tab_id) is not str or not re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", tab_id)
                or type(session.binding_revision) is not int or session.binding_revision < 1
                or not isinstance(session.expires_at, datetime) or session.expires_at.tzinfo is None):
            raise Rejected("browser_binding_unavailable", 409)
        expires = session.expires_at.timestamp()
        if not math.isfinite(expires) or expires <= self.clock():
            raise Rejected("authentication_required", 401)
        _identifier(session.conversation_id)
        return {"owner": {"principal_id": session.principal_id,
            "conversation_id": session.conversation_id,
            "auth_session_digest": hashlib.sha256(session.token.encode()).hexdigest(),
            "binding_revision": session.binding_revision, "tab_id": tab_id}, "auth_expires_at": expires}

    def _call(self, session, tab_id, operation, values=None, *, create=False):
        binding = self.binding(session, tab_id)
        native_session = self.store.browser_session(self.owner_id, create=create)
        if native_session is None:
            if operation == "status":
                return {"state": "idle", "generation": None, "url": None, "title": None,
                    "control": None, "viewport": None, "page_context": {"current": None, "previous": None}}
            raise Rejected("browser_closed", 409)
        try:
            payload = self.hermes.browser_session(native_session, operation, {**binding, **(values or {})})
        except HermesGatewayError as exc:
            status = 409 if exc.code == "runtime_conflict" else 503
            raise Rejected("browser_control_changed" if status == 409 else "browser_unavailable", status) from None
        if payload.get("session_id") not in (None, native_session):
            raise Rejected("browser_unavailable", 503)
        return payload

    @staticmethod
    def _page(value):
        if value is None:
            return None
        if type(value) is not dict:
            raise Rejected("browser_unavailable", 503)
        try:
            url = _display_url(None if value.get("url") == "about:blank" else value.get("url"))
        except HermesGatewayError:
            raise Rejected("browser_unavailable", 503) from None
        title = value.get("title")
        if title is not None and (type(title) is not str or len(title) > 512 or any(ord(c) < 32 for c in title)):
            raise Rejected("browser_unavailable", 503)
        return {"url": url, "title": title}

    def _public(self, payload):
        state = payload.get("state")
        if state not in {"starting", "live", "idle", "unavailable"}:
            raise Rejected("browser_unavailable", 503)
        generation = payload.get("generation")
        try:
            if generation is not None:
                _identifier(generation)
            url = _display_url(None if payload.get("url") == "about:blank" else payload.get("url"))
        except HermesGatewayError:
            raise Rejected("browser_unavailable", 503) from None
        if state == "live" and generation is None:
            raise Rejected("browser_unavailable", 503)
        control = payload.get("control")
        if control is not None:
            if (type(control) is not dict or control.get("mode") not in {"agent", "takeover_pending", "human", "paused", "recovering"}
                    or type(control.get("revision")) is not int or control["revision"] < 1
                    or type(control.get("can_take")) is not bool):
                raise Rejected("browser_unavailable", 503)
            exposed = {key: control[key] for key in ("mode", "revision", "can_take")}
            if control.get("lease_id") is not None:
                try:
                    exposed["lease_id"] = _identifier(control["lease_id"])
                except HermesGatewayError:
                    raise Rejected("browser_unavailable", 503) from None
                expiry = control.get("lease_expires_at")
                if type(expiry) not in {int, float} or not math.isfinite(expiry):
                    raise Rejected("browser_unavailable", 503)
                exposed["lease_expires_at"] = expiry
                next_sequence = control.get("next_sequence")
                if type(next_sequence) is not int or next_sequence < 1:
                    raise Rejected("browser_unavailable", 503)
                exposed["next_sequence"] = next_sequence
            control = exposed
        viewport = payload.get("viewport")
        if viewport is not None and (type(viewport) is not dict or set(viewport) != {"width", "height"}
                or any(type(value) is not int or not 1 <= value <= 8192 for value in viewport.values())):
            raise Rejected("browser_unavailable", 503)
        page_context = payload.get("page_context") or {"current": None, "previous": None}
        if type(page_context) is not dict:
            raise Rejected("browser_unavailable", 503)
        title = payload.get("title")
        page = self._page({"url": payload.get("url"), "title": title})
        pending = self.store.pending(self.owner_id)
        return {"state": state, "generation": generation, "url": url, "title": page["title"],
            "control": control, "viewport": viewport,
            "page_context": {key: self._page(page_context.get(key)) for key in ("current", "previous")},
            "can_return": pending is None, "vault_enabled": self.credential_vault_enabled}

    def status(self, session, tab_id):
        return self._public(self._call(session, tab_id, "status"))

    def open(self, session, tab_id):
        return self._public(self._call(session, tab_id, "open", create=True))

    def control(self, session, tab_id, operation, values):
        if operation not in {"take", "heartbeat", "input", "pause", "close"}:
            raise Rejected("invalid_request", 422)
        payload = self._call(session, tab_id, "control/" + operation, values)
        if operation == "input":
            outcome = payload.get("outcome")
            if (outcome not in {"applied", "rejected", "uncertain", "reserved"}
                    or payload.get("sequence") != values.get("sequence")):
                raise Rejected("browser_input_uncertain", 409)
            return {"outcome": outcome, "sequence": payload["sequence"]}
        return self._public(payload)

    def frame(self, session, tab_id, generation):
        payload = self._call(session, tab_id, "frame", {"generation": generation})
        if payload.get("generation") != generation:
            raise Rejected("browser_changed", 409)
        received = payload.get("received_at")
        encoded = payload.get("jpeg")
        viewport = payload.get("viewport")
        try:
            valid = (type(received) in {int, float} and math.isfinite(received)
                and 0 <= received <= self.clock() + 30 and type(encoded) is str
                and len(encoded) <= 4 * ((MAX_FRAME_BYTES + 2) // 3)
                and type(viewport) is dict and set(viewport) == {"width", "height"}
                and all(type(v) is int and 1 <= v <= 8192 for v in viewport.values()))
            if not valid:
                raise ValueError
            jpeg = base64.b64decode(encoded, validate=True)
            frame_id = _identifier(payload.get("frame_id"))
            if not 4 <= len(jpeg) <= MAX_FRAME_BYTES or not jpeg.startswith(b"\xff\xd8\xff") or not jpeg.endswith(b"\xff\xd9"):
                raise ValueError
        except (ValueError, OverflowError, HermesGatewayError):
            raise Rejected("browser_unavailable", 503) from None
        return BrowserFrame(jpeg, generation, frame_id, float(received), None,
            self.store.browser_session(self.owner_id), width=viewport["width"], height=viewport["height"])

    def dispatch_data(self, session, tab_id, requested=None, *, use_previous=False):
        binding = self.binding(session, tab_id)
        result = {"browser_owner": {key: binding["owner"][key] for key in ("principal_id", "conversation_id")}}
        if requested is None:
            if use_previous:
                previous = self.status(session, tab_id).get("page_context", {}).get("previous")
                if previous is not None:
                    result["page"] = {**previous, "state": "previous"}
                    result["use_previous_browser"] = True
            return result
        if use_previous:
            raise Rejected("browser_context_changed", 409)
        if (type(requested) is not dict or set(requested) != {"generation", "revision", "lease_id"}
                or type(requested["revision"]) is not int or requested["revision"] < 1):
            raise Rejected("browser_context_changed", 409)
        status = self.status(session, tab_id)
        control = status.get("control") or {}
        if (status["state"] != "live" or requested.get("generation") != status["generation"]
                or requested.get("revision") != control.get("revision")
                or requested.get("lease_id") != control.get("lease_id")
                or control.get("mode") not in {"human", "agent"}
                or control.get("mode") == "human" and not requested.get("lease_id")):
            raise Rejected("browser_context_changed", 409)
        context = {**binding, **requested}
        run = self.store.browser_run(self.owner_id)
        if run and run.get("run_id"):
            context["previous_run_id"] = run["run_id"]
        result["browser_context"] = context
        result["page"] = {"url": status["url"], "title": status["title"]}
        return result

    def logins(self, session, tab_id, operation, values):
        if not self.credential_vault_enabled:
            raise Rejected("browser_vault_unavailable", 503)
        if operation not in {"list", "save", "remove"}:
            raise Rejected("invalid_request", 422)
        private = {key: values[key] for key in ("generation", "revision", "lease_id", "sequence")}
        if operation == "save":
            private["arguments"] = {key: values[key] for key in ("label", "identifier_type", "identifier", "password")}
        elif operation == "remove":
            private["arguments"] = {"handle": values["entry_id"]}
        payload = self._call(session, tab_id, "logins/" + operation, private)
        if (payload.get("success") is not True or payload.get("outcome") != "applied"
                or payload.get("sequence") != values.get("sequence")):
            raise Rejected("browser_vault_unavailable", 503)
        def item(value):
            if (type(value) is not dict or value.get("kind") != "login"
                    or value.get("identifier_type") not in {"email", "phone", "username"}
                    or any(type(value.get(key)) is not str or len(value[key]) > 512
                           or any(ord(c) < 32 for c in value[key]) for key in ("id", "label", "origin", "created_at", "identifier"))):
                raise Rejected("browser_vault_unavailable", 503)
            return {key: value[key] for key in ("id", "kind", "label", "origin", "created_at", "identifier_type", "identifier")}
        if operation == "list":
            items = payload.get("items")
            if type(items) is not list or len(items) > 1000:
                raise Rejected("browser_vault_unavailable", 503)
            return {"items": [item(value) for value in items]}
        if operation == "save":
            return {"item": item(payload.get("item"))}
        if type(payload.get("removed")) is not bool:
            raise Rejected("browser_vault_unavailable", 503)
        return {"removed": payload["removed"]}
