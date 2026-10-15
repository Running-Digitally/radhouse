"""Discover only the configured engine; expose no endpoint or credential material."""
import asyncio
import ast
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import inspect
from pathlib import Path
from threading import Lock
from types import FunctionType
import time

SCHEMA = "radhouse.inference.v1"
CACHE_SECONDS = 60


def patch_selected_run(source):
    """Lock only marked selections to their admitted runtime and disable fallback.

    The source-pinned base overlay adds the unique ``disable_tools`` launch
    keyword. Reject a changed call shape rather than patching another executor.
    """
    anchor = "            disable_tools=disable_tools,\n"
    if source.count(anchor) != 1:
        raise ValueError("hermes_inference_overlay_context_mismatch")
    tree = ast.parse(source)
    launches = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == "_RunLaunch"]
    if len(launches) != 1:
        raise ValueError("hermes_inference_overlay_context_mismatch")
    kwargs = next((keyword.value for keyword in launches[0].keywords if keyword.arg == "agent_kwargs"), None)
    if (not isinstance(kwargs, ast.Call) or not isinstance(kwargs.func, ast.Name)
            or kwargs.func.id != "dict" or any(keyword.arg == "confirmed_runtime_lock" for keyword in kwargs.keywords)):
        raise ValueError("hermes_inference_overlay_context_mismatch")
    disable = [keyword.value for keyword in kwargs.keywords if keyword.arg == "disable_tools"]
    if len(disable) != 1 or not isinstance(disable[0], ast.Name) or disable[0].id != "disable_tools":
        raise ValueError("hermes_inference_overlay_context_mismatch")
    result = source.replace(anchor,
        anchor + '            confirmed_runtime_lock=(body.get("radhouse_inference") is True),\n', 1)
    patched = ast.parse(result)
    launch = next(node for node in ast.walk(patched) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == "_RunLaunch")
    kwargs = next(keyword.value for keyword in launch.keywords if keyword.arg == "agent_kwargs")
    flags = [keyword.value for keyword in kwargs.keywords if keyword.arg == "confirmed_runtime_lock"]
    expected = ast.parse('body.get("radhouse_inference") is True', mode="eval").body
    if len(flags) != 1 or ast.dump(flags[0]) != ast.dump(expected):
        raise ValueError("hermes_inference_overlay_context_mismatch")
    return result


@dataclass(frozen=True)
class Engine:
    provider: str
    model: str
    label: str
    base_url: str = field(repr=False)
    api_key: object = field(default="", repr=False)
    api_mode: str = "chat_completions"
    headers: dict = field(default_factory=dict, repr=False)
    wire_kind: str | None = field(default=None, repr=False)
    config_identity: object = field(default=None, repr=False)
    identity_reader: object = field(default=None, repr=False)
    mode_reader: object = field(default=None, repr=False)


def _native_model_mode_reader(provider, base_url):
    """Use native model/host semantics without its optional models.dev fetch.

    A copied function namespace narrows just get_provider's network policy; the
    shared native module is unchanged, including under concurrent requests.
    """
    from hermes_cli.providers import determine_api_mode, get_provider
    scope = {**determine_api_mode.__globals__,
        "get_provider": lambda name: get_provider(name, allow_network=False)}
    bounded = FunctionType(determine_api_mode.__code__, scope, determine_api_mode.__name__, determine_api_mode.__defaults__)
    return lambda model: bounded(provider, base_url, model)


def _qualified_wire(profile):
    """Only pinned, qualified native serializers may turn metadata into controls."""
    import hermes_cli
    try:
        method = profile.build_api_kwargs_extras
        source = Path(inspect.getsourcefile(method)).resolve()
        bundled = Path(hermes_cli.__file__).resolve().parent.parent / "plugins/model-providers"
        for kind in ("custom", "lmstudio"):
            if source == bundled / kind / "__init__.py":
                return kind
    except (AttributeError, TypeError, ValueError):
        pass
    return None


def _config_identity(config, selectors):
    """Keep only relevant routing fields; never resolve auth or mutate config."""
    from hermes_cli.providers import custom_provider_aliases
    fields = ("enabled", "base_url", "url", "api", "api_mode", "transport", "openai_runtime",
        "command", "args", "extra_headers", "extra_body", "capabilities", "models")
    def pick(value):
        return {key: deepcopy(value[key]) for key in fields if key in value} if isinstance(value, dict) else {}
    model = config.get("model", {})
    identity = {"selector": model.get("provider") if isinstance(model, dict) else None,
        "model": pick(model), "providers": []}
    providers = config.get("providers", {})
    entries = list(providers.items()) if isinstance(providers, dict) else []
    legacy = config.get("custom_providers", [])
    if isinstance(legacy, list):
        entries += [(str(entry.get("provider_key") or entry.get("name") or ""), entry)
            for entry in legacy if isinstance(entry, dict)]
    normalized = {str(name or "").strip().lower() for name in selectors}
    for key, entry in entries:
        if not isinstance(entry, dict):
            continue
        aliases = custom_provider_aliases(str(entry.get("name") or key), str(key))
        if normalized.intersection(aliases):
            identity["providers"].append({"key": key, "fields": pick(entry)})
    return identity


def _identity_for_model(identity, model):
    selected = deepcopy(identity)
    for value in [selected["model"], *(entry["fields"] for entry in selected["providers"])]:
        models = value.get("models")
        if isinstance(models, dict):
            value["models"] = {model: models[model]} if model in models else {}
    return selected


def configured_engine():
    from hermes_cli.config import load_config_readonly
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from providers import get_provider_profile

    config = load_config_readonly()
    model = config.get("model", {})
    if not isinstance(model, dict):
        model = {"default": str(model or "")}
    current = str(model.get("default", model.get("name", "")) or "")
    requested = str(model.get("provider") or "")
    runtime = resolve_runtime_provider(requested=requested or None, target_model=current or None)
    # A named custom selector owns its endpoint; "auto" does not own an engine.
    provider = requested if requested and requested != "auto" else str(runtime.get("provider") or "")
    profile = get_provider_profile(str(runtime.get("provider") or provider))
    label = getattr(profile, "display_name", "") or provider
    headers = runtime.get("extra_headers") or {}
    selectors = ((requested, provider) if runtime.get("provider") == "custom" and provider != "custom"
        else (requested, provider, runtime.get("provider")))
    identity = _config_identity(config, selectors)
    return Engine(provider, current, label, str(runtime.get("base_url") or ""),
        runtime.get("api_key") or "", str(runtime.get("api_mode") or "chat_completions"),
        dict(headers) if isinstance(headers, dict) else {}, _qualified_wire(profile), identity,
        lambda: _config_identity(load_config_readonly(), selectors),
        _native_model_mode_reader(provider, str(runtime.get("base_url") or "")))


def discover(engine):
    """One native-aware catalog GET, with Hermes's credential-safe HTTP opener."""
    from agent.command_token_source import materialize_probe_api_key
    from hermes_cli.models import _get_json, _custom_provider_ssl_context, _HERMES_USER_AGENT
    from hermes_cli.models_local import _lmstudio_server_root, _root_for_ollama_native_api

    base = engine.base_url.rstrip("/")
    if not base:
        raise ValueError("inference_engine_unavailable")
    headers = {"Accept": "application/json", "User-Agent": _HERMES_USER_AGENT}
    token = materialize_probe_api_key(engine.api_key)
    if token:
        headers["Authorization"] = "Bearer " + token
    headers.update(engine.headers)
    if engine.provider == "lmstudio":
        url, key = _lmstudio_server_root(base) + "/api/v1/models", "models"
    elif engine.provider in {"ollama", "custom:ollama"}:
        url, key = _root_for_ollama_native_api(base) + "/api/tags", "models"
    else:
        url, key = base + "/models", "data"
    ssl_context = _custom_provider_ssl_context(base)
    payload = _get_json(url, timeout=5.0, headers=headers,
        **({"ssl_context": ssl_context} if ssl_context is not None else {}))
    rows = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("inference_catalog_invalid")
    return rows


def _identifier(value):
    return type(value) is str and bool(value) and len(value) <= 512 and not any(ord(c) < 32 for c in value)


def _thinking(item, engine):
    from agent.reasoning_effort import OPENAI_COMPAT_WIRE_EFFORTS
    from hermes_cli.models_reasoning_caps import parse_openrouter_reasoning_capabilities

    unknown = {"state": "unknown", "choices": [], "can_disable": False, "can_enable": False}
    parameters = item.get("supported_parameters")
    parsed = item
    if isinstance(parameters, list) and "reasoning_effort" in parameters:
        parsed = {**item, "supported_parameters": [*parameters, "reasoning"]}
    detail = parse_openrouter_reasoning_capabilities(parsed)
    raw_caps = item.get("capabilities")
    reasoning = raw_caps.get("reasoning") if isinstance(raw_caps, dict) else None
    allowed = reasoning.get("allowed_options") if isinstance(reasoning, dict) else None
    if isinstance(allowed, list) and all(type(option) is str for option in allowed):
        allowed = [option.strip().lower() for option in allowed]
    else:
        allowed = None
    if detail is None and allowed is not None:
        detail = {"supports_reasoning": any(option != "off" for option in allowed),
            "supported_efforts": allowed, "mandatory": "off" not in allowed}
    if detail is None:
        return unknown
    if detail.get("supports_reasoning") is not True:
        return {**unknown, "state": "unsupported"}
    if engine.wire_kind not in {"custom", "lmstudio"}:
        return unknown
    if engine.wire_kind == "custom":
        parameters = item.get("supported_parameters")
        # The custom serializer sends top-level reasoning_effort, not the nested
        # reasoning field accepted by some aggregators. Both schema and value
        # evidence must describe the actual wire it can carry.
        if not isinstance(parameters, list) or "reasoning_effort" not in parameters:
            return unknown
    # Only actual engine-published choices, intersected with the native request decoder.
    efforts = detail.get("supported_efforts") or []
    choices = [effort for effort in OPENAI_COMPAT_WIRE_EFFORTS if effort != "none" and effort in efforts]
    if allowed is not None and engine.wire_kind == "lmstudio":
        from agent.lmstudio_reasoning import resolve_lmstudio_effort
        # LM Studio's advertised vocabulary may exceed the native serializer's
        # ceiling. Offer only levels it will actually send unchanged.
        choices = [effort for effort in choices
            if resolve_lmstudio_effort({"enabled": True, "effort": effort}, allowed) == effort]
    # A graded reasoning parameter is not evidence of a separate boolean On
    # operation. Hermes's custom serializer omits enabled=True without an effort.
    explicit_on = engine.wire_kind == "lmstudio" and allowed is not None and "on" in allowed
    off = ("off" in allowed if engine.wire_kind == "lmstudio" and allowed is not None else "none" in efforts)
    return {"state": "supported", "choices": choices, "can_disable": off and not detail.get("mandatory", False), "can_enable": explicit_on}


class NativeInferenceCatalog:
    def __init__(self, *, load_engine=configured_engine, fetch=discover, clock=time.time):
        self.load_engine, self.fetch, self.clock = load_engine, fetch, clock
        self.lock = Lock()
        self.cached = None
        self.until = 0
        self.engine = None

    def options(self, *, refresh=False):
        with self.lock:
            now = self.clock()
            if not refresh and self.cached is not None and now < self.until:
                return deepcopy(self.cached)
            checked = datetime.fromtimestamp(now, timezone.utc).isoformat()
            result = {"schema": SCHEMA, "state": "unavailable", "checked_at": checked,
                "engine": None, "current_model": None, "models": []}
            self.engine = None
            try:
                engine = self.load_engine()
                if not _identifier(engine.provider) or not _identifier(engine.model) or not _identifier(engine.label):
                    raise ValueError("inference_engine_invalid")
                self.engine = engine
                result.update(engine={"id": engine.provider, "label": engine.label}, current_model=engine.model)
                if engine.api_mode != "chat_completions":
                    result["models"] = [self._row(engine.model, available=False, reason="transport_unsupported")]
                else:
                    from hermes_cli.chat_catalog import catalog_item_is_generation
                    rows, seen = [], set()
                    for item in self.fetch(engine):
                        if not isinstance(item, dict) or catalog_item_is_generation(item):
                            continue
                        model = item.get("id") or item.get("key") or item.get("name")
                        if not _identifier(model) or model in seen or str(item.get("type") or "").lower() == "embedding":
                            continue
                        seen.add(model)
                        transport = item.get("api_mode")
                        mode = engine.mode_reader(model) if engine.mode_reader is not None else engine.api_mode
                        incompatible = mode != "chat_completions" or (transport is not None and transport != "chat_completions")
                        rows.append(self._row(model, available=not incompatible,
                            reason="transport_unsupported" if incompatible else None,
                            thinking=_thinking(item, engine) if not incompatible else None))
                    if engine.model not in seen:
                        rows.append(self._row(engine.model, available=False, reason="not_offered"))
                    result.update(state="available", models=rows)
            except Exception:
                # No stale model is made selectable after a failed refresh.
                if result["current_model"]:
                    result["models"] = [self._row(result["current_model"], available=False, reason="catalog_unavailable")]
            self.cached, self.until = result, now + CACHE_SECONDS
            return deepcopy(result)

    @staticmethod
    def _row(model, *, available=True, reason=None, thinking=None):
        return {"id": model, "label": model, "available": available, "reason": reason,
            "thinking": thinking or {"state": "unknown", "choices": [], "can_disable": False, "can_enable": False}}

    def admission_error(self, body):
        if not any(key in body for key in ("provider", "model", "model_options")):
            return None
        catalog = self.options()
        with self.lock:
            # A concurrent explicit Refresh may have replaced both objects.
            catalog, admitted_engine = deepcopy(self.cached), self.engine
        if catalog["state"] != "available" or catalog["engine"] is None:
            return "inference_catalog_unavailable"
        try:
            if admitted_engine is None:
                return "inference_catalog_unavailable"
            if admitted_engine.identity_reader is not None:
                changed = _identity_for_model(admitted_engine.config_identity, body.get("model")) != _identity_for_model(
                    admitted_engine.identity_reader(), body.get("model"))
            else:
                # Injected test engines have no private config reader.
                current_engine = self.load_engine()
                changed = (admitted_engine.provider, admitted_engine.base_url.rstrip("/"), admitted_engine.api_mode,
                    admitted_engine.headers) != (current_engine.provider, current_engine.base_url.rstrip("/"),
                    current_engine.api_mode, current_engine.headers)
        except Exception:
            return "inference_catalog_unavailable"
        # Credential rotation does not change an engine. Endpoint/transport or
        # configured selector changes do; do not apply a cached previous catalog.
        if changed:
            return "inference_selection_changed"
        if body.get("provider") != catalog["engine"]["id"]:
            return "inference_selection_changed"
        row = next((row for row in catalog["models"] if row["id"] == body.get("model")), None)
        if row is None or not row["available"]:
            return "inference_model_unavailable"
        if "model_options" not in body:
            return None
        options = body["model_options"]
        if type(options) is not dict or set(options) != {"reasoning"} or type(options["reasoning"]) is not dict:
            return "inference_selection_invalid"
        reasoning, caps = options["reasoning"], row["thinking"]
        if caps["state"] != "supported":
            return "inference_thinking_unavailable"
        if set(reasoning) == {"enabled"} and reasoning.get("enabled") is False and caps["can_disable"]:
            return None
        if set(reasoning) == {"enabled"} and reasoning.get("enabled") is True and caps["can_enable"]:
            return None
        if (set(reasoning) == {"enabled", "effort"} and reasoning.get("enabled") is True
                and reasoning.get("effort") in caps["choices"]):
            return None
        return "inference_thinking_unavailable"


def _catalog(adapter):
    from hermes_constants import get_hermes_home
    # Routed profiles on one adapter must never reuse another profile's engine metadata.
    catalogs = getattr(adapter, "_radhouse_inference_catalogs", None)
    if catalogs is None:
        catalogs = adapter._radhouse_inference_catalogs = {}
    profile = str(get_hermes_home())
    if profile not in catalogs:
        catalogs[profile] = NativeInferenceCatalog()
    return catalogs[profile]


async def handle_inference(adapter, request):
    from aiohttp import web
    error = adapter._check_auth(request)
    if error is not None:
        return error
    refresh = request.query.get("refresh") == "true"
    result = await asyncio.to_thread(_catalog(adapter).options, refresh=refresh)
    error = adapter._check_auth(request)
    if error is not None:
        return error
    return web.json_response(result, headers={"Cache-Control": "no-store"})


async def inference_admission_error(adapter, body):
    """Call only for a genuinely new run, after durable replay lookup."""
    if body.get("radhouse_inference") is not True:
        return None
    override = adapter._session_model_override_for(body.get("session_id"))
    if override and (override.get("model") != body.get("model") or override.get("provider") != body.get("provider")):
        return "inference_selection_changed"
    route = adapter._resolve_route(body.get("model"))
    if route and any(key in route for key in ("base_url", "api_key", "command", "args", "api_mode", "extra_headers", "request_overrides")):
        return "inference_selection_changed"
    if route and (route.get("model", body.get("model")) != body.get("model")
            or route.get("provider", body.get("provider")) != body.get("provider")):
        return "inference_selection_changed"
    return await asyncio.to_thread(_catalog(adapter).admission_error, body)
