"""Persisted synthetic credentials survive the cryptography dependency update."""
from datetime import datetime, timezone

import pyotp
import pytest

from radhouse.auth.local import LocalAuthService, _fernet


# Public synthetic key/secret; ciphertext generated with cryptography 46.0.3.
# This is a fixed previous-version artifact, not a new-version round trip.
KEY = 'AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8='
SECRET = 'JBSWY3DPEHPK3PXP'
CIPHERTEXT = (
    b'gAAAAABlU_EAH5m1DIXK_0LBzQZl4g0zKkful7zoPyhRXml0EaY_nYXViYcQ5Qu_'
    b'YNeI0FiykO9Zs0obarGRoqqwiYNxmq185mmZK7nCNR1KFq17lRPFLN8='
)


@pytest.mark.parametrize('tampered', [False, True])
def test_previous_version_totp_ciphertext_retains_authentication_and_integrity(tampered):
    service = LocalAuthService.__new__(LocalAuthService)
    service._fernet = _fernet(KEY)
    ciphertext = bytearray(CIPHERTEXT)
    if tampered:
        ciphertext[40] = ord('A') if ciphertext[40] != ord('A') else ord('B')
    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    credential = {'totp_secret_ciphertext': ciphertext, 'last_totp_counter': None}
    counter = service._totp_counter(credential, pyotp.TOTP(SECRET).at(now), now)
    assert counter == (None if tampered else int(now.timestamp()) // 30)
