"""Render a source-pinned overlay. Never apply against a fuzzy or bare upstream base."""

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path

PACKAGE = Path(__file__).parent


def _replace(source, old, new):
    if source.count(old) != 1:
        raise ValueError("hermes_overlay_context_mismatch")
    return source.replace(old, new, 1)


def _insert_function(source, name, block):
    tree = ast.parse(source)
    nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    if len(nodes) != 1:
        raise ValueError("hermes_overlay_context_mismatch")
    function = nodes[0]
    first = (
        function.body[1]
        if isinstance(function.body[0], ast.Expr)
        and isinstance(function.body[0].value, ast.Constant)
        and isinstance(function.body[0].value.value, str)
        else function.body[0]
    )
    lines = source.splitlines(keepends=True)
    lines.insert(first.lineno - 1, block)
    return "".join(lines)


def patch_runs(source):
    source = _replace(
        source,
        "    browser_control_transport_family: Any\n",
        "    browser_control_transport_family: Any\n    dispatch_key: str\n    scope_token: Optional[str] = field(repr=False)\n    browser_owner: Any = field(repr=False)\n",
    )
    source = _replace(
        source,
        '    idempotency_scope = idempotency_fingerprint = ""\n',
        """    from radhouse_hermes_bridge import validate_admission
    scope_error = validate_admission(body, idempotency_key, self._run_idempotency_store.durable)
    if scope_error:
        return _json_error(_openai_error, scope_error, code=scope_error, status=400)
    idempotency_scope = idempotency_fingerprint = ""
""",
    )
    source = _replace(
        source,
        '    if allowed_tools is not None:\n        initial_status["allowed_tools"] = list(allowed_tools)\n',
        '    if allowed_tools is not None:\n        initial_status["allowed_tools"] = list(allowed_tools)\n    initial_status["dispatch_key"] = idempotency_key\n',
    )
    source = _replace(
        source,
        "        browser_control_transport_family=_api_server._api_request_browser_control_transport_family.get(),\n",
        '        browser_control_transport_family=_api_server._api_request_browser_control_transport_family.get(),\n        dispatch_key=idempotency_key, scope_token=body.get("document_scope_token"), browser_owner=body.get("browser_owner"),\n',
    )
    source = _replace(
        source,
        "            ephemeral_system_prompt=instructions, session_id=session_id, gateway_session_key=gateway_session_key,\n",
        '            ephemeral_system_prompt=__import__("radhouse_hermes_bridge").trusted_browser_instructions(instructions, allowed_tools), session_id=session_id, gateway_session_key=gateway_session_key,\n',
    )
    source = _replace(
        source,
        "            # Contextvars, not process env: concurrent runs must not share identity.\n",
        """            from radhouse_hermes_bridge import BROWSER_TOOLS, LOGIN_TOOLS, bind_run_context, reset_run_context
            if run.scope_token or set(run.agent_kwargs.get("allowed_tools", ())).intersection(BROWSER_TOOLS + LOGIN_TOOLS):
                resets.append((bind_run_context(run.run_id, run.session_id, run.dispatch_key, run.scope_token, run.browser_owner), reset_run_context))
            # Contextvars, not process env: concurrent runs must not share identity.
""",
    )
    source = _replace(
        source,
        '        ("POST", "/v1/runs/{run_id}/stop", self._handle_stop_run)]',
        '        ("POST", "/v1/runs/{run_id}/stop", self._handle_stop_run),\n        ("GET", "/v1/runs/{run_id}/browser", self._handle_radhouse_browser),\n        ("GET", "/v1/runs/{run_id}/browser-frame", self._handle_radhouse_browser_frame),\n        ("GET", "/v1/maintenance/status", self._handle_radhouse_maintenance),\n        ("POST", "/v1/maintenance/fence", self._handle_radhouse_maintenance),\n        ("POST", "/v1/maintenance/release", self._handle_radhouse_maintenance)]',
    )
    source = _replace(
        source,
        "    q = self._run_streams[run_id] = _RunStream()\n",
        """    from radhouse_hermes_bridge import validate_browser_context, scoped_session_admission_error
    if await scoped_session_admission_error(self, session_id, body):
        self._run_owners.pop(run_id, None)
        return web.json_response({"error": "browser_context_rejected", "admitted": False}, status=409)
    if body.get("browser_context") is not None and session_id != body.get("session_id"):
        self._run_owners.pop(run_id, None)
        return web.json_response({"error": "browser_context_rejected", "admitted": False}, status=409)
    if validate_browser_context(self, body, run_id, idempotency_key, request):
        self._run_owners.pop(run_id, None)
        return web.json_response({"error": "browser_context_rejected", "admitted": False}, status=409)
    q = self._run_streams[run_id] = _RunStream()
""",
    )
    source = _replace(
        source,
        "    admitted = await self._admit_to_live_bot_chat(session_id, user_message, turn_author) if selected_session_id else None\n",
        '    # Scoped Radhouse work owns its admitted executor and must not enter a Desktop mailbox.\n    admitted = (await self._admit_to_live_bot_chat(session_id, user_message, turn_author)\n        if selected_session_id and not set(allowed_tools or ()).intersection(__import__("radhouse_hermes_bridge").SCOPED_TOOLS) else None)\n',
    )
    source = _replace(
        source,
        "    launch = _RunLaunch(\n",
        """    if validate_browser_context(self, body, run_id, idempotency_key, request, admit=True):
        self._set_run_status(run_id, "failed", error="browser_context_rejected")
        return _accepted_response(run_id, "failed", gateway_session_key, replayed=False)
    launch = _RunLaunch(
""",
    )
    if "from dataclasses import dataclass\n" in source:
        source = _replace(
            source,
            "from dataclasses import dataclass\n",
            "from dataclasses import dataclass, field\n",
        )
    else:  # Bounded original-function snapshot used by the standalone source tests.
        source = "from dataclasses import field\n" + source
    ast.parse(source)
    return source


def patch_api(source):
    anchor = '                "runs_idempotency": _api_runs._idempotency_capabilities(self, store_type=RunIdempotencyStore),\n'
    source = _replace(
        source,
        anchor,
        anchor
        + '                **__import__("radhouse_hermes_bridge").features(self),\n',
    )
    source = _replace(
        source,
        "        draining = self._draining_response()\n        recoverable_runs = ",
        '        from radhouse_hermes_bridge import maintenance_held\n        if maintenance_held():\n            return _error_response("Runtime maintenance is in progress.", 503, code="runtime_maintenance", headers={"Retry-After": "5"})\n        draining = self._draining_response()\n        recoverable_runs = ',
    )
    anchor = '    @_admit_api_agent_request\n    async def _handle_runs(self, request: "web.Request") -> "web.Response":\n'
    source = _replace(
        source,
        anchor,
        """    async def _handle_radhouse_browser(self, request):
        from radhouse_hermes_bridge import handle_browser
        return await handle_browser(self, request, api_server=sys.modules[__name__])

    async def _handle_radhouse_browser_frame(self, request):
        from radhouse_hermes_bridge import handle_browser
        return await handle_browser(self, request, frame=True, api_server=sys.modules[__name__])

    async def _handle_radhouse_maintenance(self, request):
        from radhouse_hermes_bridge import handle_maintenance
        return await handle_maintenance(self, request)

    async def _handle_radhouse_browser_session(self, request):
        from radhouse_hermes_bridge import handle_browser_session
        operation = request.path.rstrip("/").rsplit("/", 1)[-1]
        return await handle_browser_session(self, request, operation=operation, api_server=sys.modules[__name__])

    async def _handle_radhouse_browser_logins(self, request):
        from radhouse_hermes_bridge import handle_browser_logins
        operation = request.path.rstrip("/").rsplit("/", 1)[-1]
        return await handle_browser_logins(self, request, operation=operation)

"""
        + anchor,
    )
    anchor = "        routes.extend(_api_runs._http_routes(self))\n"
    routes = """        routes.append(("POST", "/v1/browser-sessions/open", self._handle_radhouse_browser_session))
        for operation in ("status", "frame"):
            routes.append(("POST", "/v1/browser-sessions/{session_id}/" + operation, self._handle_radhouse_browser_session))
        for operation in ("take", "heartbeat", "input", "pause", "close"):
            routes.append(("POST", "/v1/browser-sessions/{session_id}/control/" + operation, self._handle_radhouse_browser_session))
        for operation in ("list", "save", "remove", "fill"):
            routes.append(("POST", "/v1/browser-sessions/{session_id}/logins/" + operation, self._handle_radhouse_browser_logins))
"""
    source = _replace(source, anchor, anchor + routes)
    ast.parse(source)
    return source


def patch_browser(source):
    source = _replace(
        source,
        "    def check() -> bool:\n        return check_browser_routed_requirements(name)\n",
        "    def check() -> bool:\n        from radhouse_hermes_bridge import browser_available, bridge_run_active\n        if browser_available(name):\n            return True\n        if bridge_run_active():\n            return False\n        return check_browser_routed_requirements(name)\n",
    )
    source = _replace(
        source,
        "    def handler(args, **kw):\n        return record_browser_call(lambda legacy: routed_browser_handler(\n",
        "    def handler(args, **kw):\n        from radhouse_hermes_bridge import bridge_run_active, checked_browser_call\n        if bridge_run_active():\n            return checked_browser_call(name, args, kw, lambda: fallback(args, kw))\n        return record_browser_call(lambda legacy: routed_browser_handler(\n",
    )
    return source


def patch_browser_install(source):
    source = _insert_function(
        source,
        "_find_agent_browser",
        "    from radhouse_hermes_bridge import browser_argv\n    pinned = browser_argv()\n    if pinned is not None:\n        return pinned[0]  # No npx/lazy dependency install for scoped native runs.\n",
    )
    return _insert_function(
        source,
        "_chromium_installed",
        "    from radhouse_hermes_bridge import browser_argv\n    if browser_argv() is not None:\n        return True  # Scoped runs use the configured, qualified Chrome pair, not ambient caches.\n",
    )


def patch_chat_completion_helpers(source):
    source = _insert_function(
        source,
        "cleanup_task_resources",
        "    from radhouse_hermes_bridge import retain_browser_after_turn\n",
    )
    return _replace(
        source,
        '("browser", lambda _tid: _headed(), "cleanup_browser for headed session",',
        '("browser", lambda _tid: _headed() or retain_browser_after_turn(_tid), "cleanup_browser for retained session",',
    )


def patch_browser_preflight(source):
    return _insert_function(
        source,
        "_browser_command_preflight",
        """    from radhouse_hermes_bridge import bridge_run_active, browser_argv
    if bridge_run_active():
        # A qualified VM browser never starts the upstream desktop/sandbox route.
        pinned = browser_argv()
        from tools.interrupt import is_interrupted
        if is_interrupted():
            return {"success": False, "error": "Interrupted"}
        return {"browser_cmd": pinned[0]}
""",
    )


def patch_browser_session(source):
    source = patch_browser_preflight(source)
    source = _insert_function(
        source,
        "_agent_browser_argv",
        "    from radhouse_hermes_bridge import browser_argv\n    pinned = browser_argv()\n    if pinned is not None:\n        return pinned\n",
    )
    source = _insert_function(
        source,
        "_apply_chromium_sandbox_args",
        "    from radhouse_hermes_bridge import bridge_run_active\n    if bridge_run_active():\n        return  # Dedicated native browser must retain Chromium's sandbox.\n",
    )
    source = _insert_function(
        source,
        "_create_local_session",
        "    from radhouse_hermes_bridge import bridge_run_active\n    if bridge_run_active():\n        allow_real_profile = False\n",
    )
    source = _insert_function(
        source,
        "_create_session_for_key",
        "    from radhouse_hermes_bridge import bridge_run_active, current_run_context\n    if bridge_run_active():\n        current_run_context(task_id=task_id)\n        return _create_local_session(task_id, allow_real_profile=False)\n",
    )
    source = _replace(
        source,
        '    info = _session_record("h", None, {"local": True})\n',
        '    info = _session_record("h", None, {"local": True})\n    if bridge_run_active():\n        info["features"]["radhouse_owned"] = True\n',
    )
    source = _replace(
        source,
        "    if existing_session is not None:\n        # Suspect recycle:",
        '    from radhouse_hermes_bridge import bridge_run_active\n    if bridge_run_active() and existing_session is not None and not (existing_session.get("features") or {}).get("radhouse_owned"):\n        raise RuntimeError("browser_session_unavailable")\n    if existing_session is not None:\n        # Suspect recycle:',
    )
    source = _replace(
        source,
        "    env = _bt._build_browser_env()\n",
        "    from radhouse_hermes_bridge import browser_environment\n    env = browser_environment(_bt._build_browser_env())\n",
    )
    source = _replace(
        source,
        '    cmd_parts = argv + backend_args + ["--json", spawn_command] + spawn_args\n',
        '    from radhouse_hermes_bridge import bridge_run_active\n    literal_args = (["--"] + spawn_args) if bridge_run_active() else spawn_args\n    cmd_parts = argv + backend_args + ["--json", spawn_command] + literal_args\n',
    )
    source = _insert_function(
        source,
        "_run_browser_command",
        """    from radhouse_hermes_bridge import browser_command_override
    controlled = browser_command_override(task_id, command, args)
    if controlled is not None:
        return controlled
""",
    )
    source = _insert_function(
        source,
        "_get_session_info",
        """    from radhouse_hermes_bridge import owned_session_record
    controlled = owned_session_record(task_id)
    if controlled is not None:
        return controlled
""",
    )
    ast.parse(source)
    return source


def patch_budget_recovery(source):
    # A local admitted request cap is terminal; SDK wrapping must not make it an outage.
    return _insert_function(source, "auto_recover_after_exhaustion", """    from agent.provider_request_budget import ProviderRequestBudget
    budget = getattr(agent, "_provider_request_budget", None)
    if isinstance(budget, ProviderRequestBudget) and budget.snapshot()["exhausted"] is True:
        return None
""")


TRANSFORMS = {
    "gateway/platforms/api_server.py": patch_api,
    "gateway/platforms/api_server_runs.py": patch_runs,
    "tools/browser_tool.py": patch_browser,
    "tools/browser_tool_session.py": patch_browser_session,
    "tools/browser_tool_install.py": patch_browser_install,
    "agent/chat_completion_helpers.py": patch_chat_completion_helpers,
    "agent/turn_recovery_autorecover.py": patch_budget_recovery,
}


def render(root):
    lock = json.loads((PACKAGE / "source-lock.json").read_text())
    spec = importlib.util.spec_from_file_location(
        "radhouse_base_overlay", PACKAGE / "base_overlay.py"
    )
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    preceding = base.render(root)
    output = {}
    for name, declaration in lock["files"].items():
        raw = (
            preceding[name].encode()
            if name in preceding
            else (Path(root) / name).read_bytes()
        )
        if hashlib.sha256(raw).hexdigest() != declaration["before_sha256"]:
            raise ValueError("hermes_overlay_source_mismatch")
        output[name] = (
            TRANSFORMS[name](raw.decode()) if name in TRANSFORMS else raw.decode()
        )
    return output


def write(root, destination):
    """Produce a new reviewable tree, never modify a running Hermes checkout."""
    output = render(root)
    destination = Path(destination)
    destination.mkdir(mode=0o755, parents=True, exist_ok=False)
    manifest = {}
    for name, source in output.items():
        target = destination / name
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        target.write_text(source)
        manifest[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    target = destination / "radhouse_hermes_bridge.py"
    target.write_bytes((PACKAGE / "bridge.py").read_bytes())
    manifest[target.name] = hashlib.sha256(target.read_bytes()).hexdigest()
    for source, name in (
        ("browser_control.py", "radhouse_browser_control.py"),
        ("native_control.py", "radhouse_native_control.py"),
        ("vault_bridge.py", "radhouse_vault_bridge.py"),
    ):
        target = destination / name
        target.write_bytes((PACKAGE / source).read_bytes())
        manifest[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    for name in ("__init__.py", "plugin.yaml"):
        target = destination / "plugin/radhouse_documents" / name
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        target.write_bytes((PACKAGE / "plugin" / name).read_bytes())
        manifest[str(target.relative_to(destination))] = hashlib.sha256(
            target.read_bytes()
        ).hexdigest()
    (destination / "rendered-sha256.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Render the exact reviewed native source into a NEW directory."
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    print(json.dumps(write(arguments.source, arguments.output), sort_keys=True))
