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
    engines = value.get("engines")
    engine_rows = []
    if engines is not None:
        if type(engines) is not list or not 1 <= len(engines) <= 4:
            raise ValueError("inference_response_invalid")
        for row in engines:
            if type(row) is not dict or type(row.get("available")) is not bool:
                raise ValueError("inference_response_invalid")
            item = {key: _text(row.get(key)) for key in ("id", "label", "current_model")}
            item["available"] = row["available"]
            if any(known["id"] == item["id"] for known in engine_rows):
                raise ValueError("inference_response_invalid")
            engine_rows.append(item)
        if engine is None or engine["id"] not in {row["id"] for row in engine_rows}:
            raise ValueError("inference_response_invalid")
    models = value.get("models")
    if type(models) is not list:
        raise ValueError("inference_response_invalid")
    result, seen = [], set()
    for row in models:
        if type(row) is not dict or type(row.get("available")) is not bool or row.get("reason") not in REASONS:
            raise ValueError("inference_response_invalid")
        model = _text(row.get("id"))
        provider = _text(row.get("provider")) if engines is not None else None
        identity = (provider, model)
        if engines is not None and provider not in {item["id"] for item in engine_rows}:
            raise ValueError("inference_response_invalid")
        if identity in seen:
            raise ValueError("inference_response_invalid")
        seen.add(identity)
        thinking = row.get("thinking")
        if type(thinking) is not dict or thinking.get("state") not in {"supported", "unsupported", "unknown"}:
            raise ValueError("inference_response_invalid")
        choices = thinking.get("choices")
        if type(choices) is not list or any(
            type(choice) is not str or not choice.isascii() or not choice.isalpha() or len(choice) > 20
            for choice in choices
        ) or len(set(choices)) != len(choices) or type(thinking.get("can_disable")) is not bool or type(thinking.get("can_enable")) is not bool:
            raise ValueError("inference_response_invalid")
        if thinking["state"] != "supported" and (choices or thinking["can_disable"] or thinking["can_enable"]):
            raise ValueError("inference_response_invalid")
        if (row["available"] and (row.get("reason") is not None or engine is None or value["state"] != "available")
                or not row["available"] and row.get("reason") is None):
            raise ValueError("inference_response_invalid")
        if row["available"] and engines is not None and not next(item["available"] for item in engine_rows if item["id"] == provider):
            raise ValueError("inference_response_invalid")
        result.append({**({"provider": provider} if engines is not None else {}), "id": model, "label": _text(row.get("label")), "available": row["available"],
            "reason": row.get("reason"), "thinking": {"state": thinking["state"],
                "choices": list(choices), "can_disable": thinking["can_disable"], "can_enable": thinking["can_enable"]}})
    return {"schema": SCHEMA, "state": value["state"], "checked_at": checked, "engine": engine,
        "current_model": _text(value.get("current_model"), optional=True), "models": result,
        **({"engines": engine_rows} if engines is not None else {})}


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
