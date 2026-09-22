"""Small, database-free checks for owner-facing project routing."""
from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from radhouse.channels.project_buzz import ProjectBuzzConversationCycle
from radhouse.domain.projects import ProjectCoordination


def test_review_request_routes_without_preview_acceptance():
    cycle = object.__new__(ProjectBuzzConversationCycle)
    cycle.coordinator = SimpleNamespace(candidate=SimpleNamespace(display_name="Radhouse"))
    cycle.link = SimpleNamespace(agent_pubkey="b" * 64, bot_id="coordinator")
    reviewer = SimpleNamespace(link=SimpleNamespace(agent_pubkey="c" * 64, bot_id="reviewer"))
    cycle.specialists = (reviewer,)
    state = ProjectCoordination("expenses", phase="preview_feedback")
    bots = {"coordinator": SimpleNamespace(display_name="Radhouse")}
    event = {"content": "@Radhouse review Expenses PR #3", "tags": [["mention", "b" * 64, "agent-address"]]}

    selected, response, _, _ = cycle._select(event, state, {"reviewer": reviewer}, bots)

    assert selected is reviewer
    assert response is None


@pytest.mark.parametrize("extra_mention", ["c" * 64, "e" * 64])
def test_owner_can_ask_radhouse_to_send_current_work_to_reviewer(extra_mention):
    cycle = object.__new__(ProjectBuzzConversationCycle)
    cycle.coordinator = SimpleNamespace(candidate=SimpleNamespace(display_name="Radhouse"))
    cycle.link = SimpleNamespace(agent_pubkey="b" * 64, bot_id="coordinator")
    reviewer = SimpleNamespace(link=SimpleNamespace(agent_pubkey="c" * 64, bot_id="reviewer"))
    builder = SimpleNamespace(link=SimpleNamespace(agent_pubkey="d" * 64, bot_id="builder"))
    cycle.specialists = (builder, reviewer)
    state = ProjectCoordination("expenses", phase="preview_feedback")
    bots = {
        "coordinator": SimpleNamespace(display_name="Radhouse"),
        "reviewer": SimpleNamespace(display_name="Reviewer"),
        "builder": SimpleNamespace(display_name="Builder"),
    }
    event = {
        "content": "@Radhouse Can you send the work to Reviewer",
        "tags": [
            ["mention", "b" * 64, "agent-address"],
            ["mention", extra_mention, "agent-address"],
        ],
    }

    selected, response, _, _ = cycle._select(
        event, state, {"reviewer": reviewer, "builder": builder}, bots,
    )

    assert selected is reviewer
    assert response is None


def test_coordinator_request_with_two_visible_agent_addresses_remains_ambiguous():
    cycle = object.__new__(ProjectBuzzConversationCycle)
    cycle.coordinator = SimpleNamespace(candidate=SimpleNamespace(display_name="Radhouse"))
    cycle.link = SimpleNamespace(agent_pubkey="b" * 64, bot_id="coordinator")
    reviewer = SimpleNamespace(link=SimpleNamespace(agent_pubkey="c" * 64, bot_id="reviewer"))
    builder = SimpleNamespace(link=SimpleNamespace(agent_pubkey="d" * 64, bot_id="builder"))
    cycle.specialists = (builder, reviewer)
    bots = {
        "coordinator": SimpleNamespace(display_name="Radhouse"),
        "reviewer": SimpleNamespace(display_name="Reviewer"),
        "builder": SimpleNamespace(display_name="Builder"),
    }
    event = {
        "content": "@Radhouse ask @Builder and @Reviewer to handle this",
        "tags": [["mention", "b" * 64, "agent-address"]],
    }

    selected, response, _, _ = cycle._select(
        event, ProjectCoordination("expenses"),
        {"reviewer": reviewer, "builder": builder}, bots,
    )

    assert selected is None
    assert response == "Mention exactly one assigned project agent."


def test_coordinator_mention_answers_status_even_while_builder_is_active():
    cycle = object.__new__(ProjectBuzzConversationCycle)
    cycle.coordinator = SimpleNamespace(candidate=SimpleNamespace(display_name="Radhouse"))
    cycle.link = SimpleNamespace(agent_pubkey="b" * 64, bot_id="coordinator")
    builder = SimpleNamespace(link=SimpleNamespace(agent_pubkey="c" * 64, bot_id="builder"))
    cycle.specialists = (builder,)
    cycle.store = SimpleNamespace(transaction=lambda: nullcontext(SimpleNamespace()))
    cycle.service = SimpleNamespace(_now=lambda: datetime.now(timezone.utc))
    state = ProjectCoordination("expenses", phase="building", active_bot_id="builder")
    bots = {
        "coordinator": SimpleNamespace(display_name="Radhouse"),
        "builder": SimpleNamespace(display_name="Builder"),
    }
    event = {"content": "@Radhouse status", "tags": [["mention", "b" * 64, "agent-address"]]}

    selected, response, _, _ = cycle._select(event, state, {"builder": builder}, bots)

    assert selected is builder
    assert "Project status · building" in response
    assert cycle._coordinator_content({"content": "@Radhouse pause this work"}, bots) == "pause this work"


@pytest.mark.parametrize("signed_mention", [False, True])
def test_coordinator_deployment_request_overrides_reviewer_reply_ancestry(signed_mention):
    cycle = object.__new__(ProjectBuzzConversationCycle)
    cycle.coordinator = SimpleNamespace(candidate=SimpleNamespace(display_name="Radhouse"))
    cycle.link = SimpleNamespace(agent_pubkey="b" * 64, bot_id="researcher", channel_id="expenses")
    reviewer = SimpleNamespace(link=SimpleNamespace(
        agent_pubkey="c" * 64, bot_id="reviewer", link_id="reviewer-link",
    ))
    deployer = SimpleNamespace(link=SimpleNamespace(agent_pubkey="d" * 64, bot_id="deployer"))
    cycle.specialists = (reviewer, deployer)
    cycle.store = SimpleNamespace(transaction=lambda: nullcontext(SimpleNamespace(
        conversation_reply_in_channel=lambda *_: {
            "message": SimpleNamespace(link_id="reviewer-link"),
        },
    )))
    bots = {
        "researcher": SimpleNamespace(display_name="Researcher"),
        "reviewer": SimpleNamespace(display_name="Reviewer"),
        "deployer": SimpleNamespace(display_name="Deployer"),
    }
    revision = "a" * 40
    state = ProjectCoordination(
        "expenses", phase="merge_ready", source_revision=revision,
        preview_revision=revision, reviewed_revision=revision,
        reviewer_verdict="READY",
    )
    tags = [["h", "expenses"], ["e", "f" * 64, "", "reply"]]
    if signed_mention:
        tags.append(["mention", "b" * 64, "agent-address"])
    event = {
        "content": "@Radhouse can you now send it for deployment?",
        "tags": tags,
    }

    selected, response, _, _ = cycle._select(
        event, state, {"deployer": deployer}, bots,
    )

    assert selected is deployer
    assert response is None
