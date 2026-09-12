"""The work home is a scoped server-owned view, not a UI permission guess."""
from dataclasses import replace

import pytest

from tests.fakes import channel_actor

pytestmark = pytest.mark.postgres


def test_operator_home_lists_assigned_agents_and_only_owned_project_tasks(
    service, alice, envelope, start,
):
    shared = service.admit(
        alice,
        envelope(project_id="project-shared"),
        replace(start, project_id="project-shared"),
    )
    service.admit(alice, envelope(), start)

    home = service.work_home(
        alice, envelope=envelope(project_id="project-shared")
    )

    assert home.principal_id == "alice" and home.role == "operator"
    assert home.project_id == "project-shared"
    assert home.start.enabled and home.start.reason is None
    assert [(agent.display_name, agent.role_name) for agent in home.agents] == [
        ("Atlas", "Researcher"), ("Beacon", "Researcher"),
    ]
    assert [card.task.task_id for card in home.tasks] == [shared.task_id]
    assert home.tasks[0].cancel.enabled
    assert not home.tasks[0].review.enabled


def test_viewer_home_is_read_only_and_does_not_disclose_another_owners_tasks(
    service, alice, viewer, envelope, start,
):
    service.admit(
        alice,
        envelope(project_id="project-shared"),
        replace(start, project_id="project-shared"),
    )
    viewer = channel_actor(viewer, "radhouse")

    home = service.work_home(
        viewer,
        envelope=envelope(principal="viewer", project_id="project-shared"),
    )

    assert home.role == "viewer"
    assert not home.start.enabled and home.start.reason == "read_only_role"
    assert [agent.bot_id for agent in home.agents] == ["bot-alpha"]
    assert home.tasks == ()


def test_home_reflects_current_bot_grant_without_cached_ui_authority(
    service, store, alice, envelope,
):
    before = service.work_home(alice, envelope=envelope())
    assert {agent.bot_id for agent in before.agents} == {"bot-alpha", "bot-beta"}
    with store.transaction() as tx:
        tx._connection.execute(
            "DELETE FROM public.bot_grants WHERE principal_id='alice' AND bot_id='bot-alpha'"
        )

    after = service.work_home(alice, envelope=envelope())

    assert [agent.bot_id for agent in after.agents] == ["bot-beta"]


def test_completed_task_exposes_review_only_with_fresh_assurance(
    service, alice, envelope, start,
):
    task = service.admit(alice, envelope(), start)
    completed = service.run(task.task_id)

    home = service.work_home(alice, envelope=envelope())

    card = next(card for card in home.tasks if card.task.task_id == completed.task_id)
    assert not card.cancel.enabled and card.cancel.reason == "task_closed"
    assert card.review.enabled and card.review.reason is None
