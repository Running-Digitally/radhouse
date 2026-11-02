import hashlib

import pytest

from tests.test_local_reauthentication import local_client


pytestmark = pytest.mark.postgres


def test_notification_check_does_not_extend_session(local_client, store, clock):
    _, auth, totp, password = local_client
    session = auth.login("alice", password, totp.at(clock()), "synthetic-source")
    digest = hashlib.sha256(session.token.encode()).hexdigest()
    with store.transaction() as tx:
        before = dict(tx._connection.execute("SELECT * FROM local_sessions WHERE token_hash=%s", (digest,)).fetchone())
    clock.advance(minutes=10)
    assert auth.notification_session_active(digest, session.principal_id, session.conversation_id, session.binding_revision)
    with store.transaction() as tx:
        after = dict(tx._connection.execute("SELECT * FROM local_sessions WHERE token_hash=%s", (digest,)).fetchone())
    assert before == after
    clock.advance(minutes=21)
    assert not auth.notification_session_active(digest, session.principal_id, session.conversation_id, session.binding_revision)


@pytest.mark.parametrize("change", ["revoked", "inactive", "binding", "foreign", "malformed"])
def test_notification_check_rejects_stale_authority(local_client, store, clock, change):
    _, auth, totp, password = local_client
    session = auth.login("alice", password, totp.at(clock()), "synthetic-source")
    digest = hashlib.sha256(session.token.encode()).hexdigest()
    owner = session.principal_id
    with store.transaction() as tx:
        if change == "revoked":
            tx._connection.execute("UPDATE local_sessions SET revoked_at=now() WHERE token_hash=%s", (digest,))
        elif change == "inactive":
            tx._connection.execute("UPDATE actors SET active=false WHERE principal_id=%s", (owner,))
        elif change == "binding":
            tx._connection.execute("UPDATE channel_bindings SET revision=revision+1 WHERE principal_id=%s", (owner,))
    if change == "foreign":
        owner = "foreign-owner"
    if change == "malformed":
        digest = "raw-session-value"
    assert not auth.notification_session_active(digest, owner, session.conversation_id, session.binding_revision)
