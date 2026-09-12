"""Channel metadata accompanies a command but never supplies its authority."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Envelope:
    channel: str
    event_id: str
    conversation_id: str
    binding_revision: int
    command_key: str
    mirrored: bool = False
