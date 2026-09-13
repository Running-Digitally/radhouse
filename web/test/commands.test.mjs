import assert from "node:assert/strict";
import test from "node:test";
import { CommandLedger } from "../dist/commands.js";
import { RadhouseApi } from "../dist/api.js";

function storage() {
  const data = new Map();
  return { getItem: (key) => data.get(key) ?? null, setItem: (key, value) => data.set(key, value),
    removeItem: (key) => data.delete(key), data };
}

test("a lost response and page reconnect preserve the command identity without storing content", async () => {
  const disk = storage();
  const body = { brief: "Private research material" };
  const first = await new CommandLedger(disk).prepare("alice:project", "/tasks", body, "alice:project", 1);
  const retry = await new CommandLedger(disk).prepare("alice:project", "/tasks", body, "alice:project", 1);
  assert.deepEqual(retry, first);
  assert.ok(!JSON.stringify([...disk.data]).includes(body.brief));
  const changed = await new CommandLedger(disk).prepare("alice:project", "/tasks", body, "alice:project", 2);
  assert.notEqual(changed.envelope.command_key, first.envelope.command_key);
});

test("successful submission retires its identity and allows a deliberate second assignment", async () => {
  const ledger = new CommandLedger(storage());
  const first = await ledger.prepare("scope", "/tasks", {}, "scope", 1);
  ledger.complete(first.key);
  const second = await ledger.prepare("scope", "/tasks", {}, "scope", 1);
  assert.notEqual(second.envelope.command_key, first.envelope.command_key);
});

test("actual API retry after lost start reply reuses envelope and body", async () => {
  const previous = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (_path, options) => {
    calls.push(JSON.parse(options.body));
    if (calls.length === 1) throw new TypeError("lost reply");
    return new Response(JSON.stringify({ task_id: "one-task" }), { status: 200 });
  };
  try {
    const api = new RadhouseApi("alice:project", 1, "csrf", new CommandLedger());
    const input = { botId: "researcher", projectId: "project", brief: "One task", providerBinding: "local" };
    await assert.rejects(api.start(input));
    await api.start(input);
    assert.deepEqual(calls[0], calls[1]);
    await api.start(input);
    assert.notEqual(calls[1].envelope.command_key, calls[2].envelope.command_key);
  } finally { globalThis.fetch = previous; }
});
