import assert from "node:assert/strict";
import test from "node:test";

import { actionReason, blockerMessages, guidanceStatus, phaseLabel } from "../dist/view-model.js";
import { parseWorkHome } from "../dist/contract.js";
import { deliveryHandoffs } from "../dist/delivery.js";

test("phase labels use operator language", () => {
  assert.equal(phaseLabel("active"), "Working");
  assert.equal(phaseLabel("recovering"), "Needs attention");
});

test("guidance labels distinguish receipt, completed response, lateness and uncertainty", () => {
  const label = application_state => guidanceStatus({ state: "accepted", application_state });
  assert.match(label("accepted"), /Queued/);
  assert.doesNotMatch(label("accepted"), /Used in/);
  assert.match(label("applied"), /completed model response/);
  assert.match(label("applied"), /Review the result/);
  assert.match(label("too_late"), /no longer accepting.*not used/);
  assert.match(label("not_applied"), /ended without using/);
  assert.match(label("unknown"), /could not confirm.*not be resent/);
  assert.match(label(null), /not yet confirmed/);
});

test("server action reasons become useful explanations", () => {
  assert.equal(
    actionReason({ enabled: false, reason: "fresh_assurance_required" }),
    "Confirm your sign-in again before reviewing this result.",
  );
  assert.equal(actionReason({ enabled: true, reason: null }), null);
});

test("unknown blocker codes do not expose raw internal text", () => {
  const card = { task: { blockers: ["operation_unknown", "future_internal_code"] } };
  assert.deepEqual(blockerMessages(card), [
    "Radhouse is checking an uncertain runtime result before continuing.",
    "This task is waiting for a checked condition.",
  ]);
});

test("work-home contract rejects incomplete server data", () => {
  assert.throws(
    () => parseWorkHome({ principal_id: "alice", role: "operator" }),
    /invalid_work_home/,
  );
});

test("work-home contract accepts the bounded empty view", () => {
  const view = parseWorkHome({
    principal_id: "alice",
    role: "operator",
    project_id: "personal-alice",
    project_name: "Alice's work",
    agents: [],
    tasks: [],
    start: { enabled: false, reason: "no_assigned_agents" },
  });
  assert.equal(view.project_id, "personal-alice");
});

test("software delivery handoffs expose every ready project agent in natural order", () => {
  const builder = { bot_id: "builder", display_name: "Builder", role_name: "Builder", provider_binding: "local", state: "ready" };
  const agents = [
    builder,
    { bot_id: "researcher", display_name: "Researcher", role_name: "Researcher", provider_binding: "local", state: "ready" },
    { bot_id: "deployer", display_name: "Deployer", role_name: "Deployer", provider_binding: "local", state: "ready" },
    { bot_id: "reviewer", display_name: "Reviewer", role_name: "Reviewer", provider_binding: "local", state: "ready" },
    { bot_id: "offline", display_name: "Offline", role_name: "Reviewer", provider_binding: "local", state: "maintenance" },
  ];

  const choices = deliveryHandoffs(builder, agents);

  assert.deepEqual(choices.map(choice => choice.target.bot_id), ["reviewer", "deployer", "researcher"]);
  assert.deepEqual(choices.map(choice => choice.label), ["Send to review", "Prepare deployment", "Delegate to Researcher"]);
  assert.match(choices[0].brief, /blocking defects/);
  assert.match(choices[1].brief, /protected human deployment decision/);
});

test("review findings return to Builder before release preparation", () => {
  const reviewer = { bot_id: "reviewer", display_name: "Reviewer", role_name: "Reviewer", provider_binding: "local", state: "ready" };
  const choices = deliveryHandoffs(reviewer, [
    reviewer,
    { bot_id: "deployer", display_name: "Deployer", role_name: "Deployer", provider_binding: "local", state: "ready" },
    { bot_id: "builder", display_name: "Builder", role_name: "Builder", provider_binding: "local", state: "ready" },
  ]);

  assert.deepEqual(choices.map(choice => choice.label), ["Return findings to Builder", "Prepare deployment"]);
  assert.match(choices[0].brief, /Address the blocking review findings/);
});
