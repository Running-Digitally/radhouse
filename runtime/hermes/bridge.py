"""Standalone Python 3.12 native bridge; no import of Radhouse's web package."""
import asyncio
import base64
import hashlib
import http.client
import ipaddress
import json
import os
import re
import ssl
import stat
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

DOCUMENT_TOOLS = ("document_search", "document_read")
FILE_TOOLS = ("file_share",)
BROWSER_TOOLS = ("browser_navigate", "browser_snapshot", "browser_click", "browser_type",
                 "browser_scroll", "browser_back", "browser_press")
LOGIN_TOOLS = ("browser_login_list", "browser_login_fill")
SCOPED_TOOLS = DOCUMENT_TOOLS + FILE_TOOLS + BROWSER_TOOLS + LOGIN_TOOLS
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
    browser_owner: dict | None = field(default=None, repr=False)


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


def bind_run_context(run_id, session_id, dispatch_key, scope_token, browser_owner=None):
    return _context.set(
        DocumentRunContext(run_id, session_id, dispatch_key, scope_token, browser_owner)
    )


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

        documents_registered = all(
            (entry := registry.get_entry(name)) is not None
            and entry.handler.__module__ == __name__
            for name in DOCUMENT_TOOLS
        )
        sharing_registered = all(
            (entry := registry.get_entry(name)) is not None
            and entry.handler.__module__ == __name__
            for name in FILE_TOOLS
        )
    except Exception:
        documents_registered = sharing_registered = False
    return {
        "runs_document_scope": {
            "supported": _callback is not None and documents_registered,
            "durable": bool(adapter._run_idempotency_store.durable),
            "version": 1,
            "scope": "saved_turn_files",
        },
        "runs_file_share": {
            "supported": _callback is not None
            and documents_registered
            and sharing_registered,
            "version": 1,
        },
        "runs_browser_view": {
            "supported": _browser_configuration is not None,
            "version": 1,
            "mode": "same_session_view_only",
        },
        "runs_browser_control": {
            "supported": _controller is not None,
            "version": 1,
            "mode": "owner_session",
        },
        "browser_credential_vault": {
            "supported": _controller is not None and _vault is not None,
            "version": 1,
            "scope": "local_login_only",
        },
        "browser_network_policy": dict(_network_policy),
    }


def validate_admission(body, dispatch_key, durable):
    token = body.get("document_scope_token")
    names = set(body.get("allowed_tools") or ())
    uses_documents = bool(names.intersection(DOCUMENT_TOOLS))
    uses_browser = bool(names.intersection(BROWSER_TOOLS + LOGIN_TOOLS))
    uses_sharing = bool(names.intersection(FILE_TOOLS))
    scoped_session = (
        type(body.get("session_id")) is str and 1 <= len(body["session_id"]) <= 512
    )
    if token is not None and (
        type(token) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
    ):
        return "invalid_document_scope"
    if bool(token) != uses_documents:
        return (
            "document_scope_required"
            if uses_documents
            else "document_scope_without_tools"
        )
    if uses_sharing and (not uses_documents or not set(DOCUMENT_TOOLS).issubset(names)):
        return "file_share_scope_required"
    if token and (
        not dispatch_key
        or not durable
        or _callback is None
        or not scoped_session
        or body.get("disable_tools")
        or not set(DOCUMENT_TOOLS).issubset(names)
        or not names.issubset(
            set(DOCUMENT_TOOLS + BROWSER_TOOLS + FILE_TOOLS + LOGIN_TOOLS)
        )
    ):
        return "document_scope_unavailable"
    if uses_browser and _browser_configuration is None:
        return "browser_view_unavailable"
    if uses_browser and (
        not dispatch_key
        or not durable
        or not scoped_session
        or body.get("disable_tools")
        or not names.issubset(
            set(DOCUMENT_TOOLS + BROWSER_TOOLS + FILE_TOOLS + LOGIN_TOOLS)
        )
    ):
        return "browser_scope_unavailable"
    if names.intersection(LOGIN_TOOLS) and _vault is None:
        return "browser_login_unavailable"
    owner = body.get("browser_owner")
    if owner is not None and (
        type(owner) is not dict
        or set(owner) != {"conversation_id", "principal_id"}
        or any(
            type(value) is not str or not 1 <= len(value) <= 512
            for value in owner.values()
        )
    ):
        return "browser_scope_unavailable"
    if uses_browser and _controller is not None and owner is None:
        return "browser_owner_required"
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
    global \
        _callback, \
        _browser_configuration, \
        _maintenance_configuration, \
        _network_policy, \
        _controller, \
        _vault
    previous = (
        _callback,
        _browser_configuration,
        _maintenance_configuration,
        _network_policy,
        _controller,
        _vault,
    )
    try:
        _register(ctx)
    except Exception:
        (
            _callback,
            _browser_configuration,
            _maintenance_configuration,
            _network_policy,
            _controller,
            _vault,
        ) = previous
        # The pinned PluginManager rolls back registrations after register() raises.
        raise ValueError("radhouse_plugin_configuration_unverified") from None


def _register(ctx):
    callback = Callback(
        ctx.get_config("callback_base_url"),
        ctx.get_config("callback_ca_file"),
        ctx.get_config("callback_tls_server_name"),
    )
    configure_documents(callback)
    for name in DOCUMENT_TOOLS:
        operation = name.removeprefix("document_")
        properties = {"file_id": {"type": "string"}, "cursor": {"type": "string"}}
        properties["query" if operation == "search" else "locator"] = {"type": "string"}
        schema = {
            "description": (
                "Search an attached original with literal text and source citations."
                if operation == "search"
                else "Read an attached original at a source locator. Omit file_id to list the bounded file catalog; continue with its cursor."
            ),
            "parameters": {
                "type": "object",
                "properties": properties,
                "additionalProperties": False,
                "required": ["file_id", "query"] if operation == "search" else [],
            },
        }

        def handler(args, _operation=operation, **trusted):
            return document_handler(_operation, args, **trusted)

        ctx.register_tool(
            name=name, toolset="radhouse_documents", schema=schema, handler=handler
        )
    ctx.register_tool(
        name="file_share",
        toolset="radhouse_documents",
        handler=file_share_handler,
        schema={
            "description": "Create and share a downloadable UTF-8 text file with the user. "
            "Use for Markdown, CSV, JSON, code or plain text, not PDF, Office, image or audio files. "
            "Only claim success after confirmation and use the returned download_url.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "content": {"type": "string"},
                },
                "additionalProperties": False,
                "required": ["name", "content"],
            },
        },
    )
    policy_hash, runtime_hash = (
        ctx.get_config("maintenance_policy_sha256"),
        ctx.get_config("runtime_sha256"),
    )
    if policy_hash is not None or runtime_hash is not None:
        configure_maintenance(policy_hash, runtime_hash)
    browser_manifest = ctx.get_config("browser_manifest_path")
    if browser_manifest:
        manifest = json.loads(_root_file(Path(browser_manifest), 64 * 1024))
        configure_browser(
            {
                key: manifest[key]
                for key in (
                    "agent_browser_version",
                    "agent_browser_path",
                    "agent_browser_sha256",
                    "chromium_path",
                    "chromium_sha256",
                    "sandbox_proof_sha256",
                    "empty_config_path",
                    "qualification_path",
                    "runtime_sha256",
                )
            }
        )
    network_manifest = ctx.get_config("browser_network_policy_path")
    if network_manifest:
        configure_network_policy(
            json.loads(_root_file(Path(network_manifest), 16 * 1024))
        )
    control_store = ctx.get_config("browser_control_store")
    if control_store:
        configure_control(
            control_store, profile_home=ctx.get_config("browser_vault_home")
        )
        if _vault is not None:
            from radhouse_vault_bridge import LOGIN_TOOL_DEFINITIONS

            for definition in LOGIN_TOOL_DEFINITIONS:
                name = definition["name"]
                schema = {
                    key: value for key, value in definition.items() if key != "name"
                }

                def handler(args, _name=name, **trusted):
                    return login_tool_handler(_name, args, **trusted)

                ctx.register_tool(
                    name=name,
                    toolset="radhouse_documents",
                    schema=schema,
                    handler=handler,
                )


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
        pending, inflight = (
            adapter._pending_agent_requests,
            adapter._inflight_agent_runs,
        )
        if (
            type(pending) is not int
            or type(inflight) is not int
            or min(pending, inflight) < 0
        ):
            raise ValueError()
        active_agent_runs = (
            pending
            + inflight
            + sum(not task.done() for task in adapter._active_run_tasks.values())
        )
        from tools import browser_tool as browser

        with browser._cleanup_lock:
            active_browsers = len(browser._active_sessions)
        from radhouse_owner_terminal import owner_terminal_active_count
        active_terminals = owner_terminal_active_count()
        if type(active_terminals) is not int or active_terminals < 0:
            raise ValueError()
        # Existing maintenance consumers use active_runs as a zero-work gate,
        # not a distinct-conversation count. Include human shells so the pinned
        # weekly updater defers; retain separate, truthful component counts.
        active_runs = active_agent_runs + active_terminals
        if _controller is not None:
            observed = []
            for state in _controller.live_states():
                owned, current = _current_owned(
                    state.identity.conversation_id,
                    state.identity.session_id,
                    state.principal_id,
                )
                if owned is not None:
                    observed.append(owned.identity)
            snapshot = _controller.activity_snapshot(observed)
            valid = valid and snapshot.known
            active_browsers = max(active_browsers, snapshot.active_browsers)
            if snapshot.active_commands or snapshot.recovering:
                valid = False
    except Exception:
        active_runs, active_agent_runs, active_browsers, active_terminals, valid = None, None, None, None, False
    return {
        "fenced": hold is not None or not valid,
        "active_runs": active_runs,
        "active_agent_runs": active_agent_runs,
        "active_browsers": active_browsers,
        "active_terminals": active_terminals,
        "cycle_id": hold["cycle_id"] if hold else None,
        "runtime_sha256": _maintenance_configuration[1]
        if _maintenance_configuration
        else None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "verified": valid and _maintenance_configuration is not None,
    }


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
        current_run_context(
            task_id=trusted.get("task_id"), session_id=trusted.get("session_id")
        )
        if name not in BROWSER_TOOLS or _browser_configuration is None:
            raise ValueError("browser_scope_unavailable")
        properties = {
            "browser_navigate": {"url"},
            "browser_snapshot": {"full"},
            "browser_click": {"ref"},
            "browser_type": {"ref", "text"},
            "browser_scroll": {"direction"},
            "browser_back": set(),
            "browser_press": {"key"},
        }
        if type(arguments) is not dict or set(arguments) - properties[name]:
            raise ValueError("browser_arguments_invalid")
        if name in {"browser_click", "browser_type"} and (
            type(arguments.get("ref")) is not str
            or re.fullmatch(r"@?e[0-9]{1,12}", arguments["ref"]) is None
        ):
            raise ValueError("browser_arguments_invalid")
        if name == "browser_type" and (
            type(arguments.get("text")) is not str or "\x00" in arguments["text"]
        ):
            raise ValueError("browser_arguments_invalid")
        if name == "browser_press" and (
            type(arguments.get("key")) is not str
            or not arguments["key"]
            or arguments["key"].startswith("-")
            or len(arguments["key"]) > 128
            or any(ord(character) < 32 for character in arguments["key"])
        ):
            raise ValueError("browser_arguments_invalid")
        if (
            name == "browser_snapshot"
            and "full" in arguments
            and type(arguments["full"]) is not bool
        ):
            raise ValueError("browser_arguments_invalid")
        if name == "browser_scroll" and arguments.get("direction") not in {
            "up",
            "down",
        }:
            raise ValueError("browser_arguments_invalid")
        from tools import browser_tool as browser

        if not browser._cloud._is_local_mode():
            raise ValueError("browser_scope_unavailable")
        if name == "browser_navigate" and not http_url(arguments.get("url")):
            raise ValueError("browser_scope_unavailable")
        # Preserve upstream policy/formatters, changing only its admitted transport.
        if _controller is not None:
            with agent_browser_operation(current_run_context()) as owned:
                result = fallback()
                return json.dumps(_redacted(json.loads(result)), ensure_ascii=False)
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
                self.frame = (
                    None  # Never relabel a prior document frame as the new page.
                )
                if url != "about:blank" and not http_url(url):
                    self.url, self.frame = None, None
                else:
                    parts = urlsplit(url)
                    self.url = parts._replace(query="", fragment="").geturl()
                self.changed.set()
                return
            tabs = value.get("tabs")
            if (
                type(tabs) is not list
                or not tabs
                or any(type(tab) is not dict for tab in tabs)
            ):
                raise ValueError("browser_stream_unavailable")
            active = next((tab for tab in tabs if tab.get("active")), tabs[0])
            url = active.get("url")
            if url != "about:blank" and not http_url(url):
                self.url, self.frame = None, None
            else:
                parts = urlsplit(url)
                safe_url = parts._replace(query="", fragment="").geturl()
                if self.url != safe_url:
                    self.frame = None
                self.url = safe_url
        elif value.get("type") == "frame":
            if type(value.get("data")) is not str or len(value["data"]) > (
                MAX_JPEG * 4 // 3 + 4
            ):
                raise ValueError("browser_frame_unavailable")
            jpeg = base64.b64decode(value["data"], validate=True)
            if not jpeg.startswith(b"\xff\xd8\xff") or len(jpeg) > MAX_JPEG:
                raise ValueError("browser_frame_unavailable")
            # v0.26's CDP timestamp conversion can produce0. Never invent capture time.
            self.frame = {
                "jpeg": base64.b64encode(jpeg).decode(),
                "received_at": time.time(),
                "captured_at": None,
                "frame_id": hashlib.sha256(jpeg).hexdigest()[:32],
            }
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


# Session-owned control integration; this file is appended to the pinned standalone bridge.
import subprocess
import threading
from contextlib import contextmanager
from uuid import uuid4

_controller = None
_vault = None
_owned_browsers = {}
_browser_lock = threading.RLock()
_browser_operation = ContextVar("radhouse_browser_operation", default=None)


def _control_modules():
    import radhouse_browser_control as control
    import radhouse_native_control as native

    return control, native


def configure_control(store_path, *, profile_home):
    global _controller, _vault
    control, _ = _control_modules()
    _controller = control.BrowserController(
        store_path, maintenance_held=maintenance_held
    )
    _controller.recover_startup()
    if profile_home:
        from radhouse_vault_bridge import VaultBridge

        _vault = VaultBridge(profile_home)


def _redacted(value):
    from agent.redact import redact_sensitive_text

    if isinstance(value, str):
        return redact_sensitive_text(value, force=True)
    if isinstance(value, list):
        return [_redacted(item) for item in value]
    if isinstance(value, dict):
        return {_redacted(key): _redacted(item) for key, item in value.items()}
    return value


def _private_owner(body):
    control, _ = _control_modules()
    raw = body.get("owner")
    if type(raw) is not dict or set(raw) != {
        "principal_id",
        "conversation_id",
        "auth_session_digest",
        "binding_revision",
        "tab_id",
    }:
        raise control.ControlRejected("invalid_binding")
    owner = control.OwnerBinding(
        **{k: v for k, v in raw.items() if k != "conversation_id"}
    )
    control._identifier(raw["conversation_id"])
    expiry = body.get("auth_expires_at")
    if (
        type(expiry) not in (int, float)
        or not __import__("math").isfinite(expiry)
        or expiry <= time.time()
    ):
        raise control.ControlRejected("authentication_expired")
    return owner, raw["conversation_id"], expiry


def _pid_gone(pid, started):
    import psutil

    try:
        process = psutil.Process(pid)
        return (
            process.create_time() != started or process.status() == psutil.STATUS_ZOMBIE
        )
    except psutil.NoSuchProcess:
        return True


class OwnedBrowser:
    def __init__(self, identity, record, pid, started, channel):
        self.identity, self.record = identity, record
        self.pid, self.started, self.channel = pid, started, channel
        self.last_handle = None
        self.operation_lock = threading.RLock()
        self.current_page = self.previous_page = None
        self.viewport = None

    def handle(self, handle, timeout=45):
        self.last_handle = handle
        return handle.result(timeout)

    def metadata(self):
        result = self.handle(self.channel.submit_metadata(uuid4().hex))
        if not result.legacy["success"]:
            _, native = _control_modules()
            raise native.NativeRejected("browser_metadata_unavailable")
        value = result.legacy["data"].get("result")
        if type(value) is not dict or value.keys() != {
            "url",
            "title",
            "width",
            "height",
        }:
            raise ValueError("browser_metadata_unavailable")
        if value["url"] != "about:blank" and not http_url(value["url"]):
            raise ValueError("browser_metadata_unavailable")
        if any(
            type(value[k]) is not int or not 1 <= value[k] <= 16384
            for k in ("width", "height")
        ):
            raise ValueError("browser_metadata_unavailable")
        # Redact exact native values before normalization or truncation can change them.
        safe = _redacted({"url": value["url"], "title": str(value["title"])})
        url = urlsplit(safe["url"])._replace(query="", fragment="").geturl()[:2048]
        title = " ".join(re.sub(r"[\x00-\x1f\x7f]+", " ", safe["title"]).split())[:512]
        page = {"url": url, "title": title}
        if self.current_page and self.current_page["url"] != page["url"]:
            self.previous_page = self.current_page
        self.current_page, self.viewport = (
            page,
            {"width": value["width"], "height": value["height"]},
        )
        _controller.record_page(self.identity, self.current_page, self.previous_page)
        return page

    def evaluate(self, expression, *, secret=False):
        # Both secret and inspection expressions are private fixed adapter operations.
        result = self.handle(
            self.channel.submit_trusted_evaluation(uuid4().hex, expression)
        )
        if not result.legacy["success"]:
            _, native = _control_modules()
            raise native.NativeRejected("browser_evaluation_failed")
        return result.legacy["data"].get("result")

    def current_origin(self):
        result = self.evaluate("location.origin")
        if type(result) is not str or not http_url(result):
            raise ValueError("browser_origin_unavailable")
        return result


def _current_owned(conversation_id, session_id, principal_id):
    control, _ = _control_modules()
    state = _controller.current(conversation_id, session_id, principal_id)
    if state is None or state.retired:
        return None, state
    owned = _owned_browsers.get(session_id)
    if owned and owned.identity != state.identity:
        raise control.ControlRejected("stale_browser")
    pid, started = (
        (owned.pid, owned.started)
        if owned
        else (state.native_pid, state.native_started)
    )
    # Stream files may briefly outlive a daemon. Positive process retirement comes first.
    if pid and started and _pid_gone(pid, started):
        if owned:
            owned.channel.close()
            from tools import browser_tool_lifecycle as lifecycle

            lifecycle._release_session_resources(session_id, owned.record)
        _controller.retire_browser(
            state.identity, control.RetirementObservation(state.identity, True, True)
        )
        _owned_browsers.pop(session_id, None)
        from tools import browser_tool as browser

        with browser._cleanup_lock:
            browser._active_sessions.pop(session_id, None)
        return None, _controller.state(state.identity)
    stream = _session_stream(session_id)
    if owned and stream is not None:
        if stream[1] != state.identity.generation:
            raise control.ControlRejected("stale_browser")
        return owned, state
    raise control.ControlRejected("browser_retirement_unproven")


def _launch_owned(conversation_id, session_id, principal_id, *, run=None):
    control, native = _control_modules()
    import psutil
    from tools import browser_tool as browser
    from tools import browser_tool_lifecycle as lifecycle
    from tools import browser_tool_session as session

    with _browser_lock:
        owned, state = _current_owned(conversation_id, session_id, principal_id)
        if owned:
            return owned
        if _browser_configuration is None or maintenance_held():
            raise control.ControlRejected("browser_control_unavailable")
        with browser._cleanup_lock:
            if session_id in browser._active_sessions:
                raise control.ControlRejected("previous_generation_unresolved")
        record = session._session_record(
            "h", None, {"local": True, "radhouse_owned": True}
        )
        record.update(session_key=session_id, owner_task_id=session_id)
        name = record["session_name"]
        directory = Path(browser._socket_safe_tmpdir()) / ("agent-browser-" + name)
        directory.mkdir(mode=0o700)
        lifecycle._write_owner_pid(str(directory), name)
        environment = {
            k: v
            for k, v in os.environ.items()
            if k in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "XDG_RUNTIME_DIR"}
        }
        environment.update(
            AGENT_BROWSER_SOCKET_DIR=str(directory),
            AGENT_BROWSER_EXECUTABLE_PATH=_browser_configuration["chromium_path"],
            AGENT_BROWSER_ARGS="--disable-extensions",
        )
        argv = [
            _browser_configuration["agent_browser_path"],
            "--config",
            _browser_configuration["empty_config_path"],
            "--executable-path",
            _browser_configuration["chromium_path"],
            "--session",
            name,
            "--json",
            "open",
            "--",
            "about:blank",
        ]
        # Only this fixed initial launch is a CLI operation; no credential/page payload in argv.
        with browser._cleanup_lock:
            if session_id in browser._active_sessions:
                raise control.ControlRejected("previous_generation_unresolved")
        # Track before spawning: a late/failed bootstrap cannot become an untracked daemon.
        with browser._cleanup_lock:
            browser._active_sessions[session_id] = record
        lifecycle._update_session_activity(session_id)
        lifecycle._start_browser_cleanup_thread()
        channel, identity, pid, started = None, None, None, None
        try:
            result = subprocess.run(
                argv,
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=45,
                umask=0o077,
            )
            if (
                result.returncode
                or len(result.stdout) > MAX_RESPONSE
                or json.loads(result.stdout).get("success") is not True
            ):
                raise control.ControlRejected("browser_launch_failed")
            pid = session._read_browser_daemon_pid(str(directory), name)
            if pid is None or not lifecycle._verify_reapable_browser_daemon(
                pid, str(directory), name
            ):
                raise control.ControlRejected("browser_native_identity_unverified")
            started = psutil.Process(pid).create_time()
            stream = _session_stream(session_id)
            if stream is None:
                raise control.ControlRejected("browser_native_identity_unverified")
            identity = control.BrowserIdentity(conversation_id, session_id, stream[1])
            channel = native.NativeControlChannel(
                directory / (name + ".sock"),
                identity.generation,
                lambda: value[1] if (value := _session_stream(session_id)) else None,
            )
            owned = OwnedBrowser(identity, record, pid, started, channel)
            bound = _controller.bind_browser(
                identity,
                run,
                principal_id,
                native_name=name,
                native_pid=pid,
                native_started=started,
            )
            owned.previous_page = bound.previous_page
            _owned_browsers[session_id] = owned
            lifecycle._update_session_activity(session_id)
            lifecycle._start_browser_cleanup_thread()
            return owned
        except BaseException:
            if channel is not None:
                channel.close()
            # Existing exact-PID lifecycle only; do not delete evidence of an unknown daemon.
            try:
                pid = pid or session._read_browser_daemon_pid(str(directory), name)
                if pid and lifecycle._verify_reapable_browser_daemon(
                    pid, str(directory), name
                ):
                    started = started or psutil.Process(pid).create_time()
                    lifecycle._kill_verified_daemon(str(directory), name)
                    deadline = time.monotonic() + 3
                    while not _pid_gone(pid, started) and time.monotonic() < deadline:
                        time.sleep(0.025)
                    if _pid_gone(pid, started):
                        lifecycle._release_session_resources(session_id, record)
                        bound = _controller.current(
                            conversation_id, session_id, principal_id
                        )
                        if (
                            identity is not None
                            and bound is not None
                            and bound.identity == identity
                        ):
                            _controller.retire_browser(
                                identity,
                                control.RetirementObservation(identity, True, True),
                            )
            except Exception:
                pass  # Remains tracked/unresolved; observations and another Open fail closed.
            raise control.ControlRejected("browser_launch_failed") from None


@contextmanager
def agent_browser_operation(context):
    control, native = _control_modules()
    owner = context.browser_owner
    if _controller is None or type(owner) is not dict:
        raise control.ControlRejected("browser_control_unavailable")
    run = control.RunBinding(context.run_id, context.session_id, context.dispatch_key)
    owned = _launch_owned(
        owner["conversation_id"], context.session_id, owner["principal_id"], run=run
    )
    command_id = uuid4().hex
    owned.operation_lock.acquire()
    try:
        _controller.reserve_agent(owned.identity, run, command_id)
    except BaseException:
        owned.operation_lock.release()
        raise
    token = _browser_operation.set(owned)
    try:
        yield owned
    except native.NativeWaitTimeout, native.NativeChannelError:
        _controller.complete_agent(owned.identity, run, command_id, outcome="uncertain")
        raise
    except BaseException:
        pending = owned.last_handle and not owned.last_handle.future.done()
        _controller.complete_agent(
            owned.identity,
            run,
            command_id,
            outcome="uncertain" if pending else "completed",
        )
        raise
    else:
        _controller.complete_agent(owned.identity, run, command_id, outcome="completed")
    finally:
        _browser_operation.reset(token)
        owned.operation_lock.release()


def controlled_browser_command(task_id, command, args):
    """The upstream seven-tool formatters run normally; only their transport changes."""
    context = current_run_context(task_id=task_id)
    owned = _browser_operation.get()
    if owned is None or owned.identity.session_id != context.session_id:
        raise ValueError("browser_control_unavailable")
    result = owned.handle(
        owned.channel.submit_legacy(uuid4().hex, command, args or [])
    ).legacy
    from tools import browser_tool_lifecycle as lifecycle

    lifecycle._update_session_activity(context.session_id)
    return result


def _control_public(state, owner):
    holder = state.lease and state.lease.owner == owner
    output = {
        "mode": state.mode,
        "revision": state.revision,
        "can_take": state.mode in {"agent", "paused"} and not state.retired,
    }
    if holder:
        output.update(
            lease_id=state.lease.lease_id,
            lease_expires_at=state.lease.expires_at,
            next_sequence=state.last_sequence + 1,
        )
    return output


def _fence_takeover(owned, state):
    control, native = _control_modules()
    if state.mode == "human":
        return state
    if state.mode != "takeover_pending" or state.active_command is not None:
        return state
    ack = owned.handle(owned.channel.fence_after(uuid4().hex, owned.last_handle))
    if (
        not isinstance(ack, native.FenceAck)
        or ack.generation != owned.identity.generation
        or not ack.quiescent
    ):
        raise control.ControlRejected("quiescence_unproven")
    return _controller.confirm_takeover(
        owned.identity,
        state.revision,
        control.FenceObservation(owned.identity, state.takeover_after, True),
    )


def _human_input(owned, owner, body):
    control, native = _control_modules()
    with owned.operation_lock:
        # Durable ACK lookup precedes frame validation: retries do not reapply a gesture.
        ack = _controller.reserve_input(
            owned.identity,
            owner,
            body.get("lease_id"),
            body.get("revision"),
            body.get("sequence"),
        )
        if not ack.execute:
            return {
                "success": ack.outcome == "applied",
                "outcome": ack.outcome,
                "sequence": ack.sequence,
            }
        sent = False
        try:
            if body.get("operation") == "navigate" and not http_url(
                (body.get("arguments") or {}).get("url")
            ):
                raise control.ControlRejected("browser_arguments_invalid")
            native.human_commands(body.get("operation"), body.get("arguments"))
            relay = _relays.get(owned.identity.session_id)
            if (
                relay is None
                or relay.generation != owned.identity.generation
                or relay.frame is None
                or relay.frame["frame_id"] != body.get("frame_id")
                or time.time() - relay.frame["received_at"] > 30
                or body.get("viewport") != owned.viewport
            ):
                raise control.ControlRejected("stale_browser_frame")
            args = body["arguments"]
            if body["operation"] in {"click", "scroll"} and not (
                0 <= args["x"] < owned.viewport["width"]
                and 0 <= args["y"] < owned.viewport["height"]
            ):
                raise control.ControlRejected("browser_arguments_invalid")
            handle = owned.channel.submit_input(ack.command_id, body["operation"], args)
            sent = True
            outcome = owned.handle(handle).outcome
        except native.NativeRejected:
            outcome = "rejected"
        except Exception:
            outcome = "uncertain" if sent else "rejected"
        final = _controller.complete_input(
            owned.identity,
            body["lease_id"],
            ack.sequence,
            ack.command_id,
            outcome=outcome,
        )
        return {
            "success": final.outcome == "applied",
            "outcome": final.outcome,
            "sequence": final.sequence,
        }


def _previous_run(adapter, state, request):
    control, _ = _control_modules()
    if state.admitted_run is None:
        return None
    old = adapter._run_statuses.get(state.admitted_run.run_id)
    if old is None:
        old = adapter._run_idempotency_store.status_for_run(
            adapter._run_idempotency_scope(request), state.admitted_run.run_id
        )
    if type(old) is not dict or old.get("session_id") != state.identity.session_id:
        raise control.ControlRejected("previous_run_not_terminal")
    return control.RunTerminalObservation(
        state.admitted_run.run_id, state.identity.session_id, old.get("status")
    )


def _sensitive_fields(owned):
    # Return only a flag, never a field value. Submit/clear sign-in and MFA before handback.
    return (
        owned.evaluate(
            "Array.from(document.querySelectorAll('input[type=password],input[autocomplete=one-time-code]')).some(e=>e.value.length>0)"
        )
        is not False
    )


async def scoped_session_admission_error(adapter, session_id, body):
    """Existing profile-local canonical owner evidence; no delivery or new authority."""
    if not set(body.get("allowed_tools") or ()).intersection(SCOPED_TOOLS):
        return None
    try:
        db = await adapter._ensure_session_db_async()
        if db is None:
            return None
        from tools.bot_live_delivery import find_canonical_live_owner

        def check():
            owner = find_canonical_live_owner(Path(db.db_path).parent)
            return (
                owner is not None
                and db.get_compression_tip(session_id) == owner["session_id"]
            )

        return "browser_context_rejected" if await asyncio.to_thread(check) else None
    except Exception:
        return "browser_context_rejected"


def validate_browser_context(
    adapter, body, run_id, dispatch_key, request=None, *, admit=False
):
    """After exact replay: check before reserve, transfer only to a durably reserved fresh run."""
    value = body.get("browser_context")
    if value is None:
        return None
    try:
        control, _ = _control_modules()
        if type(value) is not dict:
            raise control.ControlRejected("invalid_binding")
        owner, conversation, expiry = _private_owner(value)
        session_id = body["session_id"]
        if body.get("browser_owner") != {
            "principal_id": owner.principal_id,
            "conversation_id": conversation,
        }:
            raise control.ControlRejected("owner_mismatch")
        owned, state = _current_owned(conversation, session_id, owner.principal_id)
        if owned is None or value.get("generation") != state.identity.generation:
            raise control.ControlRejected("stale_browser")
        # Hold the same execution lock through sensitive-field check and admission.
        # A concurrent human input can never enter between them.
        with owned.operation_lock:
            state = _controller.state(owned.identity)
            if state.mode == "human":
                state = _controller.heartbeat(
                    state.identity,
                    owner,
                    value.get("lease_id"),
                    value.get("revision"),
                    auth_expires_at=expiry,
                )
                if _sensitive_fields(owned):
                    raise control.ControlRejected("sensitive_fields_present")
            elif state.mode != "agent" or value.get("lease_id") is not None:
                raise control.ControlRejected("control_lease_unavailable")
            previous = _previous_run(adapter, state, request)
            if (
                state.revision != value.get("revision")
                or state.retired
                or state.active_command is not None
            ):
                raise control.ControlRejected("stale_control")
            if previous is not None and previous.status not in {
                "completed",
                "failed",
                "cancelled",
                "interrupted",
            }:
                raise control.ControlRejected("previous_run_not_terminal")
            if admit:
                _controller.admit_run(
                    state.identity,
                    owner,
                    control.RunBinding(run_id, session_id, dispatch_key),
                    lease_id=value.get("lease_id"),
                    revision=value.get("revision"),
                    previous=previous,
                )
        return None
    except Exception:
        return "browser_context_rejected"


async def handle_browser_session(adapter, request, *, operation, api_server):
    from aiohttp import web

    control, native = _control_modules()
    error = adapter._check_auth(request)
    if error is not None:
        return error
    base = {}
    try:
        if _controller is None or _browser_configuration is None:
            raise control.ControlRejected("browser_control_unavailable")
        body = await request.json()
        owner, conversation, expiry = _private_owner(body)
        session_id = (
            body.get("session_id")
            if operation == "open"
            else request.match_info["session_id"]
        )
        control._identifier(session_id)
        base = {"session_id": session_id}
        if operation == "open":
            owned = await asyncio.to_thread(
                _launch_owned, conversation, session_id, owner.principal_id
            )
            state = _controller.state(owned.identity)
            if state.mode in {"agent", "paused"}:
                state = _controller.request_takeover(
                    owned.identity,
                    owner,
                    body.get("request_id") or uuid4().hex,
                    revision=state.revision,
                    auth_expires_at=expiry,
                )
            elif state.lease is None or state.lease.owner != owner:
                raise control.ControlRejected("browser_control_busy")
            state = await asyncio.to_thread(_fence_takeover, owned, state)
        else:
            owned, state = _current_owned(conversation, session_id, owner.principal_id)
            if owned is None:
                return web.json_response(
                    {
                        **base,
                        "state": "idle",
                        "generation": None,
                        "url": None,
                        "control": None,
                        "viewport": None,
                        "page_context": {
                            "current": None,
                            "previous": state.previous_page if state else None,
                        },
                    },
                    headers={"Cache-Control": "no-store"},
                )
            if (
                body.get("generation") is not None
                and body["generation"] != state.identity.generation
            ):
                raise control.ControlRejected("stale_browser")
            if operation == "take":
                state = _controller.request_takeover(
                    owned.identity,
                    owner,
                    body.get("request_id"),
                    revision=body.get("revision"),
                    auth_expires_at=expiry,
                )
                state = await asyncio.to_thread(_fence_takeover, owned, state)
            elif operation == "heartbeat":
                state = (
                    _controller.heartbeat(
                        owned.identity,
                        owner,
                        body.get("lease_id"),
                        body.get("revision"),
                        auth_expires_at=expiry,
                    )
                    if state.mode == "human"
                    else _controller.presence(
                        owned.identity, owner, body.get("revision")
                    )
                )
                if state.active_command is None:
                    await asyncio.to_thread(
                        owned.handle, owned.channel.probe_status(uuid4().hex)
                    )
                from tools import browser_tool_lifecycle as lifecycle

                lifecycle._update_session_activity(session_id)
            elif operation == "input":
                result = await asyncio.to_thread(_human_input, owned, owner, body)
                return web.json_response(result, headers={"Cache-Control": "no-store"})
            elif operation == "pause":
                state = await asyncio.to_thread(_pause_owned, owned, owner)
            elif operation == "close":
                result = await asyncio.to_thread(
                    _owner_close, adapter, request, owned, owner, body
                )
                if not result.completed:
                    raise control.ControlRejected("retirement_unproven")
                deadline = time.monotonic() + 3
                while (
                    not _pid_gone(owned.pid, owned.started)
                    and time.monotonic() < deadline
                ):
                    await asyncio.sleep(0.05)
                if not _pid_gone(owned.pid, owned.started):
                    raise control.ControlRejected("retirement_unproven")
                _, retired = _current_owned(
                    conversation, session_id, owner.principal_id
                )
                return web.json_response(
                    {
                        **base,
                        "state": "idle",
                        "generation": None,
                        "url": None,
                        "control": None,
                        "viewport": None,
                        "page_context": {
                            "current": None,
                            "previous": retired.previous_page,
                        },
                    },
                    headers={"Cache-Control": "no-store"},
                )
            elif operation not in {"status", "frame"}:
                raise control.ControlRejected("browser_operation_unsupported")
        state = _controller.state(owned.identity)
        # Metadata is a private owner observation, not an agent browser read. It waits behind native ACKs.
        if (
            state.mode == "takeover_pending"
            and state.lease
            and state.lease.owner == owner
        ):
            state = await asyncio.to_thread(_fence_takeover, owned, state)
        if (not maintenance_held() and state.active_command is None and state.mode not in {
            "recovering",
            "takeover_pending",
        }):
            await asyncio.to_thread(_metadata_observation, owned)
        stream = _session_stream(session_id)
        if stream is None or stream[1] != owned.identity.generation:
            raise control.ControlRejected("stale_browser")
        result = await _native_frame(
            stream[0],
            want_frame=operation == "frame",
            session_id=session_id,
            generation=stream[1],
        )
        after = _controller.state(owned.identity)
        if _session_stream(session_id) != stream:
            raise control.ControlRejected("stale_browser")
        response = {
            **base,
            "state": "live",
            "generation": stream[1],
            **_redacted(owned.current_page or {"url": result["url"], "title": ""}),
            "control": _control_public(after, owner),
            "viewport": owned.viewport,
            "page_context": {
                "current": owned.current_page,
                "previous": owned.previous_page,
            },
        }
        if operation == "frame":
            response.update(
                {
                    k: result[k]
                    for k in ("jpeg", "received_at", "captured_at", "frame_id")
                }
            )
        return web.json_response(response, headers={"Cache-Control": "no-store"})
    except Exception:
        return web.json_response(
            {**base, "error": "browser_control_unavailable"},
            status=409,
            headers={"Cache-Control": "no-store"},
        )


def _pause_owned(owned, owner):
    control, native = _control_modules()
    with owned.operation_lock:
        state = _controller.state(owned.identity)
        if state.active_command is not None or state.mode == "recovering":
            raise control.ControlRejected("native_ack_pending")
        if owned.last_handle is not None:
            if not owned.last_handle.future.done():
                raise control.ControlRejected("native_ack_pending")
            result = owned.last_handle.result()
            if not ((isinstance(result, (native.AgentAck, native.HumanAck)) and result.completed)
                    or (isinstance(result, native.FenceAck) and result.quiescent)):
                raise control.ControlRejected("native_ack_unproven")
        return _controller.pause(owned.identity, owner)


def _owner_close(adapter, request, owned, owner, body):
    with owned.operation_lock:
        state = _controller.state(owned.identity)
        if state.active_command is not None:
            control, _ = _control_modules()
            raise control.ControlRejected("browser_control_busy")
        if state.mode == "human":
            _controller.begin_return(
                owned.identity, owner, body.get("lease_id"), body.get("revision")
            )
        else:
            _controller.begin_close(
                owned.identity,
                owner,
                body.get("revision"),
                _previous_run(adapter, state, request),
            )
        return owned.handle(owned.channel.submit_close(uuid4().hex))


def _metadata_observation(owned):
    with owned.operation_lock:
        state = _controller.state(owned.identity)
        if (not maintenance_held() and state.active_command is None and state.mode not in {
            "recovering",
            "takeover_pending",
        }):
            return owned.metadata()


def owned_session_record(task_id):
    if _controller is None or not bridge_run_active():
        return None
    context = current_run_context(task_id=task_id)
    owned = _browser_operation.get()
    if owned is None or owned.identity.session_id != context.session_id:
        raise ValueError("browser_control_unavailable")
    return owned.record


def browser_command_override(task_id, command, args):
    if _controller is None:
        return None
    if bridge_run_active():
        return controlled_browser_command(task_id, command, args)
    owned = _owned_browsers.get(task_id)
    if owned is None:
        return None
    if command != "close":
        raise ValueError("browser_control_unavailable")
    # Only the existing trusted native lifecycle can reach this no-run close seam.
    try:
        with owned.operation_lock:
            result = owned.handle(owned.channel.submit_close(uuid4().hex)).legacy
        return result
    except Exception:
        return {"success": False, "error": "browser_retirement_unproven"}


def login_tool_handler(name, args, **trusted):
    try:
        if _vault is None or name not in LOGIN_TOOLS or type(args) is not dict:
            raise ValueError("browser_login_unavailable")
        if (
            name == "browser_login_list"
            and args
            or name == "browser_login_fill"
            and set(args) != {"handle"}
        ):
            raise ValueError("browser_arguments_invalid")
        context = current_run_context(
            task_id=trusted.get("task_id"), session_id=trusted.get("session_id")
        )
        with agent_browser_operation(context) as access:
            result = (
                _vault.list_logins(access)
                if name == "browser_login_list"
                else _vault.fill_login(access, handle=args["handle"])
            )
            return json.dumps(_redacted(result), ensure_ascii=False)
    except Exception:
        return json.dumps({"error": "browser_login_unavailable"})


def _human_login(owned, owner, body, operation):
    control, native = _control_modules()
    ack = _controller.reserve_input(
        owned.identity,
        owner,
        body.get("lease_id"),
        body.get("revision"),
        body.get("sequence"),
    )
    if not ack.execute:
        return {
            "success": ack.outcome == "applied",
            "outcome": ack.outcome,
            "sequence": ack.sequence,
        }
    result = {}
    try:
        with owned.operation_lock:
            if operation == "list":
                result = _vault.list_logins(owned)
            elif operation == "save":
                args = body.get("arguments")
                if type(args) is not dict or set(args) != {
                    "label",
                    "identifier_type",
                    "identifier",
                    "password",
                }:
                    raise ValueError("browser_arguments_invalid")
                result = _vault.save_login(owned, **args)
            elif operation in {"remove", "fill"}:
                args = body.get("arguments")
                if type(args) is not dict or set(args) != {"handle"}:
                    raise ValueError("browser_arguments_invalid")
                result = (
                    _vault.remove_login if operation == "remove" else _vault.fill_login
                )(owned, **args)
            else:
                raise ValueError("browser_operation_unsupported")
        outcome = "applied"
    except native.NativeWaitTimeout, native.NativeChannelError:
        outcome = "uncertain"
    except Exception:
        outcome = (
            "uncertain"
            if owned.last_handle and not owned.last_handle.future.done()
            else "rejected"
        )
    final = _controller.complete_input(
        owned.identity, body["lease_id"], ack.sequence, ack.command_id, outcome=outcome
    )
    return {
        **_redacted(result),
        "success": final.outcome == "applied",
        "outcome": final.outcome,
        "sequence": final.sequence,
    }


async def handle_browser_logins(adapter, request, *, operation):
    from aiohttp import web

    error = adapter._check_auth(request)
    if error is not None:
        return error
    try:
        if _vault is None or _controller is None:
            raise ValueError("browser_login_unavailable")
        body = await request.json()
        owner, conversation, _ = _private_owner(body)
        session_id = request.match_info["session_id"]
        owned, state = _current_owned(conversation, session_id, owner.principal_id)
        if owned is None or body.get("generation") != state.identity.generation:
            raise ValueError("stale_browser")
        result = await asyncio.to_thread(_human_login, owned, owner, body, operation)
        return web.json_response(result, headers={"Cache-Control": "no-store"})
    except Exception:
        return web.json_response(
            {"error": "browser_login_unavailable"},
            status=409,
            headers={"Cache-Control": "no-store"},
        )
