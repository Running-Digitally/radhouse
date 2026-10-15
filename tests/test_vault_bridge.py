"""Adapter authority/data-flow contracts; real native crypto/browser proof is separate."""
from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("radhouse_vault_bridge",
    Path(__file__).resolve().parents[1] / "runtime/hermes/vault_bridge.py")
vault = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = vault
spec.loader.exec_module(vault)

MARKER = "disposable-vault-marker-7C3F"
HANDLE = "vault_123456abcdef"


@dataclass
class Meta:
    id: str = HANDLE
    kind: str = "login"
    label: str = "Example login"
    origin: str = "https://example.invalid"
    created_at: str = "2026-10-08T00:00:00Z"
    identifier_type: str = "email"
    identifier: str = "owner@example.invalid"


class Access:
    def __init__(self, origin="https://example.invalid", responses=None):
        self.origin = origin
        self.calls = []
        self.responses = list(responses or [[{"index": 2, "password": True}], {"filled": 1}])

    def current_origin(self):
        return self.origin

    def evaluate(self, expression, *, secret=False):
        self.calls.append((expression, secret))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir(mode=0o700)
    state = SimpleNamespace(profile=profile, items={HANDLE: Meta()}, passwords={HANDLE: MARKER},
                            registered=[], resolved=[], removed=[], adds=[], error=None)

    class Store:
        def __init__(self, base):
            assert base == profile / "vault"

        def add_item(self, kind, label, secret, *, origin):
            if state.error:
                raise state.error
            state.adds.append((kind, label, secret, origin))
            item = Meta(label=label, origin=origin, identifier_type=secret["identifier_type"],
                        identifier=secret["identifier"])
            state.items[HANDLE], state.passwords[HANDLE] = item, secret["password"]
            return item

        def list_items(self):
            if state.error:
                raise state.error
            return list(state.items.values())

        def get_meta(self, handle):
            return state.items.get(handle)

        def resolve_secret(self, handle):
            if state.error:
                raise state.error
            state.resolved.append(handle)
            return {"password": state.passwords[handle]}

        def remove_item(self, handle):
            state.removed.append(handle)
            return state.items.pop(handle, None) is not None

    store_module = ModuleType("agent.vault_store")
    store_module.VaultStore = Store
    store_module.normalize_origin = lambda value: value.lower().replace(":443", "").split("/", 3)[0] + "//" + value.lower().replace(":443", "").split("/", 3)[2]
    constants = ModuleType("hermes_constants")
    constants.get_hermes_home = lambda: state.profile
    redactor = ModuleType("agent.redact")
    redactor.register_vault_redaction_value = state.registered.append
    classifier = ModuleType("agent.vault_login_classifier")
    classifier.LoginControl = SimpleNamespace(from_dict=lambda entry: entry)
    classifier.classify_login_control = lambda entry: entry if entry.get("password") else None
    classifier.select_password_fill = lambda entries, password: [{"index": entries[0]["index"], "token": "current-password", "value": password}] if entries else []
    classifier.build_inspection_js = lambda nonce: json.dumps({"inspection": nonce})
    classifier.build_fill_js = lambda fills, expected_origin, nonce: json.dumps({"fills": fills, "origin": expected_origin, "nonce": nonce})
    package = ModuleType("agent")
    package.__path__ = []
    for name, module in (("agent", package), ("agent.vault_store", store_module),
                         ("hermes_constants", constants), ("agent.redact", redactor),
                         ("agent.vault_login_classifier", classifier)):
        monkeypatch.setitem(sys.modules, name, module)
    return vault.VaultBridge(profile), state


def save(bridge, access=None, **changes):
    arguments = {"label": "Example login", "identifier_type": "email",
                 "identifier": "owner@example.invalid", "password": MARKER, **changes}
    return bridge.save_login(access or Access(), **arguments)


def test_explicit_save_uses_only_owned_origin_and_native_login_store(fixture):
    bridge, state = fixture
    result = save(bridge, Access("https://EXAMPLE.invalid:443/login"))
    assert result["item"]["origin"] == "https://example.invalid"
    assert state.adds == [("login", "Example login", {"identifier_type": "email",
                          "identifier": "owner@example.invalid", "password": MARKER},
                         "https://example.invalid")]
    assert state.registered == [MARKER]
    assert MARKER not in json.dumps(result)
    assert "password" not in result["item"]


@pytest.mark.parametrize("changes", [{"password": ""}, {"password": None}, {"password": 7},
                                      {"identifier_type": []}, {"identifier_type": "totp"},
                                      {"identifier": "  "}, {"label": "  "}, {"label": "\x00"}])
def test_save_validation_is_fixed_and_never_writes(fixture, changes):
    bridge, state = fixture
    with pytest.raises(vault.VaultRejected, match="^login_arguments_invalid$"):
        save(bridge, **changes)
    assert not state.adds and not state.registered


@pytest.mark.parametrize("origin", ["about:blank", "file:///tmp/example", "https://user:pass@example.invalid",
                                     "https://example.invalid:0", "https://example.invalid\n", "not a URL"])
def test_save_refuses_nonweb_or_credential_bearing_browser_origins(fixture, origin):
    bridge, state = fixture
    with pytest.raises(vault.VaultRejected, match="^login_origin_unavailable$"):
        save(bridge, Access(origin))
    assert not state.adds


def test_list_and_remove_expose_only_local_login_metadata(fixture):
    bridge, state = fixture
    state.items.update({"vault_fedcba654321": Meta(id="vault_fedcba654321", kind="payment"),
                        "op:external": Meta(id="op:external")})
    result = bridge.list_logins(Access())
    assert [item["id"] for item in result["items"]] == [HANDLE]
    assert not state.resolved and MARKER not in json.dumps(result)
    assert bridge.remove_login(Access(), handle=HANDLE) == {"success": True, "removed": True}
    assert state.removed == [HANDLE]
    with pytest.raises(vault.VaultRejected, match="^login_not_found$"):
        bridge.remove_login(Access(), handle="vault_fedcba654321")
    with pytest.raises(vault.VaultRejected, match="^login_handle_invalid$"):
        bridge.remove_login(Access(), handle="op:external")


def test_metadata_management_on_blank_page_does_not_inspect_browser(fixture):
    bridge, state = fixture

    class BlankAccess(Access):
        def current_origin(self):
            raise AssertionError("metadata must not require an active web page")

    access = BlankAccess("about:blank")
    assert bridge.list_logins(access)["items"][0]["id"] == HANDLE
    assert bridge.remove_login(access, handle=HANDLE)["removed"] is True
    assert not access.calls and not state.resolved and not state.registered


def test_fill_registers_before_secret_evaluation_and_returns_only_counts(fixture):
    bridge, state = fixture
    access = Access()
    original_evaluate = access.evaluate

    def evaluate(expression, *, secret=False):
        if secret:
            assert state.registered == [MARKER]
        return original_evaluate(expression, secret=secret)

    access.evaluate = evaluate
    result = bridge.fill_login(access, handle=HANDLE)
    inspection, fill = access.calls
    assert inspection[1] is False and fill[1] is True
    assert MARKER not in inspection[0] and MARKER in fill[0]
    assert json.loads(fill[0])["origin"] == "https://example.invalid"
    assert json.loads(fill[0])["nonce"] == json.loads(inspection[0])["inspection"]
    assert result == {"success": True, "filled_fields": 1, "kind": "login", "origin": "https://example.invalid"}
    assert MARKER not in json.dumps(result)


@pytest.mark.parametrize("origin", ["https://sub.example.invalid", "http://example.invalid", "https://example.invalid:444"])
def test_fill_refuses_other_origin_before_inspection_or_secret_resolution(fixture, origin):
    bridge, state = fixture
    access = Access(origin)
    with pytest.raises(vault.VaultRejected, match="^login_origin_mismatch$"):
        bridge.fill_login(access, handle=HANDLE)
    assert not access.calls and not state.resolved and not state.registered


def test_fill_rechecks_native_navigation_race_without_echoing_found_url(fixture):
    bridge, state = fixture
    access = Access(responses=[[{"index": 2, "password": True}], {"refused": "origin_changed", "found": MARKER}])
    with pytest.raises(vault.VaultRejected, match="^login_origin_changed$") as error:
        bridge.fill_login(access, handle=HANDLE)
    assert MARKER not in str(error.value)


def test_no_password_field_does_not_decrypt(fixture):
    bridge, state = fixture
    with pytest.raises(vault.VaultRejected, match="^login_field_unavailable$"):
        bridge.fill_login(Access(responses=[[]]), handle=HANDLE)
    assert not state.resolved


def test_store_faults_never_echo_credentials_or_paths(fixture):
    bridge, state = fixture
    state.error = RuntimeError("password=" + MARKER + " /private/profile")
    with pytest.raises(vault.VaultRejected, match="^login_store_unavailable$") as error:
        save(bridge)
    assert MARKER not in str(error.value) and error.value.__suppress_context__


def test_uncertain_native_ack_propagates_to_controller_without_becoming_completed(fixture):
    bridge, state = fixture

    class PendingAck(TimeoutError):
        pass

    pending = PendingAck("native_ack_pending")
    with pytest.raises(PendingAck) as error:
        bridge.fill_login(Access(responses=[[{"index": 2, "password": True}], pending]), handle=HANDLE)
    assert error.value is pending and state.registered == [MARKER]


def test_wrong_active_profile_never_reads_store(fixture, tmp_path):
    bridge, state = fixture
    state.profile = tmp_path / "other-profile"
    with pytest.raises(vault.VaultRejected, match="^login_profile_unavailable$"):
        bridge.list_logins(Access())


@pytest.mark.parametrize("name,mode", [("vault.key", 0o644), ("vault.json.enc", 0o640)])
def test_private_native_key_and_ciphertext_are_required(fixture, name, mode):
    bridge, _ = fixture
    bridge.base.mkdir(mode=0o700)
    path = bridge.base / name
    path.write_text("synthetic")
    path.chmod(mode)
    with pytest.raises(vault.VaultRejected, match="^login_store_unavailable$"):
        bridge.list_logins(Access())


def test_symlink_key_is_refused(fixture, tmp_path):
    bridge, _ = fixture
    bridge.base.mkdir(mode=0o700)
    target = tmp_path / "target"
    target.write_text("synthetic")
    target.chmod(0o600)
    (bridge.base / "vault.key").symlink_to(target)
    with pytest.raises(vault.VaultRejected, match="^login_store_unavailable$"):
        bridge.list_logins(Access())
