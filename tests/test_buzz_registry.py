from coincurve import PrivateKey
import pytest

from radhouse.channels.buzz_registry import bind_key
from radhouse.domain.tasks import Rejected

pytestmark = pytest.mark.postgres


def test_binding_is_idempotent_and_rotation_revokes_old_key(store):
    one, two = (PrivateKey().public_key_xonly.format().hex() for _ in range(2))
    arguments = dict(principal_id="alice", conversation_id="one-buzz-room", project_id="personal-alice")
    assert bind_key(store, pubkey=one, **arguments) == 1
    assert bind_key(store, pubkey=one, **arguments) == 1
    assert bind_key(store, pubkey=two, **arguments) == 2
    with store.transaction() as tx:
        assert not tx.binding("buzz", one, "one-buzz-room").active
        assert tx.binding("buzz", two, "one-buzz-room").active
        assert tx.binding("buzz", two, "one-buzz-room").revision == 2
    with pytest.raises(Rejected, match="key_owned_by_another_person"):
        bind_key(store, pubkey=two, principal_id="bob", conversation_id="one-buzz-room", project_id="project-shared")


def test_binding_never_creates_project_access(store):
    with pytest.raises(Rejected, match="access_denied"):
        bind_key(store, pubkey=PrivateKey().public_key_xonly.format().hex(), principal_id="bob",
                 conversation_id="private-room", project_id="personal-alice")
