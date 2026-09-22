"""Small deterministic project state machine used by Buzz coordination."""

from dataclasses import replace
import json
import re
from urllib.parse import urlsplit

from radhouse.domain.projects import ProjectCoordination
from radhouse.domain.tasks import Rejected


_UPDATE = re.compile(r"(?m)^RADHOUSE_PROJECT_UPDATE:\s*(\{[^\r\n]+\})\s*$")
_REVISION = re.compile(r"^[0-9a-f]{7,64}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _https(value):
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
    )


def result_update(result: str | None) -> dict[str, str]:
    """Read one bounded machine report while keeping prose as the user result."""
    if not result or (match := _UPDATE.search(result)) is None:
        return {}
    try:
        value = json.loads(match.group(1))
    except (ValueError, TypeError):
        return {}
    allowed = {
        "repository", "branch", "pull_request", "source_revision",
        "preview_url", "preview_revision", "preview_digest",
        "reviewed_revision", "reviewer_verdict", "merged_revision",
        "deployment_url", "deployed_revision", "deployment_status",
    }
    if (
        not isinstance(value, dict)
        or not value
        or not set(value) <= allowed
        or any(not isinstance(item, str) or not item or len(item) > 512
               for item in value.values())
        or any(key in value and not _REVISION.fullmatch(value[key]) for key in (
            "source_revision", "preview_revision", "reviewed_revision",
            "merged_revision", "deployed_revision",
        ))
        or "preview_digest" in value and not _DIGEST.fullmatch(value["preview_digest"])
        or any(key in value and not _https(value[key]) for key in (
            "pull_request", "preview_url", "deployment_url",
        ))
        or "reviewer_verdict" in value
        and value["reviewer_verdict"] not in {"READY", "CHANGES_NEEDED"}
        or "deployment_status" in value
        and value["deployment_status"] not in {"healthy", "rolled_back", "failed"}
    ):
        return {}
    return value


def apply_result(
    state: ProjectCoordination, role_name: str, result: str | None
) -> ProjectCoordination:
    """Apply only self-consistent evidence from the specialist that owns it."""
    update = result_update(result)
    role = role_name.casefold()
    changes: dict[str, str | None] = {
        "active_bot_id": None,
        "active_task_id": None,
    }
    if "builder" in role:
        permitted = {
            key: value for key, value in update.items()
            if key in {"repository", "branch", "pull_request", "source_revision",
                       "preview_url", "preview_revision", "preview_digest"}
        }
        if (
            permitted.get("source_revision")
            and permitted.get("preview_revision")
            and permitted["source_revision"] != permitted["preview_revision"]
        ):
            permitted = {}
        if not {
            "source_revision", "preview_revision", "preview_digest", "preview_url"
        } <= set(permitted):
            return state.evolve(
                active_bot_id=None,
                active_task_id=None,
                phase="blocked",
                status_note="Builder finished, but exact preview revision evidence is missing.",
            ).validate()
        changes.update(permitted)
        if permitted.get("preview_revision") != state.accepted_preview_revision:
            changes.update(
                accepted_preview_revision=None,
                reviewed_revision=None,
                reviewer_verdict=None,
                merged_revision=None,
                deployed_revision=None,
                deployment_status=None,
            )
        changes.update(phase="preview_feedback", status_note="Preview ready for owner feedback.")
    elif "reviewer" in role:
        verdict = update.get("reviewer_verdict")
        reviewed = update.get("reviewed_revision")
        if reviewed != state.accepted_preview_revision:
            verdict = reviewed = None
        changes.update(
            reviewed_revision=reviewed,
            reviewer_verdict=verdict,
            phase="merge_ready" if verdict == "READY" else "correction",
            status_note=(
                "Reviewer accepted the owner-approved revision."
                if verdict == "READY"
                else "Reviewer returned changes to Builder."
                if verdict == "CHANGES_NEEDED"
                else "Review evidence did not match the accepted preview revision."
            ),
        )
    elif "deployer" in role:
        merged = update.get("merged_revision") or state.merged_revision
        deployed = update.get("deployed_revision")
        status = update.get("deployment_status")
        if (
            deployed != merged
            or state.reviewer_verdict != "READY"
            or state.reviewed_revision != state.accepted_preview_revision
        ):
            merged = deployed = status = None
        changes.update(
            deployment_url=update.get("deployment_url") if deployed else state.deployment_url,
            merged_revision=merged,
            deployed_revision=deployed,
            deployment_status=status,
            phase="deployed" if status == "healthy" else "blocked",
            status_note=(
                "Deployment is healthy." if status == "healthy"
                else "Deployment evidence needs attention."
            ),
        )
    elif "research" in role:
        changes.update(phase="research", status_note="Research completed.")
    return state.evolve(**changes).validate()


def accept_preview(state: ProjectCoordination) -> ProjectCoordination:
    if not state.preview_revision or state.preview_revision != state.source_revision:
        raise Rejected("project_preview_not_current", 409)
    return state.evolve(
        accepted_preview_revision=state.preview_revision,
        phase="review",
        status_note="Owner accepted the current preview revision.",
    ).validate()


def status_text(state: ProjectCoordination, agent_name: str | None = None) -> str:
    who = f" {agent_name} is working." if state.active_task_id and agent_name else ""
    artifact = ""
    if state.preview_url:
        artifact = f"\nPreview: {state.preview_url} ({state.preview_revision or 'revision unknown'})"
    if state.deployment_url:
        artifact += f"\nDeployment: {state.deployment_url} ({state.deployment_status or 'status unknown'})"
    return f"Project status · {state.phase.replace('_', ' ')}.{who}{artifact}"
