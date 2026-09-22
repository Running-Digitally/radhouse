import type { AttachedFile } from "./files.js";

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
  disable_tools: boolean;
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
    files: AttachedFile[];
    follows_task_id: string | null;
    guidance: { id: string; kind: string; text: string | null; choice: string | null; state: string;
      application_state: "accepted" | "applied" | "too_late" | "not_applied" | "unknown" | null }[];
    permission_request: { request_id: string; command: string; digest: string; allow_once: boolean } | null;
}

export interface TaskCard {
  task: TaskSummary;
  sequence: number;
  title: {
    task_id: string;
    title: string;
    source: "brief" | "agent" | "owner";
    revision: number;
  };
  cancel: ActionState;
  pause: ActionState;
  resume: ActionState;
  review: ActionState;
  publication: { publication_id: string; digest: string; audience: string[] } | null;
}

export interface WorkHome {
  principal_id: string;
  role: Role;
  project_id: string;
  project_name: string;
  agents: AgentSummary[];
  tasks: TaskCard[];
  start: ActionState;
}

export interface Project {
  project_id: string;
  display_name: string;
  conversation_id: string;
  binding_revision: number;
  bot_ids: string[];
  coordination: ProjectCoordination | null;
}

export interface ProjectCoordination {
  project_id: string;
  revision: number;
  phase: "intake" | "research" | "building" | "preview_feedback" | "review" |
    "correction" | "merge_ready" | "deployment" | "deployed" | "blocked";
  active_bot_id: string | null;
  active_task_id: string | null;
  latest_task_id: string | null;
  pending_message_id: string | null;
  repository: string | null;
  branch: string | null;
  pull_request: string | null;
  source_revision: string | null;
  preview_url: string | null;
  preview_revision: string | null;
  preview_digest: string | null;
  accepted_preview_revision: string | null;
  reviewed_revision: string | null;
  reviewer_verdict: string | null;
  merged_revision: string | null;
  deployment_url: string | null;
  deployed_revision: string | null;
  deployment_status: string | null;
  status_note: string | null;
  handoff_bot_id: string | null;
  handoff_brief: string | null;
}

export interface TaskEvent {
  kind: string;
  state_revision: number;
  cursor: number;
  data: { label?: string; occurred_at?: number; event?: string };
}

export interface TaskEvents {
  task: TaskSummary;
  events: TaskEvent[];
  cursor: number;
  resync_required: boolean;
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
