"""Owner-scoped observation of the browser a saved Hermes run already owns."""
from dataclasses import dataclass
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


class HermesBrowserClient:
    """Fixed private relay; no native stream port or browser input reaches the web."""
    def __init__(self, endpoint, bearer_token, *, transport=None, clock=time.time):
        self._runs = HermesRunsClient(endpoint, bearer_token, transport=transport,
            connect_timeout=2, read_timeout=3, request_deadline=5)
        self.clock = clock

    def close(self):
        self._runs.close()

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
