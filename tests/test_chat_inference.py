"""Actual engine choices are rechecked; retries retain frozen native kwargs."""
from copy import deepcopy
import pytest
from radhouse.chat.inference import InferenceService, normalize_catalog, validate_selection
from radhouse.domain.tasks import Rejected

def catalog():
    return {"schema": "radhouse.inference.v1", "state": "available", "checked_at": "2026-10-08T20:00:00+00:00",
        "engine": {"id": "configured-lan", "label": "Configured engine"}, "current_model": "alpha",
        "models": [{"id": "alpha", "label": "alpha", "available": True, "reason": None,
            "thinking": {"state": "supported", "choices": ["low", "high"], "can_disable": True, "can_enable": True}},
            {"id": "beta", "label": "beta", "available": True, "reason": None,
            "thinking": {"state": "unknown", "choices": [], "can_disable": False, "can_enable": False}}]}

class Runtime:
    def __init__(self):
        self.payload, self.calls = catalog(), []
    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if isinstance(self.payload, Exception):
            raise self.payload
        return deepcopy(self.payload), {}

@pytest.mark.parametrize("selection", [None, {"model": None, "thinking": "default"}])
def test_default_never_needs_discovery(selection):
    runtime = Runtime()
    runtime.payload = RuntimeError("private URL and secret must not escape")
    assert InferenceService(runtime).resolve(selection) == {}
    assert runtime.calls == []

@pytest.mark.parametrize("thinking,options", [
    ("default", None), ("off", {"reasoning": {"enabled": False}}),
    ("on", {"reasoning": {"enabled": True}}), ("high", {"reasoning": {"enabled": True, "effort": "high"}})])
def test_selection_returns_actual_pair_and_supported_options(thinking, options):
    selected = validate_selection({"model": "alpha", "thinking": thinking}, normalize_catalog(catalog()))
    assert selected == {"provider": "configured-lan", "model": "alpha", **({"model_options": options} if options else {})}

@pytest.mark.parametrize("model,thinking,code", [
    ("beta", "high", "inference_thinking_unavailable"), ("alpha", "max", "inference_thinking_unavailable"),
    ("disappeared", "default", "inference_model_unavailable")])
def test_unknown_or_unoffered_choices_are_not_substituted(model, thinking, code):
    with pytest.raises(Rejected) as error:
        validate_selection({"model": model, "thinking": thinking}, normalize_catalog(catalog()))
    assert error.value.code == code

def test_discovery_failure_does_not_export_vendor_body():
    runtime = Runtime()
    runtime.payload = RuntimeError("Authorization=synthetic-secret https://private-engine.invalid")
    service = InferenceService(runtime)
    assert service.options() == {"schema": "radhouse.inference.v1", "state": "unavailable",
        "checked_at": None, "engine": None, "current_model": None, "models": []}
    with pytest.raises(Rejected) as error:
        service.resolve({"model": "alpha", "thinking": "default"})
    assert error.value.code == "inference_catalog_unavailable"

def test_public_sanitization_drops_connection_and_secret_fields():
    raw = catalog()
    raw["api_key"] = "synthetic-secret"
    raw["engine"]["url"] = "https://private-engine.invalid"
    raw["models"][0]["headers"] = {"Authorization": "synthetic-secret"}
    assert normalize_catalog(raw) == catalog()

@pytest.mark.parametrize("change", [
    lambda value: value["models"].append(deepcopy(value["models"][0])),
    lambda value: value["models"][1]["thinking"].update(choices=["high"]),
    lambda value: value["models"][0]["thinking"].update(choices=[{}]),
    lambda value: value.update(checked_at="2026-10-08T20:00:00"),
    lambda value: value["models"][0].update(available=True, reason="not_offered")])
def test_malformed_metadata_never_becomes_offered_control(change):
    value = catalog()
    change(value)
    with pytest.raises(ValueError):
        normalize_catalog(value)

def test_explicit_refresh_and_catalog_change_do_not_mutate_frozen_dispatch():
    runtime = Runtime()
    service = InferenceService(runtime)
    frozen = service.resolve({"model": "alpha", "thinking": "high"})
    runtime.payload["models"] = [runtime.payload["models"][1]]
    service.options(refresh=True)
    assert runtime.calls[-1][1] == "v1/inference/options?refresh=true"
    assert frozen == {"provider": "configured-lan", "model": "alpha", "model_options": {"reasoning": {"enabled": True, "effort": "high"}}}
    with pytest.raises(Rejected) as error:
        service.resolve({"model": "alpha", "thinking": "high"})
    assert error.value.code == "inference_model_unavailable"


def enrolled_catalog():
    value = catalog()
    value['engines'] = [
        {'id': 'configured-lan', 'label': 'Primary', 'available': False, 'current_model': 'alpha'},
        {'id': 'secondary', 'label': 'Secondary', 'available': True, 'current_model': 'alpha'}]
    primary = {**value['models'][0], 'provider': 'configured-lan', 'available': False, 'reason': 'catalog_unavailable'}
    secondary = {**value['models'][0], 'provider': 'secondary'}
    value['models'] = [primary, secondary]
    return value


def test_provider_pair_selects_healthy_alternate_without_changing_default():
    value = normalize_catalog(enrolled_catalog())
    assert validate_selection({'provider': 'secondary', 'model': 'alpha', 'thinking': 'high'}, value) == {
        'provider': 'secondary', 'model': 'alpha', 'model_options': {'reasoning': {'enabled': True, 'effort': 'high'}}}
    with pytest.raises(Rejected, match='inference_model_unavailable'):
        validate_selection({'model': 'alpha', 'thinking': 'default'}, value)
    assert validate_selection({'model': None, 'thinking': 'default'}, value) == {}


@pytest.mark.parametrize('mutation', [
    lambda value: value['models'][1].update(provider='unregistered'),
    lambda value: value['models'].append(deepcopy(value['models'][1])),
    lambda value: value['engines'][1].update(available=False),
    lambda value: value['engines'].append(deepcopy(value['engines'][1]))])
def test_malformed_enrolled_catalog_cannot_offer_a_pair(mutation):
    value = enrolled_catalog()
    mutation(value)
    with pytest.raises(ValueError):
        normalize_catalog(value)


def test_enrolled_catalog_sanitizes_all_providers():
    value = enrolled_catalog()
    value['engines'][1]['url'] = 'http://private.invalid'
    value['engines'][1]['api_key'] = 'synthetic-secret'
    cleaned = normalize_catalog(value)
    assert 'private.invalid' not in str(cleaned)
    assert 'synthetic-secret' not in str(cleaned)
    assert validate_selection({'provider': 'secondary', 'model': 'alpha', 'thinking': 'default'}, cleaned) == {
        'provider': 'secondary', 'model': 'alpha'}
