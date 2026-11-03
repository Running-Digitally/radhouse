import pytest

from radhouse.chat.commitment_routes import standing_authorizer
from tests.test_local_reauthentication import local_client, login  # noqa: F401

pytestmark = pytest.mark.postgres


def test_standing_grant_reads_binding_without_extending_sessions(local_client, store, clock):
    client, auth, totp, password = local_client
    assert login(client, password, totp.at(clock())).status_code == 200
    with store.transaction() as tx:
        connection = tx._connection
        binding = connection.execute("SELECT conversation_id,revision FROM channel_bindings WHERE principal_id='alice' AND channel='radhouse'").fetchone()
        before = connection.execute("SELECT * FROM local_sessions WHERE principal_id='alice'").fetchone()
    authorize = standing_authorizer(auth)
    clock.advance(minutes=30)
    args = ('alice', binding['conversation_id'], binding['revision'])
    assert authorize(*args) is True
    with store.transaction() as tx:
        after = tx._connection.execute("SELECT * FROM local_sessions WHERE principal_id='alice'").fetchone()
        assert after == before
        tx._connection.execute("UPDATE local_sessions SET revoked_at=now() WHERE principal_id='alice'")
    # The explicit standing grant survives sign-out; delivery still needs a
    # separately valid device session. Account/binding revocation stops review.
    assert authorize(*args) is True
    with store.transaction() as tx:
        tx._connection.execute("UPDATE channel_bindings SET revision=revision+1 WHERE principal_id='alice'")
    assert authorize(*args) is False
    with store.transaction() as tx:
        tx._connection.execute("UPDATE actors SET active=false WHERE principal_id='alice'")
    assert authorize('alice', binding['conversation_id'], binding['revision']+1) is False
