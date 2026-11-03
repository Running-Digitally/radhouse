"""OpenAI is opt-in, account-discovered, and uses the pinned Responses wire."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


native = load("openai_inference_test", ROOT / "runtime/hermes/native_inference.py")
overlay = load("openai_overlay_test", ROOT / "runtime/hermes/overlay.py")


def engine(**changes):
    return native.Engine(**{"provider": "custom:openai", "model": "gpt-6.1-sol", "label": "OpenAI",
        "base_url": "https://api.openai.com/v1", "api_key": "synthetic-private-key",
        "api_mode": "codex_responses", "wire_kind": "custom", **changes})


def catalog(**changes):
    return native.NativeInferenceCatalog(load_engine=lambda: engine(**changes),
        fetch=lambda _: [{"id": model} for model in native.OPENAI_MODELS] + [{"id": "unrequested-model"}])


def test_only_requested_account_visible_models_and_documented_controls():
    result = catalog().options()
    assert [row["label"] for row in result["models"]] == list(native.OPENAI_MODELS.values())
    assert "synthetic-private-key" not in str(result)
    assert "api.openai.com" not in str(result)
    assert result["state"] == "available"
    for row in result["models"]:
        assert row["thinking"]["choices"] == ["low", "medium", "high", "xhigh", "max"]
        assert row["thinking"]["can_disable"] is (row["id"] == "gpt-6.1-terra")
        assert row["thinking"]["can_enable"] is False


@pytest.mark.parametrize("changes", [
    {"provider": "custom:other"}, {"wire_kind": None}, {"headers": {"Authorization": "other"}},
    {"base_url": "https://api.openai.com.attacker.test/v1"}, {"base_url": "http://api.openai.com/v1"},
    {"base_url": "https://api.openai.com/v1?route=other"},
])
def test_unqualified_responses_routes_stay_unavailable(changes):
    assert catalog(**changes).options()["models"][0]["reason"] == "transport_unsupported"


def test_absent_model_and_failed_refresh_never_fall_back():
    current = catalog()
    current.fetch = lambda _: [{"id": "gpt-6.1-terra"}]
    row = current.options()["models"][0]
    assert row["available"] is False
    assert row["reason"] == "not_offered"
    body = {"provider": "custom:openai", "model": "gpt-6-astra"}
    assert current.admission_error(body) == "inference_model_unavailable"
    def unavailable(_):
        raise RuntimeError("private upstream details")
    current.fetch = unavailable
    result = current.options(refresh=True)
    assert result["state"] == "unavailable"
    assert "private upstream" not in str(result)
    assert current.admission_error(body) == "inference_catalog_unavailable"


@pytest.mark.parametrize("model", list(native.OPENAI_MODELS))
@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max", "off", "ultra"])
def test_admission_checks_each_model_effort(model, effort):
    reasoning = {"enabled": False} if effort == "off" else {"enabled": True, "effort": effort}
    error = catalog().admission_error({"provider": "custom:openai", "model": model,
        "model_options": {"reasoning": reasoning}})
    supported = effort in native.OPENAI_EFFORTS or effort == "off" and model == "gpt-6.1-terra"
    assert error == (None if supported else "inference_thinking_unavailable")


@pytest.fixture
def qualified_transport(monkeypatch):
    codex = pytest.importorskip("agent.transports.codex", reason="Pinned Hermes source is required for wire qualification")
    import agent.reasoning_effort
    root = Path(agent.reasoning_effort.__file__).parent.parent
    rendered = overlay.render(root)  # Includes SHA pin checks and every existing overlay.
    patched = ModuleType("qualified_reasoning")
    exec(compile(rendered["agent/reasoning_effort.py"], "<qualified-reasoning>", "exec"), patched.__dict__)
    monkeypatch.setattr(codex, "codex_supported_efforts", patched.codex_supported_efforts)
    return codex.ResponsesApiTransport()


@pytest.mark.parametrize("model", list(native.OPENAI_MODELS))
@pytest.mark.parametrize("effort", native.OPENAI_EFFORTS)
def test_actual_responses_tools_and_effort_survive_serialization(qualified_transport, model, effort):
    wire = qualified_transport.build_kwargs(model, [{"role": "user", "content": "Synthetic fixture"}],
        [{"type": "function", "function": {"name": "fixture_lookup", "description": "Synthetic only",
          "parameters": {"type": "object", "properties": {}}}}],
        provider="custom:openai", base_url="https://api.openai.com/v1",
        reasoning_config={"enabled": True, "effort": effort})
    assert wire["model"] == model
    assert wire["reasoning"]["effort"] == effort
    assert wire["store"] is False
    assert wire["tools"][0]["name"] == "fixture_lookup"
    assert "temperature" not in wire
    assert "messages" not in wire


def test_terra_off_reaches_wire_as_none(qualified_transport):
    wire = qualified_transport.build_kwargs("gpt-6.1-terra", [{"role": "user", "content": "Synthetic"}],
        provider="custom:openai", base_url="https://api.openai.com/v1", reasoning_config={"enabled": False})
    assert wire["reasoning"]["effort"] == "none"


def test_effort_overlay_fails_closed_on_source_drift():
    with pytest.raises(ValueError, match="context_mismatch"):
        overlay.patch_openai_efforts("different upstream source")
