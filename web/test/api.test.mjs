import assert from "node:assert/strict";
import test from "node:test";
import { RadhouseApi } from "../dist/api.js";

const project = index => ({ project_id: `project-${index}`, display_name: `Project ${index}`,
  conversation_id: `conversation-${String(index).padStart(3, "0")}`, binding_revision: 1,
  bot_ids: ["bot-alpha"], coordination: null });

test("project discovery reads every page and preserves a project beyond the first hundred", async () => {
  const calls = [];
  const api = new RadhouseApi("current", 1, "csrf", undefined, async path => {
    calls.push(path);
    return Response.json(path === "/projects" ? Array.from({ length: 100 }, (_, i) => project(i)) : [project(100)]);
  });
  assert.equal((await api.projects()).at(-1).project_id, "project-100");
  assert.deepEqual(calls, ["/projects", "/projects?after=conversation-099"]);
});

test("a repeated project page fails instead of looping or duplicating results", async () => {
  const api = new RadhouseApi("current", 1, "csrf", undefined, async () =>
    Response.json(Array.from({ length: 100 }, (_, i) => project(i))));
  await assert.rejects(api.projects(), error => error.code === "invalid_server_response");
});
