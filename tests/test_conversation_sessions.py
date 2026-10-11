from dataclasses import asdict, replace
from hashlib import sha256

import pytest
from pydantic import ValidationError

from radhouse.api.schemas import StartTaskSchema, TaskResponse
from radhouse.domain.conversations import ConversationLink
from radhouse.domain.tasks import Task


@pytest.fixture
def link():
    return ConversationLink(
        "alice-researcher",
        "dm-alice",
        "personal-alice:alice:buzz",
        "alice",
        "alice@buzz",
        "agent-key",
        "bot-alpha",
        "personal-alice",
        1,
    )


def test_conversation_session_identity_survives_snapshot_round_trip(link):
    restored = ConversationLink(**asdict(link))

    assert restored.hermes_session_id == link.hermes_session_id
    original_identity = "\0".join((
        "radhouse-hermes-session-v1", link.link_id, link.principal_id,
        link.project_id, link.bot_id,
    ))
    assert link.hermes_session_id == "rh-" + sha256(original_identity.encode()).hexdigest()
    assert len(link.hermes_session_id) == 67
    assert link.hermes_session_id.startswith("rh-")
    assert link.hermes_session_id_for("fresh-boundary") != link.hermes_session_id
    assert link.hermes_session_id_for("fresh-boundary") == link.hermes_session_id_for("fresh-boundary")


@pytest.mark.parametrize(
    "change",
    [
        {"link_id": "different-conversation"},
        {"principal_id": "bob"},
        {"project_id": "project-shared"},
        {"bot_id": "bot-beta"},
    ],
)
def test_session_identity_isolated_by_conversation_owner_project_and_profile(link, change):
    assert replace(link, **change).hermes_session_id != link.hermes_session_id


def test_public_admission_cannot_choose_internal_hermes_session():
    with pytest.raises(ValidationError):
        StartTaskSchema.model_validate(
            {
                "bot_id": "bot-alpha",
                "project_id": "personal-alice",
                "brief": "A synthetic request",
                "provider_binding": "fake-local",
                "hermes_session_id": "rh-" + "a" * 64,
            }
        )


def test_public_task_response_does_not_expose_runtime_session_binding():
    task = Task(
        "task-01", "alice", "bot-alpha", "personal-alice", "A synthetic request",
        "fake-local", None, 3, hermes_session_id="rh-" + "a" * 64,
    )

    response = TaskResponse.model_validate(task)

    assert "hermes_session_id" not in response.model_dump()
