import json

import pytest

from radhouse.application.project_coordination import (
    accept_preview,
    apply_result,
    result_update,
    status_text,
)
from radhouse.domain.projects import ProjectCoordination
from radhouse.domain.tasks import Rejected


def report(**values):
    return "Useful human result.\n\nRADHOUSE_PROJECT_UPDATE: " + json.dumps(
        values, separators=(",", ":"), sort_keys=True
    )


def test_builder_preview_owner_acceptance_and_exact_reviewer_revision():
    revision = "a" * 40
    state = apply_result(
        ProjectCoordination(
            "expenses", active_bot_id="builder", active_task_id="task-1"
        ),
        "Builder",
        report(
            repository="Satish-s-RADHouse/Expenses",
            source_revision=revision,
            preview_revision=revision,
            preview_digest="b" * 64,
            preview_url="https://builder-preview.runningdigitally.com/",
            pull_request="https://github.com/Satish-s-RADHouse/Expenses/pull/3",
        ),
    )

    assert state.phase == "preview_feedback"
    assert state.active_task_id is None
    accepted = accept_preview(state)
    assert accepted.accepted_preview_revision == revision

    reviewed = apply_result(
        accepted.evolve(active_bot_id="reviewer", active_task_id="task-2"),
        "Reviewer",
        report(reviewed_revision=revision, reviewer_verdict="READY"),
    )
    assert reviewed.phase == "merge_ready"
    assert reviewed.reviewer_verdict == "READY"


def test_review_and_deployment_evidence_fail_closed_on_revision_drift():
    accepted = ProjectCoordination(
        "expenses",
        phase="review",
        source_revision="a" * 40,
        preview_revision="a" * 40,
        accepted_preview_revision="a" * 40,
        active_bot_id="reviewer",
        active_task_id="review",
    )
    reviewed = apply_result(
        accepted,
        "Reviewer",
        report(reviewed_revision="c" * 40, reviewer_verdict="READY"),
    )
    assert reviewed.phase == "correction"
    assert reviewed.reviewer_verdict is None

    deployed = apply_result(
        ProjectCoordination(
            "expenses", phase="deployment", merged_revision="d" * 40,
            active_bot_id="deployer", active_task_id="deploy",
        ),
        "Deployer",
        report(
            deployed_revision="e" * 40,
            deployment_url="https://expenses.deployed.runningdigitally.com/",
            deployment_status="healthy",
        ),
    )
    assert deployed.phase == "blocked"
    assert deployed.deployed_revision is None


def test_deployer_may_report_the_owner_approved_merge_and_deployment_together():
    source = "a" * 40
    merged = "d" * 40
    state = ProjectCoordination(
        "expenses", phase="deployment", source_revision=source,
        preview_revision=source, accepted_preview_revision=source,
        reviewed_revision=source, reviewer_verdict="READY",
        active_bot_id="deployer", active_task_id="deploy",
    )
    deployed = apply_result(
        state,
        "Deployer",
        report(
            merged_revision=merged,
            deployed_revision=merged,
            deployment_url="https://expenses.deployed.runningdigitally.com/",
            deployment_status="healthy",
        ),
    )
    assert deployed.phase == "deployed"
    assert deployed.merged_revision == deployed.deployed_revision == merged


def test_invalid_machine_report_does_not_replace_the_human_result():
    assert result_update("RADHOUSE_PROJECT_UPDATE: not-json") == {}
    assert result_update(report(preview_url="http://public.example")) == {}
    with pytest.raises(Rejected, match="project_preview_not_current"):
        accept_preview(ProjectCoordination("expenses"))

    text = status_text(ProjectCoordination(
        "expenses", phase="preview_feedback",
        preview_url="https://preview.example/", preview_revision="abc1234",
    ))
    assert "preview feedback" in text and "abc1234" in text
