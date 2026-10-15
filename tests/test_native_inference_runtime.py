"""Qualify selection on the exact pinned native source without provider calls."""
import ast
import importlib.util
import logging
from pathlib import Path
import sys
from types import MethodType, ModuleType, SimpleNamespace

import pytest


PACKAGE = Path(__file__).resolve().parents[1] / "runtime/hermes"


def module_from_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


native = module_from_file("native_inference_runtime_test", PACKAGE / "native_inference.py")


@pytest.fixture(scope="module")
def pinned_source():
    package = importlib.util.find_spec("hermes_cli")
    if package is None:
        pytest.skip("Pinned Hermes source is required for source qualification")
    root = Path(package.origin).parent.parent
    base = module_from_file("inference_base_overlay_test", PACKAGE / "base_overlay.py")
    # The base renderer verifies every before/after source SHA before transforming.
    return root, base.render(root)


def isolated_function(source, name, namespace):
    matches = [node for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    assert len(matches) == 1
    function = matches[0]
    function.decorator_list = []
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    code = ast.fix_missing_locations(ast.Module(body=[future, function], type_ignores=[]))
    exec(compile(code, "<pinned-hermes-source>", "exec"), namespace)
    return namespace[name]


def test_selected_run_patch_changes_only_the_native_launch(pinned_source):
    _, sources = pinned_source
    source = sources["gateway/platforms/api_server_runs.py"]
    patched = native.patch_selected_run(source)
    assert patched.replace('            confirmed_runtime_lock=(body.get("radhouse_inference") is True),\n', "") == source
    tree = ast.parse(patched)
    launch = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == "_RunLaunch")
    kwargs = next(keyword.value for keyword in launch.keywords if keyword.arg == "agent_kwargs")
    flag = next(keyword.value for keyword in kwargs.keywords if keyword.arg == "confirmed_runtime_lock")
    for marker, expected in ((True, True), (False, False), (None, False), (1, False)):
        assert eval(compile(ast.Expression(flag), "<launch-flag>", "eval"), {"body": {"radhouse_inference": marker}}) is expected
    executor = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "_execute_run")
    create = next(node for node in ast.walk(executor) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == "_create_agent")
    assert any(keyword.arg is None and ast.unparse(keyword.value) == "run.agent_kwargs" for keyword in create.keywords)
    with pytest.raises(ValueError, match="context_mismatch"):
        native.patch_selected_run(patched)
    with pytest.raises(ValueError, match="context_mismatch"):
        native.patch_selected_run(source.replace("disable_tools=disable_tools", "disable_tools=False"))


def test_exact_native_mode_helper_cannot_fetch_models_dev(pinned_source, monkeypatch):
    root, _ = pinned_source
    calls = []
    def get_provider(name, *, allow_network=True):
        calls.append((name, allow_network))
        return SimpleNamespace(transport="openai_chat")
    namespace = {"is_actual_route": lambda *args: False,
        "host_mandated_api_mode": lambda base: "codex_responses" if "responses.test" in base else None,
        "nous_api_mode": lambda model: "anthropic_messages" if model.startswith("anthropic/") else "chat_completions",
        "get_provider": get_provider, "TRANSPORT_TO_API_MODE": {"openai_chat": "chat_completions"}}
    module = ModuleType("hermes_cli.providers")
    module.determine_api_mode = isolated_function((root / "hermes_cli/providers.py").read_text(), "determine_api_mode", namespace)
    module.get_provider = get_provider
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert native._native_model_mode_reader("custom:office", "http://engine.test/v1")("alpha") == "chat_completions"
    assert calls == [("custom:office", False)]
    assert module.determine_api_mode.__globals__["get_provider"] is get_provider
    assert native._native_model_mode_reader("nous", "https://engine.test/v1")("anthropic/alpha") == "anthropic_messages"
    assert native._native_model_mode_reader("custom:office", "https://responses.test/v1")("alpha") == "codex_responses"
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["custom", "lmstudio"])
def test_only_bundled_qualified_serializer_is_admitted(pinned_source, kind):
    root, _ = pinned_source
    path = root / "plugins/model-providers" / kind / "__init__.py"
    tree = ast.parse(path.read_text())
    function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "build_api_kwargs_extras")
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    code = ast.fix_missing_locations(ast.Module(body=[future, function], type_ignores=[]))
    scope = {}
    exec(compile(code, str(path), "exec"), scope)
    assert native._qualified_wire(SimpleNamespace(build_api_kwargs_extras=scope["build_api_kwargs_extras"])) == kind
    assert native._qualified_wire(SimpleNamespace(build_api_kwargs_extras=lambda **kwargs: ({}, {}))) is None


@pytest.mark.parametrize("locked", [True, False])
def test_exact_native_creation_locks_requested_pair_and_preserves_generic_fallback(pinned_source, monkeypatch, locked):
    root, sources = pinned_source
    facade = ModuleType("gateway.platforms.api_server")
    facade._REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
    facade._REQUEST_OPTION_MISSING = object()
    facade._clean_request_string = lambda value: value.strip() if isinstance(value, str) else ""
    facade._coerce_request_bool = lambda value, default=False: value if isinstance(value, bool) else default
    namespace = {"logger": logging.getLogger(__name__),
        "_clean_request_string": facade._clean_request_string,
        "_REQUEST_OPTION_MISSING": facade._REQUEST_OPTION_MISSING,
        "resolve_display_setting": lambda *args: True,
        "_ProviderAuthResolutionError": RuntimeError,
        "_RUNTIME_AGENT_OVERRIDE_KEYS": ("provider", "base_url", "api_key", "api_mode")}
    request_source = (root / "gateway/platforms/api_server_request_options.py").read_text()
    for name in ("_request_reasoning_config", "_request_service_tier"):
        isolated_function(request_source, name, namespace)
    source = sources["gateway/platforms/api_server.py"]
    apply_overrides = isolated_function(source, "_apply_runtime_agent_overrides", namespace)
    select = isolated_function(source, "_select_agent_runtime", namespace)
    recover = isolated_function(source, "_recover_or_record_model", namespace)
    create = isolated_function(source, "_create_agent", namespace)
    run, agent_module, tools, switch = (ModuleType(name) for name in (
        "gateway.run", "run_agent", "hermes_cli.tools_config", "hermes_cli.model_switch"))
    run._checkpoint_agent_kwargs = lambda _: {}
    run._current_max_iterations = lambda: 5
    run._resolve_runtime_agent_kwargs = lambda: {"provider": "configured-engine", "api_mode": "chat_completions"}
    run._resolve_gateway_model = lambda: "global-default"
    run._load_gateway_config = lambda: {}
    fallback = [{"provider": "fallback-engine", "model": "fallback-model"}]
    run.GatewayRunner = SimpleNamespace(_load_fallback_model=lambda: fallback, _load_reasoning_config=lambda _: None)
    agent_module.AIAgent = lambda **kwargs: SimpleNamespace(**kwargs)
    tools._get_platform_tools = lambda *args: []
    switch.resolve_effective_model = lambda override, row, default: (override or {}).get("model") or row or default
    for module in (facade, run, agent_module, tools, switch):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    applied = []
    adapter = SimpleNamespace(_last_resolved_model={}, _model_name="hermes-agent",
        _session_model_override_for=lambda _: {"provider": "session-engine", "model": "session-model"},
        _ensure_session_db=lambda: None, _memory_sessions=SimpleNamespace(checkout=lambda _: None))
    def apply(runtime, provider, *, target_model, required=False):
        applied.append((provider, target_model, required))
        apply_overrides(runtime, {"provider": provider, "api_mode": "chat_completions"})
        return True
    adapter._apply_provider_runtime = apply
    adapter._recover_or_record_model = MethodType(recover, adapter)
    adapter._select_agent_runtime = MethodType(select, adapter)
    agent = create(adapter, session_id="synthetic-session", gateway_session_key="synthetic-affinity",
        requested_model="alpha", requested_provider="configured-engine", session_model="persisted-other-model",
        confirmed_runtime_lock=locked, model_options={"reasoning": {"enabled": True, "effort": "high"}})
    if locked:
        assert (agent.provider, agent.model) == ("configured-engine", "alpha")
        assert applied == [("configured-engine", "alpha", True)]
        assert agent.fallback_model is None
    else:
        assert (agent.provider, agent.model) == ("session-engine", "session-model")
        assert agent.fallback_model == fallback
    assert agent.reasoning_config == {"enabled": True, "effort": "high"}
    entries = isolated_function((root / "agent/agent_init_fallback.py").read_text(), "_fallback_entries", {})
    assert entries(agent.fallback_model) == ([] if locked else fallback)


@pytest.mark.parametrize("reasoning,wire", [
    ({"enabled": False}, {"reasoning_effort": "none"}),
    ({"enabled": True, "effort": "high"}, {"reasoning_effort": "high"}),
    ({"enabled": True}, {}),
])
def test_exact_custom_profile_serializes_explicit_efforts_without_claiming_boolean_on(pinned_source, reasoning, wire):
    root, _ = pinned_source
    # Execute the real cheap profile serializer, isolating registration/import side effects.
    effort_source = (root / "agent/reasoning_effort.py").read_text()
    namespace = {"EFFORT_LADDER": ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"),
        "OPENAI_COMPAT_WIRE_EFFORTS": ("none", "minimal", "low", "medium", "high", "xhigh", "max"),
        "base_url_host_matches": lambda *args: False, "_looks_like_ollama_endpoint": lambda _: False}
    isolated_function(effort_source, "clamp_effort", namespace)
    build = isolated_function((root / "plugins/model-providers/custom/__init__.py").read_text(), "build_api_kwargs_extras", namespace)
    body, top = build(object(), reasoning_config=reasoning, base_url="http://synthetic-engine.test/v1")
    assert body == {} and top == wire


@pytest.mark.parametrize("reasoning,expected", [
    ({"enabled": False}, "none"), ({"enabled": True}, "medium"),
    ({"enabled": True, "effort": "low"}, None),
])
def test_exact_lmstudio_boolean_options_use_native_vocabulary(pinned_source, reasoning, expected):
    root, _ = pinned_source
    namespace = {"_LM_VALID_EFFORTS": {"none", "minimal", "low", "medium", "high", "xhigh"},
        "_LM_EFFORT_ALIASES": {"off": "none", "on": "medium"}, "_LM_EFFORT_CLAMP": {"max": "xhigh", "ultra": "xhigh"}}
    resolve = isolated_function((root / "agent/lmstudio_reasoning.py").read_text(), "resolve_lmstudio_effort", namespace)
    assert resolve(reasoning, ["off", "on"]) == expected
