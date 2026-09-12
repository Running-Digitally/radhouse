export type Role = "admin" | "operator" | "viewer";
export type Phase = "queued" | "active" | "recovering" | "stopping" | "closed";

export interface ActionState {
  enabled: boolean;
  reason: string | null;
}

export interface AgentSummary {
  bot_id: string;
  display_name: string;
  role_name: string;
  provider_binding: string;
  state: string;
}

export interface TaskSummary {
  task_id: string;
  owner_id: string;
  bot_id: string;
  project_id: string;
  brief: string;
  provider_binding: string;
  resource_key: string | null;
  budget_remaining: number;
  task_revision: number;
  state_revision: number;
  phase: Phase;
  outcome: "completed" | "cancelled" | "failed" | null;
  blockers: string[];
  attempt_id: string | null;
  generation: number;
  model_id: string | null;
  result: string | null;
  result_digest: string | null;
  observation_sequence: number;
}

export interface TaskCard {
  task: TaskSummary;
  cancel: ActionState;
  pause: ActionState;
  resume: ActionState;
  review: ActionState;
}

export interface WorkHome {
  principal_id: string;
  role: Role;
  project_id: string;
  agents: AgentSummary[];
  tasks: TaskCard[];
  start: ActionState;
}

export interface Review {
  review_id: string;
  task_id: string;
  reviewer_id: string;
  digest: string;
  audience: string[];
  task_revision: number;
  state_revision: number;
  expires_at: string;
  revision: number;
  state: string;
}

export interface Envelope {
  channel: "radhouse";
  event_id: string;
  conversation_id: string;
  binding_revision: number;
  command_key: string;
  mirrored: false;
}
