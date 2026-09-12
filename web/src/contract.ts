import type {
  ActionState, AgentSummary, Phase, Role, TaskCard, TaskSummary, WorkHome,
} from "./types.js";

type RecordValue = Record<string, unknown>;

function record(value: unknown): RecordValue {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("invalid_work_home");
  }
  return value as RecordValue;
}

function string(value: unknown): string {
  if (typeof value !== "string") throw new Error("invalid_work_home");
  return value;
}

function nullableString(value: unknown): string | null {
  return value === null ? null : string(value);
}

function integer(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value)) {
    throw new Error("invalid_work_home");
  }
  return value;
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) throw new Error("invalid_work_home");
  return value.map(string);
}

function oneOf<T extends string>(value: unknown, choices: readonly T[]): T {
  if (typeof value !== "string" || !choices.includes(value as T)) {
    throw new Error("invalid_work_home");
  }
  return value as T;
}

function action(value: unknown): ActionState {
  const item = record(value);
  if (typeof item.enabled !== "boolean") throw new Error("invalid_work_home");
  return { enabled: item.enabled, reason: nullableString(item.reason) };
}

function agent(value: unknown): AgentSummary {
  const item = record(value);
  return {
    bot_id: string(item.bot_id),
    display_name: string(item.display_name),
    role_name: string(item.role_name),
    provider_binding: string(item.provider_binding),
    state: string(item.state),
  };
}

const phases = ["queued", "active", "recovering", "stopping", "closed"] as const;
const outcomes = ["completed", "cancelled", "failed"] as const;

function task(value: unknown): TaskSummary {
  const item = record(value);
  return {
    task_id: string(item.task_id),
    owner_id: string(item.owner_id),
    bot_id: string(item.bot_id),
    project_id: string(item.project_id),
    brief: string(item.brief),
    provider_binding: string(item.provider_binding),
    resource_key: nullableString(item.resource_key),
    budget_remaining: integer(item.budget_remaining),
    task_revision: integer(item.task_revision),
    state_revision: integer(item.state_revision),
    phase: oneOf<Phase>(item.phase, phases),
    outcome: item.outcome === null ? null : oneOf(item.outcome, outcomes),
    blockers: stringArray(item.blockers),
    attempt_id: nullableString(item.attempt_id),
    generation: integer(item.generation),
    model_id: nullableString(item.model_id),
    result: nullableString(item.result),
    result_digest: nullableString(item.result_digest),
    observation_sequence: integer(item.observation_sequence),
  };
}

function taskCard(value: unknown): TaskCard {
  const item = record(value);
  return {
    task: task(item.task),
    cancel: action(item.cancel),
    pause: action(item.pause),
    resume: action(item.resume),
    review: action(item.review),
  };
}

const roles = ["admin", "operator", "viewer"] as const;

export function parseWorkHome(value: unknown): WorkHome {
  const item = record(value);
  if (!Array.isArray(item.agents) || !Array.isArray(item.tasks)) {
    throw new Error("invalid_work_home");
  }
  return {
    principal_id: string(item.principal_id),
    role: oneOf<Role>(item.role, roles),
    project_id: string(item.project_id),
    agents: item.agents.map(agent),
    tasks: item.tasks.map(taskCard),
    start: action(item.start),
  };
}
