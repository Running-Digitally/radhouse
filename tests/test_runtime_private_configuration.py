"""Portable private configuration retains certificate and target identity checks."""

from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import json
from pathlib import Path
import ssl
import sys
import threading
from urllib.error import URLError

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
import pytest


RUNTIME = Path(__file__).resolve().parents[1] / "runtime/hermes"
spec = importlib.util.spec_from_file_location("private_configuration_bridge", RUNTIME / "bridge.py")
bridge = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bridge
spec.loader.exec_module(bridge)


@pytest.mark.parametrize("name", ["controller.example.invalid", "192.0.2.10", "::1"])
def test_callback_identity_is_explicit_configuration(name, tmp_path, monkeypatch):
    ca = tmp_path / "ca.pem"
    ca.touch()
    monkeypatch.setattr(bridge.ssl, "create_default_context", lambda **kwargs: object())
    callback = bridge.Callback("https://127.0.0.1:18645", str(ca), name)
    assert callback.tls_server_name == name


@pytest.mark.parametrize("name", [None, "", "https://controller.example.invalid", "*.example.invalid",
    "controller.example.invalid/path", "controller\n.example.invalid", "controller..invalid", "-invalid", "a" * 64])
def test_callback_rejects_absent_or_ambiguous_tls_identity(name, tmp_path):
    ca = tmp_path / "ca.pem"
    ca.touch()
    with pytest.raises(ValueError, match="invalid_document_callback"):
        bridge.Callback("https://127.0.0.1:18645", str(ca), name)


def test_callback_checks_configured_certificate_identity_over_loopback(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "controller.example.invalid")])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("controller.example.invalid")]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
        .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=True,
            data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
            encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256()))
    ca, private_key = tmp_path / "ca.pem", tmp_path / "key.pem"
    ca.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    private_key.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private_key.chmod(0o600)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            raw = b'{"kind":"catalog","files":[],"complete":true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(ca, private_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            origin = f"https://127.0.0.1:{server.server_port}"
            run = bridge.DocumentRunContext("run", "session", "dispatch", "a" * 43)
            callback = bridge.Callback(origin, str(ca), "controller.example.invalid")
            assert callback.post("read", run, {})["kind"] == "catalog"
            wrong = bridge.Callback(origin, str(ca), "another.example.invalid")
            with pytest.raises(URLError) as error:
                wrong.post("read", run, {})
            assert isinstance(error.value.reason, ssl.SSLCertVerificationError)
        finally:
            server.shutdown()
            thread.join(timeout=2)


@pytest.mark.parametrize("drift", [None, "missing_pin", "target", "hold", "policy_digest"])
def test_maintenance_hold_uses_digest_bound_private_machine_pin(tmp_path, monkeypatch, drift):
    machine_id = "a" * 32
    policy = {"schema": "radhouse.builder-maintenance.v1", "machine_id": machine_id}
    if drift == "missing_pin":
        policy.pop("machine_id")
    raw_policy = json.dumps(policy).encode()
    policy_hash, runtime_hash = hashlib.sha256(raw_policy).hexdigest(), "b" * 64
    hold = {"schema": "radhouse.builder-maintenance-hold.v1", "action": "weekly-maintenance",
        "machine_id": "c" * 32 if drift == "hold" else machine_id, "cycle_id": "d" * 32,
        "policy_sha256": policy_hash, "runtime_sha256": runtime_hash,
        "boot_id": "synthetic-boot", "created_at": datetime.now(timezone.utc).isoformat()}
    raw_hold = json.dumps(hold).encode()
    monkeypatch.setattr(bridge, "_maintenance_configuration", (policy_hash, runtime_hash))
    monkeypatch.setattr(bridge, "_root_file", lambda path, maximum:
        raw_hold if path == bridge.HOLD_PATH else raw_policy + (b" " if drift == "policy_digest" else b""))
    read_text = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda path, *args, **kwargs:
        ("e" * 32 if drift == "target" else machine_id) if path == Path("/etc/machine-id")
        else read_text(path, *args, **kwargs))
    if drift:
        with pytest.raises(ValueError, match="maintenance_hold_unverified"):
            bridge._hold()
        assert bridge.maintenance_held() is True
    else:
        value, digest = bridge._hold()
        assert value == hold
        assert digest == hashlib.sha256(raw_hold).hexdigest()
