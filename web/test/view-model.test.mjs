import assert from "node:assert/strict";
import test from "node:test";

import { actionReason, blockerMessages, guidanceStatus, phaseLabel, isFinished, attentionFor } from "../dist/view-model.js";
import { parseWorkHome } from "../dist/contract.js";

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
  assert.match(guidanceStatus({ state: "superseded", application_state: null }), /advanced to a later decision.*closed/);
});

test("server action reasons become useful explanations", () => {
  assert.equal(actionReason({ enabled: false, reason: "result_not_ready" }),
    "Review becomes available when the result is ready.");
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

test("a closed agent run does not hide waiting parent work", () => {
  const card = { task: { phase: "closed", outcome: "completed", blockers: [] },
    work: { state: "waiting", blockers: [{ message: "A dependency prevented completion." }] } };
  assert.equal(isFinished(card), false);
  assert.deepEqual(blockerMessages(card), ["A dependency prevented completion."]);
  assert.equal(isFinished({ ...card, work: { ...card.work, state: "completed" } }), true);
});

test("waiting work never hides a decision on a retained legacy task", () => {
  const waiting = { task: { phase: "closed", permission_request: null },
    work: { work_id: "new", state: "waiting", needs_input: false } };
  const permission = { task: { phase: "active", permission_request: { request_id: "permission" } } };
  assert.equal(attentionFor({tasks:[waiting,permission],attention:[]}).kind,"input");
  assert.deepEqual(attentionFor({tasks:[waiting,permission],attention:[]}).tasks,[permission]);
  assert.equal(attentionFor({tasks:[waiting],attention:[]}).kind,"waiting");
});
