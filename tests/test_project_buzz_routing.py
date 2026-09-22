"""Small, database-free checks for owner-facing project routing."""
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
