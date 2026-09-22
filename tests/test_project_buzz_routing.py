"""Small, database-free checks for owner-facing project routing."""
from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace

from radhouse.channels.project_buzz import ProjectBuzzConversationCycle
from radhouse.domain.projects import ProjectCoordination


def test_review_request_routes_without_preview_acceptance():
    cycle = object.__new__(ProjectBuzzConversationCycle)
    cycle.link = SimpleNamespace(agent_pubkey="b" * 64, bot_id="coordinator")
    reviewer = SimpleNamespace(link=SimpleNamespace(agent_pubkey="c" * 64, bot_id="reviewer"))
    cycle.specialists = (reviewer,)
    state = ProjectCoordination("expenses", phase="preview_feedback")
    bots = {"coordinator": SimpleNamespace(display_name="Radhouse")}
    event = {"content": "@Radhouse review Expenses PR #3", "tags": [["mention", "b" * 64, "agent-address"]]}

    selected, response, _, _ = cycle._select(event, state, {"reviewer": reviewer}, bots)

    assert selected is reviewer
    assert response is None


def test_coordinator_mention_answers_status_even_while_builder_is_active():
    cycle = object.__new__(ProjectBuzzConversationCycle)
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
