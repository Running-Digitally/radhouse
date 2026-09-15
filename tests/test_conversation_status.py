from dataclasses import replace

import pytest

from radhouse.application.conversations import Conversations
from radhouse.application.service import Service
from radhouse.domain.tasks import ProviderDescription, Task


def task():
    return Task("task-1", "alice", "researcher", "personal", "Compare the options.", "local", None, 3)


def test_queued_provider_outage_explains_saved_work_and_automatic_recheck():
    original = task()
    blockers, model = Service._provider_state(
        original, ProviderDescription("local", "model", available=False)
    )
    waiting = replace(original, blockers=blockers, model_id=model)
    assert "waiting for the model provider" in Conversations.describe(waiting)
    assert "assignment is saved" in Conversations.describe(waiting)
    assert "check availability again automatically" in Conversations.describe(waiting)
    assert waiting.blockers == ("provider_unavailable",)
    assert waiting.attempt_id is None and waiting.budget_remaining == original.budget_remaining

    blockers, model = Service._provider_state(waiting, ProviderDescription("local", "model"))
    recovered = replace(waiting, blockers=blockers, model_id=model)
    assert Conversations.describe(recovered) == "Your assignment is queued."
    assert recovered.task_id == waiting.task_id and recovered.attempt_id is None


def test_progress_uses_the_assigned_agent_name():
    assert Conversations.describe(replace(task(), phase="active"), "Builder") == (
        "Builder is working on your assignment."
    )


@pytest.mark.parametrize("description,expected", [
    (ProviderDescription("other", "model"), "provider_mismatch"),
    (ProviderDescription("local", "model", compatible=False), "provider_incompatible"),
])
def test_provider_identity_and_compatibility_holds_still_need_attention(description, expected):
    original = task()
    blockers, model = Service._provider_state(original, description)
    held = replace(original, blockers=blockers, model_id=model)
    assert held.blockers == (expected,)
    assert "needs attention" in Conversations.describe(held)
    assert "automatically" not in Conversations.describe(held)


@pytest.mark.parametrize("other_hold", ["human_pause", "provider_mismatch", "provider_incompatible"])
def test_provider_outage_does_not_hide_another_hold(other_hold):
    held = replace(task(), blockers=tuple(sorted(("provider_unavailable", other_hold))))
    assert "needs attention" in Conversations.describe(held)
    assert "automatically" not in Conversations.describe(held)


@pytest.mark.parametrize("phase", ["active", "recovering", "stopping", "closed"])
def test_only_queued_outage_claims_an_automatic_availability_recheck(phase):
    held = replace(task(), phase=phase, blockers=("provider_unavailable",))
    assert "needs attention" in Conversations.describe(held)
    assert "automatically" not in Conversations.describe(held)
