"""Render a source-pinned overlay. Never apply against a fuzzy or bare upstream base."""
import ast
import argparse
import hashlib
import json
from pathlib import Path

PACKAGE = Path(__file__).parent


def _replace(source, old, new):
    if source.count(old) != 1:
        raise ValueError("hermes_overlay_context_mismatch")
    return source.replace(old, new, 1)


def _insert_function(source, name, block):
    tree = ast.parse(source)
    nodes = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    if len(nodes) != 1:
        raise ValueError("hermes_overlay_context_mismatch")
    function = nodes[0]
    first = function.body[1] if isinstance(function.body[0], ast.Expr) and isinstance(function.body[0].value, ast.Constant) and isinstance(function.body[0].value.value, str) else function.body[0]
    lines = source.splitlines(keepends=True)
    lines.insert(first.lineno - 1, block)
    return "".join(lines)


def patch_runs(source):
    source = _replace(source, "    browser_control_transport_family: Any\n", "    browser_control_transport_family: Any\n    dispatch_key: str\n    scope_token: Optional[str] = field(repr=False)\n")
    source = _replace(source, "    idempotency_scope = idempotency_fingerprint = \"\"\n", """    from radhouse_hermes_bridge import validate_admission
    scope_error = validate_admission(body, idempotency_key, self._run_idempotency_store.durable)
    if scope_error:
        return _json_error(_openai_error, scope_error, code=scope_error, status=400)
    idempotency_scope = idempotency_fingerprint = ""
""")
    source = _replace(source, '    if allowed_tools is not None:\n        initial_status["allowed_tools"] = list(allowed_tools)\n',
                      '    if allowed_tools is not None:\n        initial_status["allowed_tools"] = list(allowed_tools)\n    initial_status["dispatch_key"] = idempotency_key\n')
    source = _replace(source, '        browser_control_transport_family=_api_server._api_request_browser_control_transport_family.get())\n',
                      '        browser_control_transport_family=_api_server._api_request_browser_control_transport_family.get(),\n        dispatch_key=idempotency_key, scope_token=body.get("document_scope_token"))\n')
    source = _replace(source, '            ephemeral_system_prompt=instructions, session_id=session_id, gateway_session_key=gateway_session_key,\n',
                      '            ephemeral_system_prompt=__import__("radhouse_hermes_bridge").trusted_browser_instructions(instructions, allowed_tools), session_id=session_id, gateway_session_key=gateway_session_key,\n')
    source = _replace(source, '            # Contextvars, not process env: concurrent runs must not share identity.\n', """            from radhouse_hermes_bridge import BROWSER_TOOLS, bind_run_context, reset_run_context
            if run.scope_token or set(run.agent_kwargs.get("allowed_tools", ())).intersection(BROWSER_TOOLS):
                resets.append((bind_run_context(run.run_id, run.session_id, run.dispatch_key, run.scope_token), reset_run_context))
            # Contextvars, not process env: concurrent runs must not share identity.
""")
    source = _replace(source, '        ("POST", "/v1/runs/{run_id}/stop", self._handle_stop_run)]',
                      '        ("POST", "/v1/runs/{run_id}/stop", self._handle_stop_run),\n        ("GET", "/v1/runs/{run_id}/browser", self._handle_radhouse_browser),\n        ("GET", "/v1/runs/{run_id}/browser-frame", self._handle_radhouse_browser_frame),\n        ("GET", "/v1/maintenance/status", self._handle_radhouse_maintenance),\n        ("POST", "/v1/maintenance/fence", self._handle_radhouse_maintenance),\n        ("POST", "/v1/maintenance/release", self._handle_radhouse_maintenance)]')
    if "from dataclasses import dataclass\n" in source:
        source = _replace(source, "from dataclasses import dataclass\n", "from dataclasses import dataclass, field\n")
    else:  # Bounded original-function snapshot used by the standalone source tests.
        source = "from dataclasses import field\n" + source
    ast.parse(source)
    return source


def patch_api(source):
    anchor = '                "runs_idempotency": _api_runs._idempotency_capabilities(self, store_type=RunIdempotencyStore),\n'
    source = _replace(source, anchor, anchor + '                **__import__("radhouse_hermes_bridge").features(self),\n')
    source = _replace(source, '        draining = self._draining_response()\n        recoverable_runs = ',
                      '        from radhouse_hermes_bridge import maintenance_held\n        if maintenance_held():\n            return _error_response("Runtime maintenance is in progress.", 503, code="runtime_maintenance", headers={"Retry-After": "5"})\n        draining = self._draining_response()\n        recoverable_runs = ')
    anchor = '    @_admit_api_agent_request\n    async def _handle_runs(self, request: "web.Request") -> "web.Response":\n'
    source = _replace(source, anchor, """    async def _handle_radhouse_browser(self, request):
        from radhouse_hermes_bridge import handle_browser
        return await handle_browser(self, request, api_server=sys.modules[__name__])

    async def _handle_radhouse_browser_frame(self, request):
        from radhouse_hermes_bridge import handle_browser
        return await handle_browser(self, request, frame=True, api_server=sys.modules[__name__])

    async def _handle_radhouse_maintenance(self, request):
        from radhouse_hermes_bridge import handle_maintenance
        return await handle_maintenance(self, request)

""" + anchor)
    ast.parse(source)
    return source


def patch_browser(source):
    source = _replace(source, '    def check() -> bool:\n        return check_browser_routed_requirements(name)\n',
                      '    def check() -> bool:\n        from radhouse_hermes_bridge import browser_available, bridge_run_active\n        if browser_available(name):\n            return True\n        if bridge_run_active():\n            return False\n        return check_browser_routed_requirements(name)\n')
    source = _replace(source, '    def handler(args, **kw):\n        return routed_browser_handler(name, args, fallback=lambda: fallback(args, kw),\n',
                      '    def handler(args, **kw):\n        from radhouse_hermes_bridge import bridge_run_active, checked_browser_call\n        if bridge_run_active():\n            return checked_browser_call(name, args, kw, lambda: fallback(args, kw))\n        return routed_browser_handler(name, args, fallback=lambda: fallback(args, kw),\n')
    return source


def patch_browser_install(source):
    source = _insert_function(source, "_find_agent_browser", "    from radhouse_hermes_bridge import browser_argv\n    pinned = browser_argv()\n    if pinned is not None:\n        return pinned[0]  # No npx/lazy dependency install for scoped native runs.\n")
    return _insert_function(source, "_chromium_installed", "    from radhouse_hermes_bridge import browser_argv\n    if browser_argv() is not None:\n        return True  # Scoped runs use the configured, qualified Chrome pair, not ambient caches.\n")


def patch_browser_session(source):
    source = _insert_function(source, "_agent_browser_argv", "    from radhouse_hermes_bridge import browser_argv\n    pinned = browser_argv()\n    if pinned is not None:\n        return pinned\n")
    source = _insert_function(source, "_apply_chromium_sandbox_args", "    from radhouse_hermes_bridge import bridge_run_active\n    if bridge_run_active():\n        return  # Dedicated native browser must retain Chromium's sandbox.\n")
    source = _insert_function(source, "_create_local_session", "    from radhouse_hermes_bridge import bridge_run_active\n    if bridge_run_active():\n        allow_real_profile = False\n")
    source = _insert_function(source, "_create_session_for_key", "    from radhouse_hermes_bridge import bridge_run_active, current_run_context\n    if bridge_run_active():\n        current_run_context(task_id=task_id)\n        return _create_local_session(task_id, allow_real_profile=False)\n")
    source = _replace(source, '    info = _session_record("h", None, {"local": True})\n',
                      '    info = _session_record("h", None, {"local": True})\n    if bridge_run_active():\n        info["features"]["radhouse_owned"] = True\n')
    source = _replace(source, '    if existing_session is not None:\n        # Suspect recycle:',
                      '    from radhouse_hermes_bridge import bridge_run_active\n    if bridge_run_active() and existing_session is not None and not (existing_session.get("features") or {}).get("radhouse_owned"):\n        raise RuntimeError("browser_session_unavailable")\n    if existing_session is not None:\n        # Suspect recycle:')
    source = _replace(source, '    env = _bt._build_browser_env()\n',
                      '    from radhouse_hermes_bridge import browser_environment\n    env = browser_environment(_bt._build_browser_env())\n')
    source = _replace(source, '    cmd_parts = _agent_browser_argv(browser_cmd) + backend_args + ["--json", command] + args\n',
                      '    from radhouse_hermes_bridge import bridge_run_active\n    literal_args = (["--"] + args) if bridge_run_active() else args\n    cmd_parts = _agent_browser_argv(browser_cmd) + backend_args + ["--json", command] + literal_args\n')
    ast.parse(source)
    return source


TRANSFORMS = {"gateway/platforms/api_server.py": patch_api, "gateway/platforms/api_server_runs.py": patch_runs,
              "tools/browser_tool.py": patch_browser, "tools/browser_tool_session.py": patch_browser_session,
              "tools/browser_tool_install.py": patch_browser_install}


def render(root):
    lock = json.loads((PACKAGE / "source-lock.json").read_text())
    output = {}
    for name, declaration in lock["files"].items():
        raw = (Path(root) / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != declaration["before_sha256"]:
            raise ValueError("hermes_overlay_source_mismatch")
        output[name] = TRANSFORMS[name](raw.decode()) if name in TRANSFORMS else raw.decode()
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
    for name in ("__init__.py", "plugin.yaml"):
        target = destination / "plugin/radhouse_documents" / name
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        target.write_bytes((PACKAGE / "plugin" / name).read_bytes())
        manifest[str(target.relative_to(destination))] = hashlib.sha256(target.read_bytes()).hexdigest()
    (destination / "rendered-sha256.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Render the exact reviewed native source into a NEW directory.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    print(json.dumps(write(arguments.source, arguments.output), sort_keys=True))
