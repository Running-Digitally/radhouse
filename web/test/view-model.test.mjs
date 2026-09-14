import assert from "node:assert/strict";
import test from "node:test";

import { actionReason, blockerMessages, phaseLabel } from "../dist/view-model.js";
import { parseWorkHome } from "../dist/contract.js";

test("phase labels use operator language", () => {
  assert.equal(phaseLabel("active"), "Working");
  assert.equal(phaseLabel("recovering"), "Needs attention");
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
