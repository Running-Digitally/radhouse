import json

import pytest

from radhouse.application.project_coordination import (
    accept_preview,
    apply_result,
    coordination_prompt,
    parse_coordination_plan,
    result_update,
    status_text,
)
from radhouse.domain.projects import ProjectCoordination
from radhouse.domain.tasks import Rejected


def report(**values):
    return "Useful human result.\n\nRADHOUSE_PROJECT_UPDATE: " + json.dumps(
        values, separators=(",", ":"), sort_keys=True
    )


def test_current_preview_can_be_reviewed_without_owner_acceptance():
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
    reviewed = apply_result(
        state.evolve(active_bot_id="reviewer", active_task_id="task-2"),
        "Reviewer",
        report(reviewed_revision=revision, reviewer_verdict="READY"),
    )
    assert reviewed.phase == "merge_ready"
    assert reviewed.reviewer_verdict == "READY"
    assert reviewed.accepted_preview_revision is None


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


def test_llm_coordination_plan_is_strict_bounded_data():
    prompt = coordination_prompt(
        "Compare the options and then improve the importer.",
        phase="intake",
        available_roles=("researcher", "builder"),
        attachments=(("groups.csv", "text/csv"),),
    )
    assert "use no tools" not in prompt.lower()
    assert "groups.csv (text/csv)" in prompt
    result = (
        'RADHOUSE_COORDINATION_PLAN: {"route":"research_then_build",'
        '"summary":"Research the format, then implement the smallest importer change.",'
        '"clarification":null}'
    )
    plan = parse_coordination_plan(
        result,
        allowed_routes=frozenset({"research", "build", "research_then_build", "clarify"}),
    )
    assert plan.route == "research_then_build"
    assert plan.clarification is None


@pytest.mark.parametrize(
    "result",
    [
        "Some prose first.\nRADHOUSE_COORDINATION_PLAN: {}",
        'RADHOUSE_COORDINATION_PLAN: {"route":"deploy","summary":"Do it",'
        '"clarification":null}',
        'RADHOUSE_COORDINATION_PLAN: {"route":"clarify","summary":"Unsure",'
        '"clarification":null}',
        'RADHOUSE_COORDINATION_PLAN: {"route":"build","summary":"Do it",'
        '"clarification":"May I deploy?"}',
        'RADHOUSE_COORDINATION_PLAN: {"route":"build","summary":"Do\\u0000it",'
        '"clarification":null}',
    ],
)
def test_invalid_or_authority_expanding_llm_coordination_plan_is_rejected(result):
    with pytest.raises(Rejected, match="coordination_plan_invalid"):
        parse_coordination_plan(
            result,
            allowed_routes=frozenset({"research", "build", "research_then_build", "clarify"}),
        )


def test_pull_status_renders_sanitized_runtime_activity_without_raw_trace():
    state = ProjectCoordination(
        "expenses", phase="building", active_bot_id="builder", active_task_id="task-1"
    )
    task = type("TaskStatus", (), {"permission_request": None, "blockers": ()})()
    text = status_text(
        state,
        "Builder",
        task=task,
        activity={"label": "Using an assigned tool", "occurred_at": 100},
        now=225,
    )
    assert "Builder · Working" in text
    assert "Current step: Using an assigned tool" in text
    assert "Last activity: 2 minutes ago" in text
    assert "Needs you: nothing" in text
