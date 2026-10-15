"""One current engine, bounded discovery cache, and strict native admission."""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import pytest

spec = importlib.util.spec_from_file_location("native_inference_test", Path(__file__).resolve().parents[1] / "runtime/hermes/native_inference.py")
native = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = native
spec.loader.exec_module(native)

@pytest.fixture
def helpers(monkeypatch):
    caps, chat, efforts = ModuleType("hermes_cli.models_reasoning_caps"), ModuleType("hermes_cli.chat_catalog"), ModuleType("agent.reasoning_effort")
    caps.parse_openrouter_reasoning_capabilities = lambda item: item.get("fixture_caps")
    chat.catalog_item_is_generation = lambda item: item.get("type") in {"image", "video"}
    efforts.EFFORT_LADDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
    efforts.OPENAI_COMPAT_WIRE_EFFORTS = efforts.EFFORT_LADDER[:-1]
    for module in (caps, chat, efforts):
        monkeypatch.setitem(sys.modules, module.__name__, module)

def engine(**kwargs):
    kwargs.setdefault("wire_kind", "custom")
    return native.Engine("current-engine", "alpha", "Current engine", "http://engine.test/v1", "synthetic-secret", **kwargs)

def supported(mandatory=False):
    return {"id": "alpha", "supported_parameters": ["reasoning_effort"], "fixture_caps": {"supports_reasoning": True,
        "supported_efforts": ["none", "high", "low", "not-a-native-effort"], "mandatory": mandatory}}

def test_actual_models_only_and_unknown_thinking_stays_unknown(helpers):
    current = native.NativeInferenceCatalog(load_engine=engine, fetch=lambda _: [supported(), {"id": "beta"}, {"id": "image", "type": "image"}])
    result = current.options()
    assert [row["id"] for row in result["models"]] == ["alpha", "beta"]
    assert result["models"][0]["thinking"] == {"state": "supported", "choices": ["low", "high"], "can_disable": True, "can_enable": False}
    assert result["models"][1]["thinking"] == {"state": "unknown", "choices": [], "can_disable": False, "can_enable": False}
    assert "synthetic-secret" not in str(result)
    assert "engine.test" not in str(result)
    assert "synthetic-secret" not in repr(engine())

def test_boolean_toggle_without_invented_efforts(helpers):
    pytest.importorskip("agent.lmstudio_reasoning", reason="Actual LM Studio serializer qualification requires Hermes source")
    current = native.NativeInferenceCatalog(load_engine=lambda: engine(wire_kind="lmstudio"),
        fetch=lambda _: [{"key": "alpha", "capabilities": {"reasoning": {"allowed_options": ["off", "on"]}}}])
    assert current.options()["models"][0]["thinking"] == {
        "state": "supported", "choices": [], "can_disable": True, "can_enable": True}

def test_lmstudio_level_clamping_does_not_mislabel_efforts(helpers):
    pytest.importorskip("agent.lmstudio_reasoning", reason="Actual LM Studio serializer qualification requires Hermes source")
    current = native.NativeInferenceCatalog(load_engine=lambda: engine(wire_kind="lmstudio"),
        fetch=lambda _: [{"id": "alpha", "capabilities": {"reasoning": {"allowed_options": ["off", "low", "xhigh", "max", "ultra"]}}}])
    assert current.options()["models"][0]["thinking"]["choices"] == ["low", "xhigh"]

def test_hermes_internal_effort_never_appears_as_a_distinct_wire_choice(helpers):
    row = supported()
    row["fixture_caps"]["supported_efforts"] = ["max", "ultra"]
    current = native.NativeInferenceCatalog(load_engine=engine, fetch=lambda _: [row])
    assert current.options()["models"][0]["thinking"]["choices"] == ["max"]

def test_malformed_boolean_metadata_never_creates_a_toggle(helpers):
    row = supported()
    row["capabilities"] = {"reasoning": {"allowed_options": "on"}}
    current = native.NativeInferenceCatalog(load_engine=engine, fetch=lambda _: [row])
    assert current.options()["models"][0]["thinking"]["can_enable"] is False

def test_unqualified_profile_and_nested_only_custom_parameter_stay_unknown(helpers):
    row = supported()
    unqualified = native.NativeInferenceCatalog(load_engine=lambda: engine(wire_kind=None), fetch=lambda _: [row])
    assert unqualified.options()["models"][0]["thinking"]["state"] == "unknown"
    row["supported_parameters"] = ["reasoning"]
    nested = native.NativeInferenceCatalog(load_engine=engine, fetch=lambda _: [row])
    assert nested.options()["models"][0]["thinking"]["state"] == "unknown"

def test_mixed_catalog_transport_row_is_visible_but_unavailable(helpers):
    current = native.NativeInferenceCatalog(load_engine=engine,
        fetch=lambda _: [supported(), {"id": "beta", "api_mode": "anthropic_messages"}])
    row = current.options()["models"][1]
    assert row["available"] is False and row["reason"] == "transport_unsupported"
    assert current.admission_error({"provider": "current-engine", "model": "beta"}) == "inference_model_unavailable"

def test_native_model_specific_mode_is_checked_when_engine_omits_row_mode(helpers):
    current = native.NativeInferenceCatalog(
        load_engine=lambda: engine(mode_reader=lambda model: "chat_completions" if model == "alpha" else "codex_responses"),
        fetch=lambda _: [supported(), {"id": "beta"}])
    assert current.options()["models"][1]["reason"] == "transport_unsupported"

@pytest.mark.parametrize("requested,expected", [("auto", "resolved-engine"), ("", "resolved-engine"), ("custom:office", "custom:office")])
def test_engine_identity_preserves_named_target_but_resolves_auto(monkeypatch, requested, expected):
    # This isolated resolver test does not qualify the actual bundled serializer.
    monkeypatch.setattr(native, "_qualified_wire", lambda profile: None)
    config, runtime, providers, aliases = (ModuleType(name) for name in ("hermes_cli.config", "hermes_cli.runtime_provider", "providers", "hermes_cli.providers"))
    config.load_config_readonly = lambda: {"model": {"provider": requested, "default": "alpha"}}
    runtime.resolve_runtime_provider = lambda **_: {"provider": "resolved-engine", "base_url": "http://synthetic-engine.test/v1", "api_mode": "chat_completions"}
    providers.get_provider_profile = lambda _: None
    aliases.custom_provider_aliases = lambda name, key="": {name.lower(), key.lower(), "custom:" + key.lower()}
    aliases.determine_api_mode = lambda provider, base, model: "chat_completions"
    aliases.get_provider = lambda *args, **kwargs: None
    for module in (config, runtime, providers, aliases):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    assert native.configured_engine().provider == expected

def test_current_config_identity_check_does_not_resolve_oauth_or_reject_irrelevant_changes(helpers, monkeypatch):
    from copy import deepcopy
    aliases = ModuleType("hermes_cli.providers")
    aliases.custom_provider_aliases = lambda name, key="": {name.lower(), key.lower(), "custom:" + key.lower()}
    monkeypatch.setitem(sys.modules, aliases.__name__, aliases)
    config = {"model": {"provider": "custom:office", "default": "alpha", "base_url": "http://engine.test/v1"},
        "providers": {"office": {"base_url": "http://engine.test/v1", "models": {"alpha": {"supports_reasoning": True}, "beta": {}}},
            "unrelated": {"base_url": "http://unrelated.test/v1"}}, "display": {"theme": "light"}}
    selectors = ("custom:office",)
    initial = native._config_identity(config, selectors)
    selected = native.Engine("current-engine", "alpha", "Current", "http://engine.test/v1", wire_kind="custom",
        config_identity=initial, identity_reader=lambda: native._config_identity(config, selectors))
    current = native.NativeInferenceCatalog(load_engine=lambda: selected, fetch=lambda _: [supported()])
    current.options()
    # Admission must use its config reader, never repeat provider/OAuth resolution.
    current.load_engine = lambda: pytest.fail("No second runtime credential resolution")
    body = {"provider": "current-engine", "model": "alpha"}
    config["model"]["default"] = "beta"
    config["display"]["theme"] = "dark"
    config["providers"]["unrelated"]["base_url"] = "http://changed-unrelated.test/v1"
    config["providers"]["office"]["models"]["beta"]["supports_reasoning"] = False
    assert current.admission_error(body) is None
    for mutation in (lambda: config["model"].update(base_url="http://changed.test/v1"),
            lambda: config["providers"]["office"].update(transport="anthropic_messages"),
            lambda: config["providers"]["office"]["models"]["alpha"].update(supports_reasoning=False)):
        saved = deepcopy(config)
        mutation()
        assert current.admission_error(body) == "inference_selection_changed"
        config.clear()
        config.update(saved)

def test_mandatory_reasoning_never_offers_off(helpers):
    current = native.NativeInferenceCatalog(load_engine=engine, fetch=lambda _: [supported(mandatory=True)])
    assert current.options()["models"][0]["thinking"]["can_disable"] is False
    assert current.admission_error({"provider": "current-engine", "model": "alpha", "model_options": {"reasoning": {"enabled": False}}}) == "inference_thinking_unavailable"

def test_current_model_not_offered_stays_visible_unavailable(helpers):
    current = native.NativeInferenceCatalog(load_engine=engine, fetch=lambda _: [{"id": "beta"}])
    row = current.options()["models"][-1]
    assert row["id"] == "alpha" and row["available"] is False and row["reason"] == "not_offered"

def test_cache_refresh_and_failed_refresh_never_offer_stale_models(helpers):
    now, calls, result = [1000], [], [[supported()]]
    def fetch(_):
        calls.append(now[0])
        if isinstance(result[0], Exception):
            raise result[0]
        return result[0]
    current = native.NativeInferenceCatalog(load_engine=engine, fetch=fetch, clock=lambda: now[0])
    first = current.options()
    first["models"].clear()
    now[0] += 59
    assert current.options()["models"] and len(calls) == 1
    current.options(refresh=True)
    assert len(calls) == 2
    now[0] += 61
    result[0] = RuntimeError("synthetic-secret at engine.test")
    unavailable = current.options()
    assert len(calls) == 3 and unavailable["state"] == "unavailable"
    assert unavailable["models"][0]["reason"] == "catalog_unavailable"
    assert current.admission_error({"provider": "current-engine", "model": "alpha"}) == "inference_catalog_unavailable"
    assert "synthetic-secret" not in str(unavailable)

def test_incompatible_transport_does_not_probe_http(helpers):
    current = native.NativeInferenceCatalog(load_engine=lambda: engine(api_mode="anthropic_messages"),
        fetch=lambda _: pytest.fail("No incompatible transport discovery"))
    assert current.options()["models"][0]["reason"] == "transport_unsupported"

@pytest.mark.parametrize("replacement", [
    native.Engine("different-engine", "alpha", "Changed", "http://engine.test/v1"),
    native.Engine("current-engine", "alpha", "Changed", "http://changed.test/v1"),
    native.Engine("current-engine", "alpha", "Changed", "http://engine.test/v1", api_mode="anthropic_messages"),
    native.Engine("current-engine", "alpha", "Changed", "http://engine.test/v1", headers={"X-Route": "changed"}),
])
def test_cached_catalog_never_crosses_a_changed_current_engine(helpers, replacement):
    configured, calls = [engine()], []
    current = native.NativeInferenceCatalog(load_engine=lambda: configured[0], fetch=lambda _: (calls.append(True) or [supported()]))
    assert current.options()["state"] == "available"
    configured[0] = replacement
    assert current.admission_error({"provider": "current-engine", "model": "alpha"}) == "inference_selection_changed"
    assert len(calls) == 1

def test_credential_rotation_keeps_same_engine_without_another_catalog_get(helpers):
    configured, calls = [engine()], []
    current = native.NativeInferenceCatalog(load_engine=lambda: configured[0], fetch=lambda _: (calls.append(True) or [supported()]))
    current.options()
    configured[0] = native.Engine("current-engine", "alpha", "Current engine", "http://engine.test/v1", "rotated-synthetic-secret")
    assert current.admission_error({"provider": "current-engine", "model": "alpha"}) is None
    assert len(calls) == 1

@pytest.mark.parametrize("changes,error", [
    ({"provider": "different"}, "inference_selection_changed"), ({"model": "missing"}, "inference_model_unavailable"),
    ({"model_options": {"service_tier": "priority"}}, "inference_selection_invalid"),
    ({"model_options": {"reasoning": {"enabled": True, "effort": "max"}}}, "inference_thinking_unavailable"),
    ({"model_options": {"reasoning": {"enabled": 0}}}, "inference_thinking_unavailable")])
def test_native_admission_never_substitutes_unsupported_choice(helpers, changes, error):
    current = native.NativeInferenceCatalog(load_engine=engine, fetch=lambda _: [supported()])
    assert current.admission_error({"provider": "current-engine", "model": "alpha", **changes}) == error

def test_native_supported_boolean_and_effort_choices_admitted(helpers):
    current = native.NativeInferenceCatalog(load_engine=engine, fetch=lambda _: [supported()])
    for reasoning in ({"enabled": False}, {"enabled": True, "effort": "high"}):
        assert current.admission_error({"provider": "current-engine", "model": "alpha", "model_options": {"reasoning": reasoning}}) is None
    assert current.admission_error({"provider": "current-engine", "model": "alpha", "model_options": {"reasoning": {"enabled": True}}}) == "inference_thinking_unavailable"

def test_native_lmstudio_toggle_admitted(helpers):
    pytest.importorskip("agent.lmstudio_reasoning", reason="Actual LM Studio serializer qualification requires Hermes source")
    toggle = native.NativeInferenceCatalog(load_engine=lambda: engine(wire_kind="lmstudio"),
        fetch=lambda _: [{"id": "alpha", "capabilities": {"reasoning": {"allowed_options": ["off", "on"]}}}])
    assert toggle.admission_error({"provider": "current-engine", "model": "alpha", "model_options": {"reasoning": {"enabled": True}}}) is None

def test_unmarked_native_client_bypasses_catalog(monkeypatch):
    monkeypatch.setattr(native, "_catalog", lambda _: pytest.fail("Unmarked native clients stay unchanged"))
    assert asyncio.run(native.inference_admission_error(object(), {"model": "other-client-model"})) is None

def test_conflicting_session_override_rejected_before_discovery(monkeypatch):
    monkeypatch.setattr(native, "_catalog", lambda _: pytest.fail("Conflict must stop before discovery"))
    adapter = SimpleNamespace(_session_model_override_for=lambda _: {"model": "other", "provider": "current-engine"})
    assert asyncio.run(native.inference_admission_error(adapter,
        {"radhouse_inference": True, "provider": "current-engine", "model": "alpha", "session_id": "synthetic-session"})) == "inference_selection_changed"


@pytest.mark.parametrize("field", ["base_url", "api_key", "command", "args", "api_mode", "extra_headers", "request_overrides"])
def test_matching_model_route_cannot_redirect_the_selected_engine(monkeypatch, field):
    monkeypatch.setattr(native, "_catalog", lambda _: pytest.fail("Pinned route conflict stops before discovery"))
    adapter = SimpleNamespace(_session_model_override_for=lambda _: None,
        _resolve_route=lambda _: {"model": "alpha", "provider": "current-engine", field: "synthetic-pin"})
    assert asyncio.run(native.inference_admission_error(adapter,
        {"radhouse_inference": True, "provider": "current-engine", "model": "alpha"})) == "inference_selection_changed"

def test_discovery_calls_only_current_endpoint_once_and_keeps_headers_native(monkeypatch):
    calls = []
    models, local, token = ModuleType("hermes_cli.models"), ModuleType("hermes_cli.models_local"), ModuleType("agent.command_token_source")
    models._get_json = lambda url, **kwargs: (calls.append((url, kwargs)) or {"data": [{"id": "alpha"}]})
    models._custom_provider_ssl_context = lambda _: None
    models._HERMES_USER_AGENT = "synthetic-hermes"
    local._lmstudio_server_root = lambda base: base.removesuffix("/v1")
    local._root_for_ollama_native_api = local._lmstudio_server_root
    token.materialize_probe_api_key = lambda value: value
    for module in (models, local, token):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    assert native.discover(engine(headers={"X-Synthetic-Secret": "native-only"})) == [{"id": "alpha"}]
    assert len(calls) == 1 and calls[0][0] == "http://engine.test/v1/models"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer synthetic-secret"
    assert calls[0][1]["headers"]["X-Synthetic-Secret"] == "native-only"

def test_actual_hermes_http_helper_preserves_engine_metadata(tmp_path, monkeypatch):
    """Execute the pinned HTTP/parser functions, isolated from unrelated CLI dependencies."""
    import ast
    import gzip
    import json
    from typing import Any, Optional
    import urllib.request
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Thread
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "synthetic-hermes-home"))
    package = importlib.util.find_spec("hermes_cli")
    if package is None:
        pytest.skip("Hermes source is required for the actual HTTP-helper qualification")
    root = Path(package.origin).parent
    def isolated_function(path, name, namespace):
        tree = ast.parse(path.read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        code = ast.Module(body=[function], type_ignores=[])
        exec(compile(code, str(path), "exec"), namespace)
        return namespace[name]
    models, local, token, caps, efforts, chat = (ModuleType(name) for name in (
        "hermes_cli.models", "hermes_cli.models_local", "agent.command_token_source",
        "hermes_cli.models_reasoning_caps", "agent.reasoning_effort", "hermes_cli.chat_catalog"))
    models._get_json = isolated_function(root / "models.py", "_get_json", {
        "urllib": urllib, "gzip": gzip, "json": json, "Any": Any, "Optional": Optional,
        "_urlopen_model_catalog_request": urllib.request.urlopen})
    caps.parse_openrouter_reasoning_capabilities = isolated_function(root / "models_reasoning_caps.py",
        "parse_openrouter_reasoning_capabilities", {"Any": Any, "Optional": Optional})
    models._custom_provider_ssl_context = lambda _: None
    models._HERMES_USER_AGENT = "pinned-hermes-fixture"
    local._lmstudio_server_root = lambda base: base.removesuffix("/v1")
    local._root_for_ollama_native_api = local._lmstudio_server_root
    token.materialize_probe_api_key = lambda value: value
    efforts.EFFORT_LADDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
    efforts.OPENAI_COMPAT_WIRE_EFFORTS = efforts.EFFORT_LADDER[:-1]
    chat.catalog_item_is_generation = lambda _: False
    for module in (models, local, token, caps, efforts, chat):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    calls = []
    rows = [{"id": "alpha", "supported_parameters": ["reasoning_effort"],
        "reasoning": {"supported_efforts": ["none", "low", "high"], "mandatory": False}},
        {"id": "beta", "supported_parameters": []}, {"id": "uncatalogued"}]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.path, self.headers.get("Authorization")))
            data = json.dumps({"data": rows}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def log_message(self, *args):
            pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        configured = native.Engine("custom", "alpha", "Fixture engine",
            f"http://127.0.0.1:{server.server_port}/v1", "fixture-only-token", wire_kind="custom")
        current = native.NativeInferenceCatalog(load_engine=lambda: configured)
        result = current.options()
        assert calls == [("/v1/models", "Bearer fixture-only-token")]
        assert result["state"] == "available"
        assert result["models"][0]["thinking"]["choices"] == ["low", "high"]
        assert result["models"][1]["thinking"]["state"] == "unsupported"
        assert result["models"][2]["thinking"]["state"] == "unknown"
        current.options()
        assert len(calls) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
