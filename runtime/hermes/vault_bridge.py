"""Local login operations for the already-owned Radhouse browser.

The runtime owns authentication, profile scope and the controller reservation.
It passes an internal browser access object, never one decoded from HTTP. All
inspection and filling stay inside that reservation on the same native channel.
There is no CLI, external-manager discovery or model-facing secret resolver.
"""
from pathlib import Path
import json
import os
import re
import secrets
import stat
from typing import Protocol
from urllib.parse import urlsplit


LOGIN_TOOLS = ("browser_login_list", "browser_login_fill")
LOGIN_TOOL_DEFINITIONS = (
    {
        "name": "browser_login_list",
        "description": "List saved local login handles and metadata. Passwords are never returned.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "browser_login_fill",
        "description": (
            "Fill the current page's password field from a saved local login handle. "
            "The exact saved origin must match; this does not submit the form. "
            "Complete verification codes through human browser control."
        ),
        "parameters": {
            "type": "object", "properties": {"handle": {"type": "string"}},
            "required": ["handle"], "additionalProperties": False,
        },
    },
)


class VaultRejected(ValueError):
    """A fixed code, never caller input, decrypted values or native diagnostics."""


class BrowserAccess(Protocol):
    """Trusted, controller-reserved access to one existing native generation.

    Evaluation returns only the matched ACK's result. Transport uncertainty
    propagates to the runtime, which retains its command and recovery state.
    Secret-bearing expressions must never enter argv, logs or retained payloads.
    """

    def current_origin(self) -> str: ...

    def evaluate(self, expression: str, *, secret: bool = False): ...


def _text(value, *, empty=False):
    if type(value) is not str or "\x00" in value or not empty and not value:
        raise VaultRejected("login_arguments_invalid")
    return value


def _handle(value):
    if type(value) is not str or re.fullmatch(r"vault_[a-f0-9]{12}", value) is None:
        raise VaultRejected("login_handle_invalid")
    return value


def _origin(access):
    # Transport exceptions must reach the runtime so an uncertain native ACK
    # cannot accidentally release its control reservation.
    value = access.current_origin()
    try:
        parts = urlsplit(value)
        if (type(value) is not str or parts.scheme not in {"http", "https"}
                or not parts.hostname or parts.username or parts.password
                or any(ord(c) < 32 for c in value)
                or parts.port is not None and not 1 <= parts.port <= 65535):
            raise ValueError
        from agent.vault_store import normalize_origin
        return normalize_origin(value)
    except Exception:
        raise VaultRejected("login_origin_unavailable") from None


def _decoded(value):
    try:
        for _ in range(2):
            if type(value) is not str:
                break
            value = json.loads(value)
        return value
    except (ValueError, TypeError):
        raise VaultRejected("login_page_unavailable") from None


def _metadata(item):
    return {"id": item.id, "kind": "login", "label": item.label,
            "origin": item.origin, "created_at": item.created_at,
            "identifier_type": item.identifier_type, "identifier": item.identifier}


class VaultBridge:
    def __init__(self, profile_home: str | Path):
        self.profile_home = Path(profile_home).absolute()
        self.base = self.profile_home / "vault"

    def _private_paths(self):
        try:
            for path in (self.profile_home, self.base):
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    if path == self.base:
                        continue
                    raise
                if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_mode & 0o077):
                    raise ValueError
            for name in ("vault.key", "vault.json.enc"):
                try:
                    info = (self.base / name).lstat()
                except FileNotFoundError:
                    continue
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or stat.S_IMODE(info.st_mode) != 0o600):
                    raise ValueError
        except Exception:
            raise VaultRejected("login_store_unavailable") from None

    def _store(self):
        try:
            from hermes_constants import get_hermes_home
            from agent.vault_store import VaultStore
            if Path(get_hermes_home()).absolute() != self.profile_home:
                raise ValueError
        except Exception:
            raise VaultRejected("login_profile_unavailable") from None
        self._private_paths()
        return VaultStore(self.base)

    def _store_call(self, store, method, *args, **kwargs):
        try:
            result = getattr(store, method)(*args, **kwargs)
        except Exception:
            raise VaultRejected("login_store_unavailable") from None
        self._private_paths()
        return result

    def save_login(self, access: BrowserAccess, *, label, identifier_type, identifier, password):
        label, identifier = _text(label).strip(), _text(identifier).strip()
        password = _text(password)
        if (not label or not identifier or type(identifier_type) is not str
                or identifier_type not in {"email", "phone", "username"}):
            raise VaultRejected("login_arguments_invalid")
        origin = _origin(access)
        store = self._store()
        from agent.redact import register_vault_redaction_value
        # This also covers human-entered values after handback; the registry is
        # native, profile-scoped and memory-only, not a credential isolation layer.
        register_vault_redaction_value(password)
        item = self._store_call(store, "add_item", "login", label,
                                {"identifier_type": identifier_type, "identifier": identifier,
                                 "password": password}, origin=origin)
        return {"success": True, "item": _metadata(item)}

    def list_logins(self, access: BrowserAccess):
        # The runtime has already reserved the owner's browser/profile. Reading
        # metadata does not depend on a web origin, including on about:blank.
        store = self._store()
        items = self._store_call(store, "list_items")
        return {"success": True, "items": [_metadata(item) for item in items
                                            if item.kind == "login" and _valid_local_id(item.id)]}

    def remove_login(self, access: BrowserAccess, *, handle):
        _handle(handle)
        store = self._store()
        item = self._store_call(store, "get_meta", handle)
        if item is None or item.kind != "login":
            raise VaultRejected("login_not_found")
        return {"success": True, "removed": self._store_call(store, "remove_item", handle)}

    def fill_login(self, access: BrowserAccess, *, handle):
        _handle(handle)
        origin = _origin(access)
        store = self._store()
        item = self._store_call(store, "get_meta", handle)
        if item is None or item.kind != "login":
            raise VaultRejected("login_not_found")
        if item.origin != origin:
            raise VaultRejected("login_origin_mismatch")
        from agent.vault_login_classifier import (LoginControl, build_fill_js, build_inspection_js,
                                                  classify_login_control, select_password_fill)
        nonce = secrets.token_hex(8)
        raw = _decoded(access.evaluate(build_inspection_js(nonce), secret=False))
        if type(raw) is not list:
            raise VaultRejected("login_page_unavailable")
        try:
            classified = [control for entry in raw if type(entry) is dict
                          if (control := classify_login_control(LoginControl.from_dict(entry))) is not None]
        except Exception:
            raise VaultRejected("login_page_unavailable") from None
        if not select_password_fill(classified, "inspection-only"):
            raise VaultRejected("login_field_unavailable")
        secret = self._store_call(store, "resolve_secret", handle)
        password = secret.get("password") if type(secret) is dict else None
        if type(password) is not str or not password:
            raise VaultRejected("login_store_unavailable")
        fills = select_password_fill(classified, password)
        if not fills:
            raise VaultRejected("login_field_unavailable")
        from agent.redact import register_vault_redaction_value
        register_vault_redaction_value(password)
        # Native script reasserts the exact origin synchronously before writing.
        # Only the trusted reserved channel receives this secret-bearing string.
        result = _decoded(access.evaluate(build_fill_js(fills, expected_origin=origin, nonce=nonce), secret=True))
        if type(result) is not dict:
            raise VaultRejected("login_page_unavailable")
        if result.get("refused") == "origin_changed":
            raise VaultRejected("login_origin_changed")
        filled = result.get("filled")
        if type(filled) is not int or filled not in (0, 1):
            raise VaultRejected("login_page_unavailable")
        return {"success": bool(filled), "filled_fields": filled, "kind": "login", "origin": origin}


def _valid_local_id(value):
    return type(value) is str and re.fullmatch(r"vault_[a-f0-9]{12}", value) is not None
