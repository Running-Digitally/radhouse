"""Display titles stay separate from task execution and protected review state."""
from dataclasses import replace

import pytest

from radhouse.application.service import Service
from radhouse.domain.tasks import (
    Rejected, agent_task_title, initial_task_title, normalize_task_title,
)
from tests.fakes import FakeAgentWork


def test_title_helpers_are_bounded_and_reuse_agent_headings():
    assert initial_task_title("New task: Compare two backup plans. Then recommend one.") == "Compare two backup plans."
    assert agent_task_title("Intro\n\n## Recovery plan **for owners**\nDetails") == "Recovery plan for owners"
    assert agent_task_title("No heading here") == "No heading here"
    assert agent_task_title("RADHOUSE_PROJECT_UPDATE: {}\nDone") is None
    assert len(normalize_task_title("word " * 40)) <= 100
    with pytest.raises(Rejected, match="invalid_task_title"):
        normalize_task_title(" \n ")


@pytest.mark.postgres
def test_agent_title_and_owner_edit_do_not_change_task_or_review_identity(
    store, service_factory, fake_provider, clock, tmp_path, alice, bob, envelope, start,
):
    work = FakeAgentWork(
        tmp_path / "title-runtime.sqlite3", clock=clock,
        result_content="# Practical recovery plan\n\nA useful result.",
    )
    service = service_factory(work=work)
    admitted = service.admit(alice, envelope(), replace(
        start, brief="New task: Compare the current recovery options and recommend one."
    ))
    with store.transaction() as tx:
        assert tx.task_title(admitted.task_id).title == "Compare the current recovery options and recommend one."

    completed = service.run(admitted.task_id)
    home = service.work_home(alice, envelope=envelope())
    card = next(item for item in home.tasks if item.task.task_id == completed.task_id)
    assert (card.title.title, card.title.source, card.title.revision) == (
        "Practical recovery plan", "agent", 2,
    )
    assert work.start_count == 1

    review = service.prepare_review(
        alice, completed.task_id, completed.state_revision, ("alice",), envelope=envelope(),
    )
    rename = envelope(command_key="rename-one")
    renamed = service.rename_task(
        alice, completed.task_id, card.title.revision, "My recovery decision",
        envelope=rename,
    )
    assert (renamed.title, renamed.source, renamed.revision) == (
        "My recovery decision", "owner", 3,
    )
    service.record_agent_title(completed.task_id, "A later agent suggestion")
    with store.transaction() as tx:
        assert tx.task_title(completed.task_id) == renamed
    assert service.rename_task(
        alice, completed.task_id, card.title.revision, "My recovery decision",
        envelope=rename,
    ) == renamed
    after = service.get(alice, completed.task_id, envelope=envelope())
    assert (after.state_revision, after.result_digest) == (
        completed.state_revision, completed.result_digest,
    )
    publication = service.publish(
        alice, envelope(), review.review_id, review.revision,
        completed.result, review.audience,
    )
    assert publication.digest == completed.result_digest

    with pytest.raises(Rejected, match="task_title_revision_conflict"):
        service.rename_task(
            alice, completed.task_id, card.title.revision, "Stale edit", envelope=envelope(),
        )
    with pytest.raises(Rejected):
        service.rename_task(
            bob, completed.task_id, renamed.revision, "Not Bob's title",
            envelope=envelope(principal="bob"),
        )
