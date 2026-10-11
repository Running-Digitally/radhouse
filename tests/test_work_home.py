"""The work home is a scoped server-owned view, not a UI permission guess."""
from dataclasses import asdict, replace

import pytest

from tests.fakes import channel_actor
from radhouse.domain.tasks import Rejected

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
    assert home.project_name == "Shared research"
    assert home.start.enabled and home.start.reason is None
    assert [(agent.display_name, agent.role_name) for agent in home.agents] == [
        ("Atlas", "Researcher"), ("Beacon", "Researcher"),
    ]
    assert [card.task.task_id for card in home.tasks] == [shared.task_id]
    assert home.tasks[0].cancel.enabled
    assert not home.tasks[0].review.enabled


def test_project_work_is_newest_first_by_durable_admission_order(
    service, alice, envelope, start,
):
    first = service.admit(alice, envelope(), start)
    second = service.admit(alice, envelope(), replace(start, brief="A later assignment"))

    home = service.work_home(alice, envelope=envelope())

    assert [card.task.task_id for card in home.tasks] == [second.task_id, first.task_id]
    assert home.tasks[0].sequence > home.tasks[1].sequence


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
    assert next(project for project in service.projects(viewer)
                if project.project_id == "project-shared").bot_ids == ("bot-alpha",)
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


def test_home_reflects_project_agent_assignment_without_cross_project_leak(
    service, store, alice, envelope,
):
    with store.transaction() as tx:
        tx._connection.execute(
            "DELETE FROM public.project_bots "
            "WHERE project_id='project-shared' AND bot_id='bot-beta'"
        )

    shared = service.work_home(
        alice, envelope=envelope(project_id="project-shared"),
    )
    personal = service.work_home(alice, envelope=envelope())

    assert [agent.bot_id for agent in shared.agents] == ["bot-alpha"]
    assert {agent.bot_id for agent in personal.agents} == {"bot-alpha", "bot-beta"}


def test_completed_task_exposes_review_without_reauthentication(
    service, alice, envelope, start,
):
    task = service.admit(alice, envelope(), start)
    completed = service.run(task.task_id)

    home = service.work_home(replace(alice, assurance_until=None), envelope=envelope())

    card = next(card for card in home.tasks if card.task.task_id == completed.task_id)
    assert not card.cancel.enabled and card.cancel.reason == "task_closed"
    assert card.review.enabled and card.review.reason is None


@pytest.mark.parametrize("revocation", ["bot", "project_bot", "membership", "account"])
def test_shared_results_are_discoverable_without_private_task_data_and_recheck_access(
    service, store, alice, viewer, envelope, start, revocation,
):
    scope = envelope(project_id="project-shared")
    task = service.run(service.admit(alice, scope, replace(start,
        project_id="project-shared", brief="Private source instructions")).task_id)
    recipient_scope = envelope(principal="viewer", project_id="project-shared")
    assert service.work_home(viewer, envelope=recipient_scope).shared_results == ()
    review = service.prepare_review(alice, task.task_id, task.state_revision,
                                   ("alice", "viewer"), envelope=scope)
    publication = service.publish(alice, envelope(project_id="project-shared"), review.review_id,
                                  review.revision, task.result, review.audience)
    home = service.work_home(viewer, envelope=recipient_scope)
    assert home.tasks == ()
    assert [asdict(item) for item in home.shared_results] == [{
        "publication_id": publication.publication_id, "owner_id": "alice",
        "content": task.result, "digest": task.result_digest,
    }]
    assert service.work_home(alice, envelope=scope).shared_results == ()
    with store.transaction() as tx:
        sql = {
            "bot": "DELETE FROM bot_grants WHERE principal_id='viewer'",
            "project_bot": "DELETE FROM project_bots WHERE project_id='project-shared' AND bot_id='bot-alpha'",
            "membership": "DELETE FROM project_members WHERE principal_id='viewer'",
            "account": "UPDATE actors SET active=false WHERE principal_id='viewer'",
        }[revocation]
        tx._connection.execute(sql)
    if revocation in {"membership", "account"}:
        with pytest.raises(Rejected):
            service.work_home(viewer, envelope=recipient_scope)
    else:
        assert service.work_home(viewer, envelope=recipient_scope).shared_results == ()
