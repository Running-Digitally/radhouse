import type { ActionState, Phase, TaskCard, TaskSummary } from "./types.js";

export function guidanceStatus(receipt: TaskSummary["guidance"][number]): string {
  const labels = {
    accepted: "Queued for this run’s next tool checkpoint.",
    applied: "Used in a completed model response. Review the result to check how it was followed.",
    too_late: "The run is no longer accepting guidance. This update was not used; include it in a follow-up.",
    not_applied: "The run ended without using this update at a later checkpoint. It was not resent; include it in a follow-up.",
    unknown: "The runtime could not confirm whether this update was used. It will not be resent automatically.",
  };
  if (receipt.application_state) return labels[receipt.application_state];
  return receipt.state === "accepted" ? "Received by the agent; application is not yet confirmed."
    : receipt.state === "superseded" ? "The run advanced to a later decision; this earlier response is closed."
    : ["submitted", "unknown"].includes(receipt.state) ? "Delivery outcome unknown. This instruction will not be sent again automatically."
    : "The agent did not accept this instruction.";
}

const phaseLabels: Record<Phase, string> = {
  queued: "Ready to begin",
  active: "Working",
  recovering: "Needs attention",
  stopping: "Stopping safely",
  closed: "Finished",
};

const reasonLabels: Record<string, string> = {
  read_only_role: "Your access is read-only.",
  no_assigned_agents: "Ask an administrator to assign an agent.",
  agents_unavailable: "Your agents are temporarily unavailable. Your draft can wait here.",
  already_published: "This result has already been published to its reviewed audience.",
  task_closed: "This task is already finished.",
  task_not_pausable: "Pause becomes available while the agent is working.",
  task_not_paused: "This task is not paused.",
  result_not_ready: "Review becomes available when the result is ready.",
};

const blockerLabels: Record<string, string> = {
  operation_unknown: "Radhouse is checking an uncertain runtime result before continuing.",
  runtime_unavailable: "The agent runtime is temporarily unavailable.",
  runtime_stop: "Radhouse has not yet confirmed that the exact run stopped.",
  provider_unavailable: "The selected model service is unavailable.",
  provider_incompatible: "The currently served model does not meet this task’s needs.",
  provider_mismatch: "The task’s model-service binding changed unexpectedly.",
  grant_withdrawal: "Access needed by this task was withdrawn.",
  human_pause: "Paused by a person.",
  cancel_requested: "Cancellation was requested.",
  resource_busy: "Another task is using the same exclusive resource.",
  budget_exhausted: "This task has reached its retry budget.",
};

export function phaseLabel(phase: Phase): string {
  return phaseLabels[phase];
}

export function actionReason(action: ActionState): string | null {
  if (action.enabled || action.reason === null) return null;
  return reasonLabels[action.reason] ?? "This action is unavailable right now.";
}

export function blockerMessages(card: TaskCard): string[] {
  return card.task.blockers.map(
    (blocker) => blockerLabels[blocker] ?? "This task is waiting for a checked condition.",
  );
}
