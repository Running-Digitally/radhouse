import type { AgentSummary } from "./types.js";

export interface DeliveryHandoff {
  target: AgentSummary;
  label: string;
  brief: string;
}

function role(agent: AgentSummary): string {
  return agent.role_name.trim().toLowerCase();
}

function isBuilder(agent: AgentSummary): boolean {
  return ["builder", "engineer"].includes(role(agent));
}

function priority(source: AgentSummary, target: AgentSummary): number {
  const sourceRole = role(source);
  const targetRole = role(target);
  if (isBuilder(source) && targetRole === "reviewer") return 0;
  if (sourceRole === "reviewer" && isBuilder(target)) return 0;
  if (targetRole === "deployer") return 1;
  if (targetRole === "reviewer") return 2;
  return 3;
}

function handoff(source: AgentSummary, target: AgentSummary): DeliveryHandoff {
  const sourceRole = role(source);
  const targetRole = role(target);
  if (targetRole === "reviewer") {
    return {
      target,
      label: `Send to ${target.display_name} for review`,
      brief: "Review the exact completed work above. Separate blocking defects from suggestions and state whether it is ready to proceed.",
    };
  }
  if (sourceRole === "reviewer" && isBuilder(target)) {
    return {
      target,
      label: `Return findings to ${target.display_name}`,
      brief: "Address the blocking review findings above, keep the change bounded, and report the updated revision and validation.",
    };
  }
  if (targetRole === "deployer") {
    return {
      target,
      label: `Prepare deployment with ${target.display_name}`,
      brief: "Check the reviewed result above against the configured release target. Report readiness and wait for the protected human deployment decision before invoking any deployment operation.",
    };
  }
  return {
    target,
    label: `Delegate to ${target.display_name}`,
    brief: "Continue from the exact completed result above within this project's existing access.",
  };
}

export function deliveryHandoffs(
  source: AgentSummary,
  agents: AgentSummary[],
): DeliveryHandoff[] {
  return agents
    .filter((agent) => agent.state === "ready" && agent.bot_id !== source.bot_id)
    .map((agent) => handoff(source, agent))
    .sort((left, right) =>
      priority(source, left.target) - priority(source, right.target)
      || left.target.display_name.localeCompare(right.target.display_name));
}
