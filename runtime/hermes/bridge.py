"""Standalone Python 3.12 native bridge; no import of Radhouse's web package."""
from contextvars import ContextVar
from dataclasses import dataclass, field
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import stat
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

DOCUMENT_TOOLS = ("document_search", "document_read")
FILE_TOOLS = ("file_share",)
BROWSER_TOOLS = ("browser_navigate", "browser_snapshot", "browser_click", "browser_type",
                 "browser_scroll", "browser_back", "browser_press")
BROWSER_VIEW_STATUSES = frozenset(("queued", "running", "waiting_for_approval", "stopping",
                                   "completed", "failed", "cancelled", "interrupted"))
MAX_RESPONSE = 1024 * 1024
MAX_JPEG = 512 * 1024


@dataclass(frozen=True)
class DocumentRunContext:
    run_id: str
    session_id: str
    dispatch_key: str
    scope_token: str | None = field(repr=False)


_context = ContextVar("radhouse_document_run", default=None)
_callback = None
_browser_configuration = None
HOLD_PATH = Path("/var/lib/radhouse-maintenance/hold.json")
POLICY_PATH = Path("/etc/radhouse/builder-maintenance.json")
_maintenance_configuration = None
_network_policy = {"schema": "radhouse.browser-network-policy.v1", "verified": False,
                   "source": None, "verified_at": None, "enforcement": "vm_firewall",
                   "allowed": [], "denied": []}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("document_response_unavailable")


def bind_run_context(run_id, session_id, dispatch_key, scope_token):
    return _context.set(DocumentRunContext(run_id, session_id, dispatch_key, scope_token))


def reset_run_context(token):
    _context.reset(token)


def current_run_context(*, task_id=None, session_id=None, documents=False):
    context = _context.get()
    if (context is None or task_id is not None and task_id != context.session_id
            or session_id is not None and session_id != context.session_id
            or documents and not context.scope_token):
        raise ValueError("document_context_unavailable")
    return context


@dataclass(frozen=True)
class Callback:
    base_url: str
    ca_file: str
    tls_server_name: str

    def __post_init__(self):
        parsed = urlsplit(self.base_url)
        if (parsed.scheme != "https" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment or not Path(self.ca_file).is_file()
                or not _tls_identity(self.tls_server_name)):
            raise ValueError("invalid_document_callback")
        # Certificate verification and hostname checks remain on across the SSH forward.
        ssl.create_default_context(cafile=self.ca_file)

    def post(self, operation, context, arguments):
        body = {"run_id": context.run_id, "session_id": context.session_id,
                "dispatch_key": context.dispatch_key, **arguments}
        request = Request(self.base_url.rstrip("/") + "/internal/documents/" + operation,
                          data=json.dumps(body).encode(), method="POST",
                          headers={"Authorization": "Bearer " + context.scope_token,
                                   "Content-Type": "application/json"})
        context_tls = ssl.create_default_context(cafile=self.ca_file)
        server_name = self.tls_server_name
        class ForwardedTLS(http.client.HTTPSConnection):
            def connect(self):
                if self._tunnel_host:
                    raise ValueError("document_callback_unavailable")
                http.client.HTTPConnection.connect(self)  # TCP stays on the fixed loopback forward.
                self.sock = self._context.wrap_socket(self.sock, server_hostname=server_name)
        class PinnedIdentity(HTTPSHandler):
            def https_open(self, request):
                return self.do_open(ForwardedTLS, request, context=context_tls)
        client = build_opener(ProxyHandler({}), _NoRedirect(), PinnedIdentity())
        with client.open(request, timeout=20) as response:
            data = response.read(MAX_RESPONSE + 1)
        if len(data) > MAX_RESPONSE:
            raise ValueError("document_response_unavailable")
        value = json.loads(data)
        kinds = {"file"} if operation == "share" else {"catalog", "passages"}
        if type(value) is not dict or value.get("kind") not in kinds:
            raise ValueError("document_response_unavailable")
        return value


def _tls_identity(value):
    """Accept one explicit certificate identity from private plugin configuration."""
    if type(value) is not str or not value or len(value) > 253:
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                   for label in value.split("."))



def configure_documents(callback):
    global _callback
    if callback is not None and not isinstance(callback, Callback):
        raise ValueError("invalid_document_callback")
    _callback = callback


def features(adapter):
    try:
        from tools.registry import registry
        documents_registered = all((entry := registry.get_entry(name)) is not None
                                   and entry.handler.__module__ == __name__ for name in DOCUMENT_TOOLS)
        sharing_registered = all((entry := registry.get_entry(name)) is not None
                                and entry.handler.__module__ == __name__ for name in FILE_TOOLS)
    except Exception:
        documents_registered = sharing_registered = False
    return {
        "runs_document_scope": {"supported": _callback is not None and documents_registered,
            "durable": bool(adapter._run_idempotency_store.durable), "version": 1, "scope": "saved_turn_files"},
        "runs_file_share": {"supported": _callback is not None and documents_registered and sharing_registered,
            "version": 1},
        "runs_browser_view": {"supported": _browser_configuration is not None,
            "version": 1, "mode": "same_session_view_only"},
        "browser_network_policy": dict(_network_policy),
    }


def validate_admission(body, dispatch_key, durable):
    token = body.get("document_scope_token")
    names = set(body.get("allowed_tools") or ())
    uses_documents = bool(names.intersection(DOCUMENT_TOOLS))
    uses_browser = bool(names.intersection(BROWSER_TOOLS))
    uses_sharing = bool(names.intersection(FILE_TOOLS))
    scoped_session = type(body.get("session_id")) is str and 1 <= len(body["session_id"]) <= 512
    if token is not None and (type(token) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token)):
        return "invalid_document_scope"
    if bool(token) != uses_documents:
        return "document_scope_required" if uses_documents else "document_scope_without_tools"
    if uses_sharing and (not uses_documents or not set(DOCUMENT_TOOLS).issubset(names)):
        return "file_share_scope_required"
    if token and (not dispatch_key or not durable or _callback is None or not scoped_session
                  or body.get("disable_tools") or not set(DOCUMENT_TOOLS).issubset(names)
                  or not names.issubset(set(DOCUMENT_TOOLS + BROWSER_TOOLS + FILE_TOOLS))):
        return "document_scope_unavailable"
    if uses_browser and _browser_configuration is None:
        return "browser_view_unavailable"
    if uses_browser and (not dispatch_key or not durable or not scoped_session or body.get("disable_tools")
                         or not names.issubset(set(DOCUMENT_TOOLS + BROWSER_TOOLS + FILE_TOOLS))):
        return "browser_scope_unavailable"
    return None


def _arguments(operation, args):
    permitted = {"file_id", "cursor"} | ({"query"} if operation == "search" else {"locator"})
    if type(args) is not dict or set(args) - permitted:
        raise ValueError("document_arguments_invalid")
    file_id = args.get("file_id")
    if file_id is not None and (type(file_id) is not str or not re.fullmatch(
            r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", file_id)):
        raise ValueError("document_arguments_invalid")
    if operation == "search" and (file_id is None or type(args.get("query")) is not str
                                  or not args["query"].strip() or len(args["query"]) > 512):
        raise ValueError("document_arguments_invalid")
    if operation == "read" and file_id is None and args.get("locator") is not None:
        raise ValueError("document_arguments_invalid")
    for name, maximum in (("locator", 1024), ("cursor", 4096)):
        if args.get(name) is not None and (type(args[name]) is not str or len(args[name]) > maximum):
            raise ValueError("document_arguments_invalid")
    return dict(args)


def document_handler(operation, args, **trusted):
    try:
        context = current_run_context(task_id=trusted.get("task_id"), session_id=trusted.get("session_id"), documents=True)
        arguments = _arguments(operation, args)
        if _callback is None:
            raise ValueError("document_callback_unavailable")
        return json.dumps(_callback.post(operation, context, arguments), ensure_ascii=False)
    except Exception:
        # Vendor exceptions can contain paths, bearer values and uploaded content.
        return json.dumps({"error": "document_access_unavailable"})


def file_share_handler(args, **trusted):
    try:
        context = current_run_context(task_id=trusted.get("task_id"), session_id=trusted.get("session_id"), documents=True)
        if (type(args) is not dict or set(args) != {"name", "content"}
                or type(args["name"]) is not str or not 1 <= len(args["name"]) <= 200
                or re.search(r'[/\\\x00-\x1f\x7f]', args["name"])
                or type(args["content"]) is not str or _callback is None):
            raise ValueError("file_share_arguments_invalid")
        return json.dumps(_callback.post("share", context, dict(args)), ensure_ascii=False)
    except Exception:
        return json.dumps({"error": "file_share_unavailable"})


def register(ctx):
    global _callback, _browser_configuration, _maintenance_configuration, _network_policy
    previous = (_callback, _browser_configuration, _maintenance_configuration, _network_policy)
    try:
        _register(ctx)
    except Exception:
        _callback, _browser_configuration, _maintenance_configuration, _network_policy = previous
        # The pinned PluginManager rolls back registrations after register() raises.
        raise ValueError("radhouse_plugin_configuration_unverified") from None


def _register(ctx):
    callback = Callback(ctx.get_config("callback_base_url"), ctx.get_config("callback_ca_file"), ctx.get_config("callback_tls_server_name"))
    configure_documents(callback)
    for name in DOCUMENT_TOOLS:
        operation = name.removeprefix("document_")
        properties = {"file_id": {"type": "string"}, "cursor": {"type": "string"}}
        properties["query" if operation == "search" else "locator"] = {"type": "string"}
        schema = {"description": ("Search an attached original with literal text and source citations." if operation == "search"
                    else "Read an attached original at a source locator. Omit file_id to list the bounded file catalog; continue with its cursor."),
                  "parameters": {"type": "object", "properties": properties, "additionalProperties": False,
                                 "required": ["file_id", "query"] if operation == "search" else []}}
        def handler(args, _operation=operation, **trusted):
            return document_handler(_operation, args, **trusted)
        ctx.register_tool(name=name, toolset="radhouse_documents", schema=schema, handler=handler)
    ctx.register_tool(name="file_share", toolset="radhouse_documents", handler=file_share_handler,
        schema={"description": "Create and share a downloadable UTF-8 text file with the user. "
                    "Use for Markdown, CSV, JSON, code or plain text, not PDF, Office, image or audio files. "
                    "Only claim success after confirmation and use the returned download_url.",
                "parameters": {"type": "object", "properties": {
                    "name": {"type": "string"}, "content": {"type": "string"}},
                    "additionalProperties": False, "required": ["name", "content"]}})
    policy_hash, runtime_hash = ctx.get_config("maintenance_policy_sha256"), ctx.get_config("runtime_sha256")
    if policy_hash is not None or runtime_hash is not None:
        configure_maintenance(policy_hash, runtime_hash)
    browser_manifest = ctx.get_config("browser_manifest_path")
    if browser_manifest:
        manifest = json.loads(_root_file(Path(browser_manifest), 64 * 1024))
        configure_browser({key: manifest[key] for key in ("agent_browser_version", "agent_browser_path",
            "agent_browser_sha256", "chromium_path", "chromium_sha256", "sandbox_proof_sha256", "empty_config_path", "qualification_path", "runtime_sha256")})
    network_manifest = ctx.get_config("browser_network_policy_path")
    if network_manifest:
        configure_network_policy(json.loads(_root_file(Path(network_manifest), 16 * 1024)))


def configure_network_policy(value):
    """An informational firewall snapshot, never a grant or reachability promise."""
    global _network_policy
    required = {"schema", "verified", "source", "verified_at", "enforcement", "allowed", "denied"}
    if (type(value) is not dict or set(value) != required
            or value["schema"] != "radhouse.browser-network-policy.v1" or type(value["verified"]) is not bool
            or value["enforcement"] != "vm_firewall"):
        raise ValueError("browser_network_policy_invalid")
    for key in ("allowed", "denied"):
        if (type(value[key]) is not list or len(value[key]) > 16
                or any(type(item) is not str or not 1 <= len(item) <= 256 or any(not 32 <= ord(c) < 127 for c in item) for item in value[key])):
            raise ValueError("browser_network_policy_invalid")
    if value["source"] is not None and (type(value["source"]) is not str or not 1 <= len(value["source"]) <= 256
                                        or any(not 32 <= ord(c) < 127 for c in value["source"])):
        raise ValueError("browser_network_policy_invalid")
    if value["verified_at"] is not None:
        if (type(value["verified_at"]) is not str or len(value["verified_at"]) > 64
                or any(not 32 <= ord(c) < 127 for c in value["verified_at"])):
            raise ValueError("browser_network_policy_invalid")
        parsed = datetime.fromisoformat(value["verified_at"])
        if parsed.tzinfo is None or parsed.timestamp() > time.time() + 300:
            raise ValueError("browser_network_policy_invalid")
    if value["verified"] and (not value["source"] or not value["verified_at"]):
        raise ValueError("browser_network_policy_invalid")
    _network_policy = {**value, "allowed": list(value["allowed"]), "denied": list(value["denied"])}


def trusted_browser_instructions(instructions, names):
    if not set(names or ()).intersection(BROWSER_TOOLS):
        return instructions
    return (instructions or "") + "\n\nBrowser network information from the operator's configured VM firewall snapshot. " \
        "This is descriptive evidence with a source and freshness, not permission or a guarantee of reachability. " \
        "An unverified snapshot means effective firewall policy is unknown. Reachability does not authorize actions. " \
        + json.dumps(_network_policy, sort_keys=True, ensure_ascii=False)


def configure_maintenance(policy_sha256, runtime_sha256):
    global _maintenance_configuration
    if any(type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None for value in (policy_sha256, runtime_sha256)):
        raise ValueError("maintenance_configuration_unverified")
    _maintenance_configuration = (policy_sha256, runtime_sha256)


def _root_file(path, maximum):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("maintenance_hold_unverified")
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("maintenance_hold_unverified")
    return data


def _hold():
    try:
        raw = _root_file(HOLD_PATH, 4096)
    except FileNotFoundError:
        return None, None
    value = json.loads(raw)
    policy_raw = _root_file(POLICY_PATH, 64 * 1024)
    policy = json.loads(policy_raw)
    machine_id = policy.get("machine_id") if type(policy) is dict else None
    required = {"schema", "action", "machine_id", "cycle_id", "policy_sha256", "runtime_sha256", "boot_id", "created_at"}
    if (_maintenance_configuration is None or type(value) is not dict or set(value) != required
            or value["schema"] != "radhouse.builder-maintenance-hold.v1" or value["action"] != "weekly-maintenance"
            or type(machine_id) is not str or re.fullmatch(r"[a-f0-9]{32}", machine_id) is None
            or policy.get("schema") != "radhouse.builder-maintenance.v1"
            or value["machine_id"] != machine_id or Path("/etc/machine-id").read_text().strip() != machine_id
            or not re.fullmatch(r"[a-f0-9]{32}", value["cycle_id"])
            or (value["policy_sha256"], value["runtime_sha256"]) != _maintenance_configuration
            or hashlib.sha256(policy_raw).hexdigest() != value["policy_sha256"]):
        raise ValueError("maintenance_hold_unverified")
    if datetime.fromisoformat(value["created_at"]).tzinfo is None:
        raise ValueError("maintenance_hold_unverified")
    return value, hashlib.sha256(raw).hexdigest()


def maintenance_held():
    try:
        value, _ = _hold()
        return value is not None
    except Exception:
        return True  # Malformed/unknown/root-source drift holds are never ignored.


def maintenance_status(adapter):
    hold, valid = None, True
    try:
        hold, _ = _hold()
    except Exception:
        valid = False
    try:
        pending, inflight = adapter._pending_agent_requests, adapter._inflight_agent_runs
        if type(pending) is not int or type(inflight) is not int or min(pending, inflight) < 0:
            raise ValueError()
        active_runs = pending + inflight + sum(not task.done() for task in adapter._active_run_tasks.values())
        from tools import browser_tool as browser
        with browser._cleanup_lock:
            active_browsers = len(browser._active_sessions)
    except Exception:
        active_runs, active_browsers, valid = None, None, False
    return {"fenced": hold is not None or not valid, "active_runs": active_runs, "active_browsers": active_browsers,
            "cycle_id": hold["cycle_id"] if hold else None,
            "runtime_sha256": _maintenance_configuration[1] if _maintenance_configuration else None,
            "checked_at": datetime.now(timezone.utc).isoformat(), "verified": valid and _maintenance_configuration is not None}


async def handle_maintenance(adapter, request):
    from aiohttp import web
    error = adapter._check_auth(request)
    if error is not None:
        return error
    if request.remote not in {"127.0.0.1", "::1"}:
        return web.json_response({"error": "maintenance_loopback_required"}, status=403)
    try:
        result = maintenance_status(adapter)
        if request.method != "GET":
            arguments = await request.json()
            hold, digest = _hold()
            if (type(arguments) is not dict or set(arguments) != {"cycle_id", "hold_sha256"}
                    or hold is None or hold["cycle_id"] != arguments["cycle_id"] or digest != arguments["hold_sha256"]
                    or not result["verified"]):
                return web.json_response({"error": "maintenance_unverified"}, status=409)
            # Release authorizes the root helper to remove its matching hold after
            # its pinned restart proof. This service never deletes a root-owned hold.
            result["released"] = request.path.endswith("/release")
        return web.json_response(result, headers={"Cache-Control": "no-store"})
    except Exception:
        return web.json_response({"error": "maintenance_unverified"}, status=409)


def http_url(url):
    try:
        parsed = urlsplit(url)
        if (type(url) is not str or any(ord(character) < 32 for character in url)
                or parsed.scheme not in {"https", "http"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.port is not None and not 1 <= parsed.port <= 65535):
            return False
        return True
    except (ValueError, TypeError):
        return False


def configure_browser(configuration):
    """Installation supplies exact verified pins/isolation evidence; never infer from npm ranges."""
    global _browser_configuration
    if configuration is None:
        _browser_configuration = None
        return
    required = {"agent_browser_version", "agent_browser_path", "agent_browser_sha256",
                "chromium_path", "chromium_sha256", "sandbox_proof_sha256", "empty_config_path", "qualification_path", "runtime_sha256"}
    if (type(configuration) is not dict or set(configuration) != required
            or re.fullmatch(r"\d+\.\d+\.\d+", configuration["agent_browser_version"]) is None
            or any(re.fullmatch(r"[a-f0-9]{64}", configuration[key]) is None
                   for key in ("agent_browser_sha256", "chromium_sha256", "sandbox_proof_sha256", "runtime_sha256"))):
        raise ValueError("browser_installation_unverified")
    for prefix in ("agent_browser", "chromium"):
        digest = hashlib.sha256()
        with Path(configuration[prefix + "_path"]).open("rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError("browser_installation_unverified")
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != configuration[prefix + "_sha256"]:
            raise ValueError("browser_installation_unverified")
    if json.loads(_root_file(Path(configuration["empty_config_path"]), 4096)) != {}:
        raise ValueError("browser_installation_unverified")
    proof_raw = _root_file(Path(configuration["qualification_path"]), 16 * 1024)
    proof = json.loads(proof_raw)
    if (hashlib.sha256(proof_raw).hexdigest() != configuration["sandbox_proof_sha256"]
            or proof.get("state") != "qualified" or proof.get("same_session_frame_progression") is not True or proof.get("sandbox_enabled") is not True
            or proof.get("origin_guard_verified") is not True or proof.get("runtime_sha256") != configuration["runtime_sha256"]
            or proof.get("view_only_input_ignored") is not True
            or proof.get("chrome_control_guard_verified") is not True
            or proof.get("agent_browser_version") != configuration["agent_browser_version"]
            or proof.get("agent_browser_sha256") != configuration["agent_browser_sha256"]
            or proof.get("chromium_sha256") != configuration["chromium_sha256"]):
        raise ValueError("browser_installation_unverified")
    _browser_configuration = dict(configuration)


def bridge_run_active():
    return _context.get() is not None


def browser_available(name):
    return name in BROWSER_TOOLS and _browser_configuration is not None


def retain_browser_after_turn(task_id):
    """Only the normal turn finalizer may retain this qualified, owned session.

    Idle, shutdown and explicit teardown call the native lifecycle directly.
    Reading this predicate never creates a session or refreshes its idle timer.
    """
    context = _context.get()
    if context is None or context.session_id != task_id or _browser_configuration is None:
        return False
    try:
        from tools import browser_tool as browser
        with browser._cleanup_lock:
            record = browser._active_sessions.get(task_id)
            if not record:
                return False
            features = record.get("features", {})
            return (record.get("session_key") == task_id and record.get("owner_task_id") == task_id
                    and features.get("local") is True and features.get("radhouse_owned") is True
                    and not features.get("real_profile") and not features.get("lightpanda")
                    and not record.get("cdp_url") and not record.get("bb_session_id")
                    and re.fullmatch(r"h_[a-f0-9]{10}", record.get("session_name", "")) is not None)
    except (AttributeError, TypeError):
        return False


def browser_argv():
    if not bridge_run_active():
        return None
    if _browser_configuration is None:
        raise ValueError("browser_installation_unverified")
    return [_browser_configuration["agent_browser_path"], "--config", _browser_configuration["empty_config_path"],
            "--executable-path", _browser_configuration["chromium_path"]]


def browser_environment(environment):
    if not bridge_run_active():
        return environment
    if _browser_configuration is None:
        raise ValueError("browser_installation_unverified")
    # No provider, callback, scope bearer, profile/CDP/state or inherited browser settings.
    clean = {key: value for key, value in environment.items()
             if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "XDG_RUNTIME_DIR"}}
    clean["AGENT_BROWSER_EXECUTABLE_PATH"] = _browser_configuration["chromium_path"]
    clean["AGENT_BROWSER_ARGS"] = "--disable-extensions"
    return clean


def checked_browser_call(name, arguments, trusted, fallback):
    try:
        current_run_context(task_id=trusted.get("task_id"), session_id=trusted.get("session_id"))
        if name not in BROWSER_TOOLS or _browser_configuration is None:
            raise ValueError("browser_scope_unavailable")
        properties = {"browser_navigate": {"url"}, "browser_snapshot": {"full"}, "browser_click": {"ref"},
                      "browser_type": {"ref", "text"}, "browser_scroll": {"direction"}, "browser_back": set(), "browser_press": {"key"}}
        if type(arguments) is not dict or set(arguments) - properties[name]:
            raise ValueError("browser_arguments_invalid")
        if name in {"browser_click", "browser_type"} and (type(arguments.get("ref")) is not str
                or re.fullmatch(r"@?e[0-9]{1,12}", arguments["ref"]) is None):
            raise ValueError("browser_arguments_invalid")
        if name == "browser_type" and (type(arguments.get("text")) is not str or "\x00" in arguments["text"]):
            raise ValueError("browser_arguments_invalid")
        if name == "browser_press" and (type(arguments.get("key")) is not str or not arguments["key"]
                or arguments["key"].startswith("-") or len(arguments["key"]) > 128
                or any(ord(character) < 32 for character in arguments["key"])):
            raise ValueError("browser_arguments_invalid")
        if name == "browser_snapshot" and "full" in arguments and type(arguments["full"]) is not bool:
            raise ValueError("browser_arguments_invalid")
        if name == "browser_scroll" and arguments.get("direction") not in {"up", "down"}:
            raise ValueError("browser_arguments_invalid")
        from tools import browser_tool as browser
        if not browser._cloud._is_local_mode():
            raise ValueError("browser_scope_unavailable")
        if name == "browser_navigate" and not http_url(arguments.get("url")):
            raise ValueError("browser_scope_unavailable")
        # The fixed native fallback bypasses personal browser-extension routing.
        return fallback()
    except Exception:
        return json.dumps({"error": "browser_access_unavailable"})


def _session_stream(session_id):
    # Reading a view never calls _get_session_info or launches a browser.
    from tools import browser_tool as browser
    with browser._cleanup_lock:
        record = browser._active_sessions.get(session_id)
        if not record:
            return None
        record = dict(record)
    features = record.get("features", {})
    name = record.get("session_name", "")
    if (not features.get("local") or not features.get("radhouse_owned") or features.get("real_profile") or record.get("cdp_url")
            or not re.fullmatch(r"h_[a-f0-9]{10}", name)):
        raise ValueError("browser_session_unavailable")
    directory = Path(browser._socket_safe_tmpdir()) / ("agent-browser-" + name)
    try:
        info = directory.lstat()
    except FileNotFoundError:
        return None  # The retained native session was retired; observation cannot recreate it.
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("browser_session_unavailable")
    path = directory / (name + ".stream")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None  # Native idle shutdown may precede Hermes's session-cache cleanup.
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("browser_session_unavailable")
        port = stream.read(17).strip()
    if not port.isdigit() or not 1024 <= int(port) <= 65535:
        raise ValueError("browser_session_unavailable")
    generation = hashlib.sha256(f"{name}:{info.st_ino}:{info.st_mtime_ns}".encode()).hexdigest()[:32]
    return int(port), generation


_relays = {}


class NativeRelay:
    """One read-only connection to an existing native generation; no browser/input creation."""
    def __init__(self, session_id, port, generation, *, current=None):
        self.session_id, self.port, self.generation = session_id, port, generation
        self.connected, self.screencasting, self.url, self.frame = False, False, None, None
        self.current = current or (lambda: _session_stream(self.session_id))
        self.changed = asyncio.Event()
        self.task = asyncio.create_task(self.listen())

    def ingest(self, value):
        if type(value) is not dict:
            raise ValueError("browser_stream_unavailable")
        if value.get("type") == "status":
            self.connected = value.get("connected") is True
            self.screencasting = value.get("screencasting") is True
            if not self.connected:
                self.frame = None
        elif value.get("type") in {"tabs", "url"}:
            if value["type"] == "url":
                url = value.get("url")
                self.frame = None  # Never relabel a prior document frame as the new page.
                if not http_url(url):
                    self.url, self.frame = None, None
                else:
                    parts = urlsplit(url)
                    self.url = parts._replace(query="", fragment="").geturl()
                self.changed.set()
                return
            tabs = value.get("tabs")
            if type(tabs) is not list or not tabs or any(type(tab) is not dict for tab in tabs):
                raise ValueError("browser_stream_unavailable")
            active = next((tab for tab in tabs if tab.get("active")), tabs[0])
            url = active.get("url")
            if not http_url(url):
                self.url, self.frame = None, None
            else:
                parts = urlsplit(url)
                safe_url = parts._replace(query="", fragment="").geturl()
                if self.url != safe_url:
                    self.frame = None
                self.url = safe_url
        elif value.get("type") == "frame":
            if type(value.get("data")) is not str or len(value["data"]) > (MAX_JPEG * 4 // 3 + 4):
                raise ValueError("browser_frame_unavailable")
            jpeg = base64.b64decode(value["data"], validate=True)
            if not jpeg.startswith(b"\xff\xd8\xff") or len(jpeg) > MAX_JPEG:
                raise ValueError("browser_frame_unavailable")
            # v0.26's CDP timestamp conversion can produce0. Never invent capture time.
            self.frame = {"jpeg": base64.b64encode(jpeg).decode(), "received_at": time.time(),
                          "captured_at": None, "frame_id": hashlib.sha256(jpeg).hexdigest()[:32]}
        self.changed.set()

    async def listen(self):
        import aiohttp
        try:
            async with aiohttp.ClientSession(trust_env=False) as client:
                async with client.ws_connect(f"http://127.0.0.1:{self.port}", timeout=3,
                                             max_msg_size=MAX_RESPONSE) as channel:
                    while self.current() == (self.port, self.generation):
                        try:
                            message = await channel.receive(timeout=1)
                        except asyncio.TimeoutError:
                            continue  # Stationary pages keep their actual native frame.
                        if message.type == aiohttp.WSMsgType.TEXT:
                            self.ingest(json.loads(message.data))
                        elif message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                            break
        except Exception:
            pass
        finally:
            self.connected, self.screencasting, self.url, self.frame = False, False, None, None
            self.changed.set()
            if _relays.get(self.session_id) is self:
                _relays.pop(self.session_id, None)

    async def snapshot(self, want_frame):
        deadline = asyncio.get_running_loop().time() + 3
        while True:
            self.changed.clear()
            if self.connected and self.screencasting and self.url and (self.frame or not want_frame):
                return {"url": self.url, **(self.frame if want_frame else {})}
            if self.task.done():
                raise ValueError("browser_stream_unavailable")
            await asyncio.wait_for(self.changed.wait(), max(0.001, deadline - asyncio.get_running_loop().time()))


async def _native_frame(port, *, want_frame, session_id, generation):
    relay = _relays.get(session_id)
    if relay is None or relay.port != port or relay.generation != generation:
        if relay:
            relay.task.cancel()
        if len(_relays) >= 16 and session_id not in _relays:
            raise ValueError("browser_relay_capacity")
        relay = _relays[session_id] = NativeRelay(session_id, port, generation)
    return await relay.snapshot(want_frame)


async def handle_browser(adapter, request, *, frame=False, api_server):
    from aiohttp import web
    from gateway.platforms.api_server_runs import _load_owned_run
    run_id, status, _, _, error = _load_owned_run(adapter, request, _api_server=api_server,
                                               permission="status", active_fallback=False)
    if error is not None:
        return error
    session_id = status.get("session_id")
    # The pinned resolver returns a live cached dict. Freeze these identities
    # before awaiting native data so in-place updates cannot evade revalidation.
    names = list(status.get("allowed_tools", []))
    dispatch_key = status.get("dispatch_key")
    base = {"run_id": run_id, "session_id": session_id}
    if (_browser_configuration is None or not session_id or not set(names).intersection(BROWSER_TOOLS)
            or status.get("status") not in BROWSER_VIEW_STATUSES):
        return web.json_response({**base, "state": "unavailable", "generation": None, "url": None}, status=409 if frame else 200)
    try:
        stream = _session_stream(session_id)
        if stream is None:
            return web.json_response({**base, "state": "idle", "generation": None, "url": None}, status=409 if frame else 200)
        port, generation = stream
        result = await _native_frame(port, want_frame=frame, session_id=session_id, generation=generation)
        if _session_stream(session_id) != stream:
            raise ValueError("browser_generation_changed")
        _, after, _, _, error = _load_owned_run(adapter, request, _api_server=api_server,
                                              permission="status", active_fallback=False)
        if (error is not None or after.get("session_id") != session_id or after.get("allowed_tools") != names
                or after.get("dispatch_key") != dispatch_key
                or after.get("status") not in BROWSER_VIEW_STATUSES):
            raise ValueError("browser_run_changed")
        if frame:
            return web.json_response({**base, "generation": generation,
                **{key: result[key] for key in ("jpeg", "received_at", "captured_at", "frame_id")}}, headers={"Cache-Control": "no-store"})
        return web.json_response({**base, "state": "live", "generation": generation, "url": result["url"]}, headers={"Cache-Control": "no-store"})
    except Exception:
        try:
            retired = _session_stream(session_id) is None
        except Exception:
            retired = False
        return web.json_response({**base, "state": "idle" if retired else "unavailable", "generation": None, "url": None}, status=409 if frame else 200,
                                 headers={"Cache-Control": "no-store"})
