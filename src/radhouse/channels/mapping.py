"""Pure, fail-closed verification against a transaction's current binding."""
from radhouse.channels.commands import Envelope
from radhouse.domain.access import AuthContext, Binding
from radhouse.domain.tasks import Rejected


def verify_envelope(
    actor: AuthContext,
    envelope: Envelope,
    binding: Binding | None,
    project_id: str,
) -> None:
    """Call before deduplication or command effects using a fresh binding.

    Transport authentication supplies ``actor``; the payload cannot establish
    the author. Mirrored deliveries are never ingress commands, even if their
    original command was valid and its receipt is already retained.
    """
    if envelope.mirrored:
        raise Rejected("mirrored_event", 409)
    if (
        binding is None
        or not binding.active
        or actor.channel != envelope.channel
        or binding.channel != actor.channel
        or binding.subject != actor.subject
        or binding.principal_id != actor.principal_id
        or binding.conversation_id != envelope.conversation_id
        or binding.project_id != project_id
        or binding.revision != envelope.binding_revision
    ):
        raise Rejected("binding_denied", 403)
