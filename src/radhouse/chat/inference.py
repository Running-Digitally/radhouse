"""Model choices belong to the configured engine, and to one submitted turn."""
from copy import deepcopy
from datetime import datetime

from radhouse.domain.tasks import Rejected

SCHEMA = "radhouse.inference.v1"
REASONS = {None, "transport_unsupported", "not_offered", "catalog_unavailable"}


def _text(value, *, optional=False):
    if optional and value is None:
        return None
    if type(value) is not str or not value or len(value) > 512 or any(ord(c) < 32 for c in value):
        raise ValueError("inference_response_invalid")
    return value


def _normalize_engines(rows, default):
    if type(rows) is not list or not 1 <= len(rows) <= 4:
        raise ValueError("inference_response_invalid")
    result, seen = [], set()
    for row in rows:
        if type(row) is not dict or type(row.get("available")) is not bool:
            raise ValueError("inference_response_invalid")
        item = {key: _text(row.get(key)) for key in ("id", "label", "current_model")}
        item["available"] = row["available"]
        if item["id"] in seen:
            raise ValueError("inference_response_invalid")
        seen.add(item["id"])
        result.append(item)
    if default is None or default["id"] not in seen:
        raise ValueError("inference_response_invalid")
    return result


def _normalize_thinking(value):
    if type(value) is not dict or value.get("state") not in {"supported", "unsupported", "unknown"}:
        raise ValueError("inference_response_invalid")
    choices = value.get("choices")
    if type(choices) is not list or any(
        type(choice) is not str or not choice.isascii() or not choice.isalpha() or len(choice) > 20
        for choice in choices
    ) or len(set(choices)) != len(choices):
        raise ValueError("inference_response_invalid")
    if type(value.get("can_disable")) is not bool or type(value.get("can_enable")) is not bool:
        raise ValueError("inference_response_invalid")
    if value["state"] != "supported" and (choices or value["can_disable"] or value["can_enable"]):
        raise ValueError("inference_response_invalid")
    return {"state": value["state"], "choices": list(choices),
        "can_disable": value["can_disable"], "can_enable": value["can_enable"]}



def _check_model_availability(row, state, engine, enrolled):
    if not row["available"]:
        if row.get("reason") is None:
            raise ValueError("inference_response_invalid")
        return
    if row.get("reason") is not None or engine is None or state != "available":
        raise ValueError("inference_response_invalid")
    if enrolled and not engine["available"]:
        raise ValueError("inference_response_invalid")


def _normalize_model(row, state, default, engines):
    if type(row) is not dict or type(row.get("available")) is not bool or row.get("reason") not in REASONS:
        raise ValueError("inference_response_invalid")
    provider = _text(row.get("provider")) if engines is not None else None
    engine = next((item for item in engines if item["id"] == provider), None) if engines is not None else default
    if engines is not None and engine is None:
        raise ValueError("inference_response_invalid")
    _check_model_availability(row, state, engine, engines is not None)
    return {**({"provider": provider} if engines is not None else {}),
        "id": _text(row.get("id")), "label": _text(row.get("label")),
        "available": row["available"], "reason": row.get("reason"),
        "thinking": _normalize_thinking(row.get("thinking"))}


def normalize_catalog(value):
    """Allowlist the public shape; provider URLs, headers and credentials stay native."""
    if type(value) is not dict or value.get("schema") != SCHEMA or value.get("state") not in {"available", "unavailable"}:
        raise ValueError("inference_response_invalid")
    checked = value.get("checked_at")
    if checked is not None:
        _text(checked)
        if datetime.fromisoformat(checked.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("inference_response_invalid")
    engine = value.get("engine")
    if engine is not None:
        if type(engine) is not dict:
            raise ValueError("inference_response_invalid")
        engine = {key: _text(engine.get(key)) for key in ("id", "label")}
    engines = _normalize_engines(value["engines"], engine) if value.get("engines") is not None else None
    models = value.get("models")
    if type(models) is not list:
        raise ValueError("inference_response_invalid")
    result, seen = [], set()
    for row in models:
        model = _normalize_model(row, value["state"], engine, engines)
        identity = (model.get("provider"), model["id"])
        if identity in seen:
            raise ValueError("inference_response_invalid")
        seen.add(identity)
        result.append(model)
    return {"schema": SCHEMA, "state": value["state"], "checked_at": checked, "engine": engine,
        "current_model": _text(value.get("current_model"), optional=True), "models": result,
        **({"engines": engines} if engines is not None else {})}


def validate_selection(selection, catalog):
    """Return only the immutable native kwargs a new turn may dispatch."""
    if selection is None:
        return {}
    if type(selection) is not dict or set(selection) not in ({"model", "thinking"}, {"provider", "model", "thinking"}):
        raise Rejected("inference_selection_invalid", 422)
    model, thinking = selection["model"], selection["thinking"]
    provider = selection.get("provider")
    if "provider" in selection:
        try:
            _text(provider)
        except ValueError:
            raise Rejected("inference_selection_invalid", 422) from None
        if model is None:
            raise Rejected("inference_selection_invalid", 422)
    if model is not None:
        try:
            _text(model)
        except ValueError:
            raise Rejected("inference_selection_invalid", 422) from None
    if type(thinking) is not str:
        raise Rejected("inference_selection_invalid", 422)
    if model is None and thinking == "default":
        return {}
    if catalog["state"] != "available" or catalog["engine"] is None:
        raise Rejected("inference_catalog_unavailable", 503)
    selected = model or catalog["current_model"]
    provider = provider or catalog["engine"]["id"]
    row = next((row for row in catalog["models"] if row["id"] == selected
        and row.get("provider", catalog["engine"]["id"]) == provider), None)
    if row is None or not row["available"]:
        raise Rejected("inference_model_unavailable", 409)
    result = {"provider": provider, "model": row["id"]}
    caps = row["thinking"]
    if thinking == "default":
        return result
    if caps["state"] != "supported":
        raise Rejected("inference_thinking_unavailable", 409)
    if thinking == "off" and caps["can_disable"]:
        result["model_options"] = {"reasoning": {"enabled": False}}
    elif thinking == "on" and caps["can_enable"]:
        result["model_options"] = {"reasoning": {"enabled": True}}
    elif thinking in caps["choices"]:
        result["model_options"] = {"reasoning": {"enabled": True, "effort": thinking}}
    else:
        raise Rejected("inference_thinking_unavailable", 409)
    return result


class InferenceService:
    def __init__(self, hermes):
        self.hermes = hermes

    def options(self, *, refresh=False):
        try:
            path = "v1/inference/options" + ("?refresh=true" if refresh else "")
            payload, _ = self.hermes._request("GET", path, expected_status=200)
            return normalize_catalog(payload)
        except Exception:
            return {"schema": SCHEMA, "state": "unavailable", "checked_at": None,
                "engine": None, "current_model": None, "models": []}

    def resolve(self, selection):
        # Default chat remains usable even when model discovery is down.
        if selection is None or selection == {"model": None, "thinking": "default"}:
            return {}
        return deepcopy(validate_selection(selection, self.options()))
