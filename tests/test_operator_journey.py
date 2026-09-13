"""Operator read/action paths retain current grants and exact result identity."""
from dataclasses import replace

from fastapi.testclient import TestClient
import pytest

from radhouse.api.app import create_app
from radhouse.domain.tasks import Rejected

pytestmark = pytest.mark.postgres


def test_projects_excludes_inactive_and_revoked_memberships(service, store, alice):
    assert {p.project_id for p in service.projects(alice)} == {"personal-alice", "project-shared"}
    with store.transaction() as tx:
        tx._connection.execute("UPDATE projects SET state='archived' WHERE project_id='project-shared'")
    assert [p.project_id for p in service.projects(alice)] == ["personal-alice"]
    with store.transaction() as tx:
        tx._connection.execute("DELETE FROM project_members WHERE principal_id='alice'")
    assert service.projects(alice) == ()


def test_home_removes_private_task_after_bot_grant_revoked(service, store, alice, envelope, start):
    task = service.admit(alice, envelope(), start)
    service.run(task.task_id)
    with store.transaction() as tx:
        tx._connection.execute("DELETE FROM bot_grants WHERE principal_id='alice' AND bot_id=%s", (start.bot_id,))
    assert service.work_home(alice, envelope=envelope()).tasks == ()
    with pytest.raises(Rejected, match="access_denied"):
        service.review_audience(alice, task.task_id, envelope=envelope())


def test_no_start_when_assigned_agents_are_unavailable(service, store, alice, envelope):
    with store.transaction() as tx:
        tx._connection.execute("UPDATE bots SET state='maintenance'")
    home = service.work_home(alice, envelope=envelope())
    assert not home.start.enabled and home.start.reason == "agents_unavailable"


def test_audience_is_scoped_and_rechecked_on_publication(service, store, alice, envelope, start):
    channel = envelope(project_id="project-shared")
    task = service.admit(alice, channel, replace(start, project_id="project-shared"))
    task = service.run(task.task_id)
    audience = service.review_audience(alice, task.task_id, envelope=channel)
    assert "alice" in audience and "viewer" in audience
    review = service.prepare_review(alice, task.task_id, task.state_revision, ("alice", "viewer"), envelope=channel)
    with store.transaction() as tx:
        tx._connection.execute("DELETE FROM project_members WHERE principal_id='viewer' AND project_id='project-shared'")
    with pytest.raises(Rejected, match="access_denied"):
        service.publish(alice, envelope(project_id="project-shared"), review.review_id,
                        review.revision, task.result, review.audience)


def test_result_download_requires_current_owner_access_and_is_attachment(service, alice, bob, envelope, start):
    task = service.run(service.admit(alice, envelope(), start).task_id)
    actor = alice
    with TestClient(create_app(service, lambda _: actor)) as client:
        query = {"conversation_id": envelope().conversation_id, "binding_revision": 1}
        result = client.get(f"/tasks/{task.task_id}/result", params=query)
        assert result.status_code == 200 and result.text == task.result
        assert result.headers["content-type"].startswith("text/plain")
        assert result.headers["content-disposition"] == 'attachment; filename="radhouse-result.txt"'
        assert result.headers["cache-control"] == "no-store"
        actor = bob
        assert client.get(f"/tasks/{task.task_id}/result", params=query).status_code == 403
