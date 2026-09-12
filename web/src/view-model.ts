import type { ActionState, Phase, TaskCard } from "./types.js";

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
  task_closed: "This task is already finished.",
  task_not_pausable: "Pause becomes available while the agent is working.",
  task_not_paused: "This task is not paused.",
  result_not_ready: "Review becomes available when the result is ready.",
  fresh_assurance_required: "Confirm your sign-in again before reviewing this result.",
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
