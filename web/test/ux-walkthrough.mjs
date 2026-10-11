import assert from "node:assert/strict";

const { chromium, expect } = await import(process.env.RADHOUSE_PLAYWRIGHT_MODULE);
const browser = await chromium.launch({ headless: true,
  ...(process.env.RADHOUSE_BROWSER_CHANNEL ? { channel: process.env.RADHOUSE_BROWSER_CHANNEL } : {}) });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const tid = "11111111-1111-4111-8111-111111111111";
const enabled = { enabled: true, reason: null }, disabled = { enabled: false, reason: "task_closed" };
const project = { project_id: "personal-alice", display_name: "My work",
  conversation_id: "personal-alice:alice:radhouse", binding_revision: 1, bot_ids: ["bot-alpha"], coordination: null };
const card = { sequence: 1, title: { task_id: tid, title: "Garden comparison", source: "brief", revision: 1 },
  cancel: disabled, pause: disabled, resume: disabled, review: enabled, publication: null,
  task: { task_id: tid, owner_id: "alice", bot_id: "bot-alpha", project_id: project.project_id,
    brief: "Compare two gardens.", provider_binding: "fake-local", resource_key: null, disable_tools: false,
    budget_remaining: 2, task_revision: 1, state_revision: 2, phase: "closed", outcome: "completed", blockers: [],
    attempt_id: null, generation: 1, model_id: "fake-local", result: "# Garden result\n\nThe garden has shade.",
    result_digest: "a".repeat(64), observation_sequence: 1, files: [], follows_task_id: null, guidance: [], permission_request: null } };
const newer = Array.from({ length: 3 }, (_, index) => {
  const next = structuredClone(card); next.sequence = index + 2;
  next.task.task_id = `${index + 2}1111111-1111-4111-8111-111111111111`;
  next.title.task_id = next.task.task_id; next.title.title = `Newer result ${index}`; return next;
});
const home = { principal_id: "alice", role: "operator", project_id: project.project_id, project_name: project.display_name,
  agents: [{ bot_id: "bot-alpha", display_name: "Researcher", role_name: "Researcher", provider_binding: "fake-local", state: "ready" }],
  tasks: [...newer, card], start: enabled, shared_results: [] };
const link = { link_id: "link-alice", bot_id: "bot-alpha", display_name: "Researcher", channel_id: "dm-alice", error_code: null };
const png = { name: "sample.png", media_type: "image/png", encoding: "base64", sha256: "a".repeat(64),
  content: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=" };
const history = { messages: [{ message_id: "m1", author: "bot-alpha", content: "Your garden result is ready.", source: "radhouse",
  state: "result", task_id: tid, created_at: 1791676800, sequence: 1, files: [png] }], cursor: 1, error_code: null };
let hasConversation = true, homeRequests = 0, slow = false;
const posts = [], errors = [];
page.on("pageerror", error => errors.push(String(error)));
page.on("console", message => { if (message.type() === "error" && /Content Security Policy/.test(message.text())) errors.push(message.text()); });
await page.route("**/*", async route => {
  const request = route.request(), url = new URL(request.url());
  const json = value => route.fulfill({ json: value });
  if (url.pathname === "/auth/session") return json({ principal_id: "alice", username: "alice", assurance_until: "2099-01-01T00:00:00Z",
    conversation_id: project.conversation_id, binding_revision: 1, project_id: project.project_id, csrf_token: "synthetic" });
  if (url.pathname === "/projects") return json([project]);
  if (url.pathname === "/work-home") {
    homeRequests++; if (slow) await new Promise(resolve => setTimeout(resolve, 11_000));
    return json(home);
  }
  if (url.pathname === "/conversations") return json(hasConversation ? [link] : []);
  if (url.pathname.endsWith("/messages")) {
    if (request.method() === "POST") posts.push(request.postDataJSON());
    return json(history);
  }
  if (url.pathname === "/tasks" && request.method() === "POST") {
    posts.push(request.postDataJSON()); return json(card.task);
  }
  if (url.pathname.endsWith("/events")) return json({ task: card.task, events: [], cursor: 0, resync_required: false });
  return route.continue(); // Serve the actual application bundle and CSP.
});
const reload = async () => { await page.reload(); await page.getByRole("heading", { name: "What needs you", exact: true }).waitFor(); };
const file = (name, text) => ({ name, mimeType: "text/plain", buffer: Buffer.from(text) });
try {
  await page.goto(`${process.env.RADHOUSE_BROWSER_ORIGIN}/app/`);
  await page.getByRole("button", { name: "Review result", exact: true }).click();
  const task = page.locator(`[data-task-id="${tid}"]`);
  await expect(task.locator(".result-viewer")).toBeVisible();
  assert.equal(await page.locator(".recent-activity").evaluate(node => node.open), true);
  assert.equal(await page.locator(".older-work").evaluate(node => node.open), true);
  await expect(task.locator("h3").first()).toBeFocused();
  await page.getByText("sample.png", { exact: true }).click();
  await expect(page.locator("img.message-reference__image")).toBeVisible();
  await expect.poll(() => page.locator("img.message-reference__image").evaluate(node => node.naturalWidth)).toBeGreaterThan(0);

  // New data forces a render; reading state must survive it.
  await task.locator(".task-card__assignment > summary").click();
  await task.getByRole("tab", { name: "Source", exact: true }).click();
  history.messages.push({ ...history.messages[0], message_id: "m2", sequence: 2, content: "Updated progress", task_id: null, files: [] });
  history.cursor = 2;
  await page.getByText("Updated progress", { exact: true }).waitFor({ timeout: 15_000 });
  await expect(task.getByRole("tab", { name: "Source", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(task.getByRole("tab", { name: "Source", exact: true })).toBeFocused();
  assert.equal(await task.locator(".task-card__assignment").evaluate(node => node.open), true);
  assert.equal(await page.locator(".message-reference").evaluate(node => node.open), true);

  await task.locator(".task-card__more > summary").click();
  await task.getByRole("button", { name: "Ask for a change", exact: true }).click();
  await expect(page.getByLabel("Assignment", { exact: true })).toBeFocused();
  await page.getByLabel("Assignment", { exact: true }).fill("Explain the shade in more detail.");
  const picker = page.getByLabel("Reference files", { exact: false });
  await picker.setInputFiles(file("first.txt", "first"));
  await page.getByRole("button", { name: "Remove first.txt" }).waitFor();
  await picker.setInputFiles(file("second.txt", "second"));
  await page.getByRole("button", { name: "Remove second.txt" }).waitFor();
  await expect(page.getByRole("list", { name: "Selected attachments" }).locator("li")).toHaveCount(2);
  await page.getByRole("button", { name: "Remove first.txt" }).click();
  await expect(page.getByRole("list", { name: "Selected attachments" }).locator("li")).toHaveCount(1);
  await picker.setInputFiles(file("too-large.txt", "x".repeat(65537)));
  await page.getByRole("alert").waitFor();
  await expect(page.getByRole("button", { name: "Remove second.txt" })).toBeVisible();
  await page.getByRole("button", { name: "Send assignment", exact: true }).click();
  await page.getByRole("button", { name: "Send message", exact: true }).waitFor();
  assert.equal(posts.at(-1).start.follows_task_id, tid);
  assert.deepEqual(posts.at(-1).start.files.map(item => item.name), ["second.txt"]);

  // The conversation composer uses the same additive picker for chooser,
  // paste and drop. A failed addition must not discard the existing files.
  await picker.setInputFiles(file("chosen.txt", "chosen"));
  await page.getByRole("button", { name: "Remove chosen.txt" }).waitFor();
  const composer = page.getByLabel("Message Researcher", { exact: true });
  for (const eventType of ["paste", "drop"]) {
    await composer.evaluate((node, type) => {
      const data = new DataTransfer(); data.items.add(new File([type], `${type}.txt`, { type: "text/plain" }));
      node.dispatchEvent(type === "paste" ? new ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true })
        : new DragEvent("drop", { dataTransfer: data, bubbles: true, cancelable: true }));
    }, eventType);
    await page.getByRole("button", { name: `Remove ${eventType}.txt` }).waitFor();
  }
  await expect(page.getByRole("list", { name: "Selected attachments" }).locator("li")).toHaveCount(3);
  await page.getByRole("button", { name: "Remove paste.txt" }).click();
  await composer.fill("Use both remaining references.");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.getByRole("list", { name: "Selected attachments" }).locator("li")).toHaveCount(0);
  assert.deepEqual(posts.at(-1).files.map(item => item.name), ["chosen.txt", "drop.txt"]);

  home.role = "viewer";
  home.shared_results = [{ publication_id: "publication-1", owner_id: "bob", content: "# Approved shared result", digest: "b".repeat(64) }];
  await reload();
  await expect(page.getByRole("heading", { name: "Approved shared result", exact: true })).toBeVisible();
  assert.equal(await page.getByRole("button", { name: "Send message", exact: true }).count(), 0);
  assert.equal(await page.getByRole("button", { name: "Start fresh thread", exact: true }).count(), 0);
  assert.equal(await page.getByRole("button", { name: "Reply", exact: true }).count(), 0);

  home.role = "operator"; home.tasks = [card]; hasConversation = false;
  for (const [phase, outcome, blockers] of [["recovering", null, ["budget_exhausted"]], ["recovering", null, []], ["closed", "failed", []]]) {
    Object.assign(card.task, { phase, outcome, blockers, result: null, result_digest: null });
    await reload();
    await expect(page.locator(".attention-panel")).toContainText("1 assignment needs attention");
    await page.getByRole("button", { name: "View task needing attention", exact: true }).click();
    await expect(task).toBeVisible();
  }
  await page.setViewportSize({ width: 320, height: 800 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= 320), true, "The composer overflows a narrow screen");

  // An 11-second response crosses the old fixed 10-second interval. It must
  // finish once, without a second request invalidating the successful load.
  slow = true; const before = homeRequests;
  await page.reload();
  await page.getByRole("heading", { name: "What needs you", exact: true }).waitFor({ timeout: 20_000 });
  assert.equal(homeRequests - before, 1);
  assert.deepEqual(errors, []);
  console.log("UX regressions passed: hidden results, follow-up, image CSP, refresh state, attachments, viewer controls, shared results, attention and slow loads.");
} finally {
  slow = false;
  await browser.close();
}
