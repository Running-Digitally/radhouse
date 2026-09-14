import { ApiError, RadhouseApi, operatorClient } from "./api.js";
import type { AuthSession } from "./api.js";
import { actionReason, blockerMessages, guidanceStatus, phaseLabel } from "./view-model.js";
import type { Project, Review, TaskCard, TaskEvents, WorkHome } from "./types.js";
import { conversationPanel } from "./conversations.js";
import type { ConversationDraft, ConversationHistory, ConversationLink } from "./conversations.js";

export function mountWorkHome(page: HTMLElement, client = operatorClient()): () => void {
let reviewToken = new URLSearchParams(window.location.hash.slice(1)).get("review");
let reviewTarget: { task_id: string; project_id: string; conversation_id: string; binding_revision: number } | null = null;
function clearReviewTarget(): void {
  reviewToken = null; reviewTarget = null;
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
}
let disposed = false;
let api: RadhouseApi | null = null;
let signedIn: AuthSession | null = null;
let projects: Project[] = [];
let selectedProject = "";
let loadGeneration = 0;
let sessionEpoch = 0;
let actionsInFlight = 0;
let filePickerOpen = false;
const drafts = new Map<string, { brief: string; bot: string; files: { name: string; content: string }[]; followsTaskId?: string }>();
const reviews = new Map<string, Review>();
const expanded = new Set<string>();
const timelines = new Map<string, TaskEvents>();
const conversationDrafts = new Map<string, ConversationDraft>();
const guidanceDrafts = new Map<string, string>();
let conversationLinks: ConversationLink[] = [];
let conversationHistory: ConversationHistory | null = null;
let selectedConversation = "";

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function notice(message: string, error = false): HTMLElement {
  const node = element("div", `notice${error ? " notice--error" : ""}`, message);
  node.setAttribute("role", error ? "alert" : "status");
  return node;
}
function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const labels: Record<string, string> = {
      review_link_denied: "This review link is expired or no longer available to your account. Open your work home, or ask Researcher for status to get a fresh link.",
      stale_state: "The task changed. Review the latest state before trying again.",
      fresh_assurance_required: "Confirm your sign-in before reviewing this result.",
      binding_denied: "Your access to this conversation changed.",
      access_denied: "Your access to this project or agent changed.",
      private_task: "This task is private to another person.",
      invalid_server_response: "The response could not be verified. Refresh to check the task before retrying.",
      invalid_credentials: "The password or authenticator code was not accepted. Use a fresh code.",
      authentication_required: "Please sign in to continue.",
      csrf_denied: "Your session changed. Refresh before retrying.",
      publication_conflict: "This result already has a publication. Refresh to see its reviewed audience.",
      review_task_changed: "The result changed after review. Prepare a new review.",
      review_expired: "The review expired. Prepare a fresh review of the current result.",
      bot_unavailable: "This agent is unavailable. Your assignment draft is retained.",
      invalid_input_files: "Choose up to four UTF-8 text files, no more than 64 KB in total.",
      runtime_guidance_receipts_unavailable: "This runtime cannot confirm live guidance yet. Include the update in a follow-up.",
      task_not_accepting_control: "This task cannot accept guidance now. Include the update in a follow-up.",
      control_outcome_unknown: "An earlier instruction is still unconfirmed. Check its outcome before sending another.",
    };
    return labels[error.code] ?? "Radhouse could not complete the action. Refresh to check its current state.";
  }
  return "The connection was interrupted. Your draft is retained; retrying the same request uses its original task identity.";
}
function field(label: string, name: string, type = "text"): { wrapper: HTMLLabelElement; input: HTMLInputElement } {
  const wrapper = element("label", "field");
  const input = element("input", "field__control");
  input.name = name;
  input.type = type;
  input.required = true;
  if (type === "password") input.autocomplete = "current-password";
  if (name === "totp") {
    input.autocomplete = "one-time-code";
    input.inputMode = "numeric";
    input.pattern = "[0-9]{6}";
    input.maxLength = 6;
  }
  wrapper.append(element("span", "field__label", label), input);
  return { wrapper, input };
}
async function action(button: HTMLButtonElement, run: () => Promise<void>): Promise<void> {
  const epoch = sessionEpoch;
  const label = button.textContent;
  const controls = Array.from(page.querySelectorAll<HTMLInputElement | HTMLButtonElement | HTMLSelectElement | HTMLTextAreaElement>("input, button, select, textarea"))
    .map((node) => ({ node, disabled: node.disabled }));
  for (const control of controls) control.node.disabled = true;
  page.setAttribute("aria-busy", "true");
  actionsInFlight++;
  button.disabled = true;
  button.textContent = "Working…";
  try { await run(); }
  catch (error) {
    if (epoch !== sessionEpoch) return;
    if (error instanceof ApiError && error.status === 401) loginScreen(errorMessage(error));
    else if (error instanceof ApiError && ["access_denied", "binding_denied", "stale_state"].includes(error.code)) {
      await load(errorMessage(error));
    } else page.prepend(notice(errorMessage(error), true));
  } finally {
    actionsInFlight--;
    for (const control of controls) if (control.node.isConnected) control.node.disabled = control.disabled;
    page.removeAttribute("aria-busy");
    button.textContent = label;
  }
}
function button(label: string, run: (node: HTMLButtonElement) => Promise<void>, primary = false): HTMLButtonElement {
  const node = element("button", `button button--${primary ? "primary" : "secondary"}`, label);
  node.type = "button";
  node.addEventListener("click", () => void action(node, () => run(node)));
  return node;
}
function applySession(session: AuthSession): void {
  signedIn = session;
  api = client.fromSession(session);
  selectedProject ||= session.project_id;
}
function loginScreen(message?: string): void {
  loadGeneration++;
  sessionEpoch++;
  filePickerOpen = false;
  api = null;
  signedIn = null;
  selectedProject = "";
  projects = [];
  // Private display state never crosses an account change.
  drafts.clear(); reviews.clear(); expanded.clear(); timelines.clear(); conversationDrafts.clear(); guidanceDrafts.clear();
  conversationLinks = []; conversationHistory = null; selectedConversation = "";
  reviewTarget = null;
  page.replaceChildren();
  const card = element("section", "login-card");
  card.append(element("p", "eyebrow", "Radhouse · A home for your agents"),
    element("h1", "page-title", "Welcome home"), element("p", "muted", "Sign in with your Radhouse account."));
  if (message) card.append(notice(message, true));
  const form = element("form", "login-form");
  const username = field("Username", "username"); username.input.autocomplete = "username";
  const password = field("Password", "password", "password");
  const totp = field("Authenticator code", "totp");
  const submit = element("button", "button button--primary", "Sign in"); submit.type = "submit";
  form.append(username.wrapper, password.wrapper, totp.wrapper, submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    void action(submit, async () => {
      const epoch = sessionEpoch;
      const session = await client.login(username.input.value, password.input.value, totp.input.value);
      password.input.value = ""; totp.input.value = "";
      if (epoch !== sessionEpoch || disposed) return;
      applySession(session);
      await load();
    });
  });
  card.append(form); page.append(card);
}
function assurancePanel(): HTMLElement {
  const panel = element("section", "review-panel");
  panel.append(element("h3", "section-title", "Confirm it’s you"),
    element("p", "muted", "Your task stays here while you confirm your password and a fresh authenticator code."));
  const form = element("form", "login-form");
  const password = field("Password", "password", "password");
  const code = field("Authenticator code", "totp");
  const submit = element("button", "button button--primary", "Confirm sign-in"); submit.type = "submit";
  form.append(password.wrapper, code.wrapper, submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    void action(submit, async () => {
      if (!api) return;
      signedIn = await api.reauthenticate(password.input.value, code.input.value);
      password.input.value = ""; code.input.value = "";
      await load("Sign-in confirmed. You can now review the result.");
    });
  });
  panel.append(form);
  return panel;
}
function reviewPanel(card: TaskCard, review: Review): HTMLElement {
  const panel = element("section", "review-panel");
  panel.append(element("h4", "review-panel__title", "Review this exact result"),
    element("p", "muted", `Share with: ${review.audience.map((id) => id === signedIn?.principal_id ? "Only me" : id).join(", ")}`),
    element("p", "muted", `Review expires ${new Date(review.expires_at).toLocaleTimeString()}`),
    element("p", "digest", `Artifact SHA-256: ${review.digest}`),
    element("pre", "result", card.task.result ?? ""));
  panel.append(button("Approve and publish", async () => {
    if (!api || card.task.result === null) return;
    if (new Date(review.expires_at).getTime() <= Date.now()) {
      reviews.delete(card.task.task_id);
      await load("The review expired. Select the audience and review again.");
      return;
    }
    await api.publish(review, card.task.result);
    reviews.delete(card.task.task_id);
    await load("Result published to the reviewed audience.");
  }, true), button("Back", async () => { reviews.delete(card.task.task_id); await load(); }));
  return panel;
}
async function prepareAudience(article: HTMLElement, card: TaskCard): Promise<void> {
  if (!api) return;
  const epoch = sessionEpoch;
  const currentApi = api;
  const audience = await currentApi.reviewAudience(card.task.task_id);
  if (!article.isConnected || epoch !== sessionEpoch) return;
  const panel = element("section", "review-panel");
  panel.append(element("h4", "review-panel__title", "Who may see this result?"),
    element("p", "muted", "Only this result is shared. Your other conversations, files and agent memory stay private."));
  const choices: HTMLInputElement[] = [];
  for (const principal of audience) {
    const label = element("label", "audience-choice");
    const input = element("input"); input.type = "checkbox"; input.value = principal;
    input.checked = principal === signedIn?.principal_id;
    choices.push(input);
    label.append(input, document.createTextNode(principal === signedIn?.principal_id ? "Me" : principal));
    panel.append(label);
  }
  panel.append(button("Review selected audience", async () => {
    const selected = choices.filter((item) => item.checked).map((item) => item.value);
    if (selected.length === 0) { panel.prepend(notice("Choose at least one recipient.", true)); return; }
    const review = await currentApi.prepareReview(card.task, selected);
    if (epoch !== sessionEpoch) return;
    reviews.set(card.task.task_id, review);
    await load();
  }, true), button("Back", async () => { panel.remove(); }));
  article.querySelector(".review-panel")?.remove(); article.append(panel);
}
const eventNames: Record<string, string> = {
  admitted: "Assignment received", claimed: "Agent started work", completed: "Result ready",
  published: "Result published", paused: "Paused by you", resumed: "Resumed",
  cancelled: "Cancelled", human_pause: "Pause requested", cancel_requested: "Cancellation requested",
  runtime_dispatch_prepared: "Preparing the agent run", runtime_accepted: "Agent run accepted",
};
function historyPanel(card: TaskCard): HTMLElement {
  const panel = element("section", "history-panel");
  panel.append(element("h4", "section-title", "Task progress"));
  const renderEvents = (data: TaskEvents): void => {
    const list = element("ol", "timeline");
    for (const event of data.events) {
      list.append(element("li", undefined, eventNames[event.kind] ?? `Task state updated (revision ${event.state_revision})`));
    }
    panel.replaceChildren(element("h4", "section-title", "Task progress"), list);
  };
  const cached = timelines.get(card.task.task_id);
  if (cached) renderEvents(cached); else panel.append(element("p", "muted", "Loading progress…"));
  const epoch = sessionEpoch;
  if (api) void api.events(card.task.task_id).then((data) => {
    if (epoch !== sessionEpoch || !panel.isConnected) return;
    timelines.set(card.task.task_id, data); renderEvents(data);
  }).catch(() => { if (panel.isConnected) panel.append(notice("Progress could not refresh. Try again when connected.", true)); });
  return panel;
}
function taskCard(card: TaskCard, home: WorkHome): HTMLElement {
  const task = card.task;
  const article = element("article", "task-card"); article.dataset.taskId = task.task_id;
  const heading = element("div", "task-card__heading");
  heading.append(element("h3", "task-card__title", task.brief),
    element("span", `phase phase--${task.phase}`, task.outcome === "cancelled" ? "Cancelled"
      : task.outcome === "failed" ? "Needs a new assignment" : phaseLabel(task.phase)));
  const agent = home.agents.find((item) => item.bot_id === task.bot_id);
  article.append(heading, element("p", "task-card__context", `${agent?.display_name ?? task.bot_id} · ${home.project_name} · Private task`));
  if (task.disable_tools) article.append(element("p", "task-card__context", "Tools disabled for this assignment"));
  const blockers = blockerMessages(card);
  if (blockers.length) {
    const list = element("ul", "blockers"); blockers.forEach((text) => { list.append(element("li", "blockers__item", text)); }); article.append(list);
  }
  if (task.result !== null) {
    article.append(element("pre", "result", task.result));
    const download = button("Download result", async () => {
      if (!api) return;
      const content = await api.resultText(task.task_id);
      const url = URL.createObjectURL(new Blob([content], { type: "text/plain" }));
      const link = element("a"); link.href = url; link.download = "radhouse-result.txt";
      link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    article.append(download);
  }
  if (card.publication) article.append(notice(`Published to ${card.publication.audience.join(", ")}.`));
  if (task.files.length) article.append(element("p", "muted", `Reference files: ${task.files.map((file) => file.name).join(", ")}`));
  if (task.follows_task_id) article.append(element("p", "muted", "Includes the result of your previous assignment."));
  for (const receipt of task.guidance) {
    const status = guidanceStatus(receipt);
    article.append(notice(`${receipt.text ?? `Permission response: ${receipt.choice}`} — ${status}`));
  }
  if (home.role !== "viewer" && task.phase === "active" && task.blockers.length === 0) {
    if (task.permission_request) {
      const permission = element("section", "permission-panel");
      permission.append(element("h4", "section-title", "The agent needs your decision"),
        element("pre", "result", task.permission_request.command),
        element("p", "digest", `Request SHA-256: ${task.permission_request.digest}`));
      const respond = async (choice: "once" | "deny"): Promise<void> => {
        if (!api) return;
        await api.permission(task, choice); await load("Permission response recorded for this run.");
      };
      if (!signedIn || new Date(signedIn.assurance_until).getTime() <= Date.now()) permission.append(assurancePanel());
      else {
        if (task.permission_request.allow_once) permission.append(button("Allow this request once", async () => respond("once")));
        else permission.append(notice("This action is outside the agent’s current grant. An administrator must review access before it can be allowed."));
        permission.append(button("Deny this request", async () => respond("deny")));
      }
      article.append(permission);
    } else if (!task.guidance.some((receipt) => ["submitted", "unknown"].includes(receipt.state))) {
      const guidance = element("form", "guidance-form");
      const label = element("label", "field"); const input = element("textarea", "field__control");
      input.name = `guide-${task.task_id}`; input.maxLength = 4096; input.required = true;
      input.value = guidanceDrafts.get(task.task_id) ?? "";
      input.addEventListener("input", () => guidanceDrafts.set(task.task_id, input.value));
      label.append(element("span", "field__label", "Guide the current assignment"), input);
      const send = element("button", "button button--secondary", "Send guidance"); send.type = "submit";
      guidance.append(label, send);
      guidance.addEventListener("submit", (event) => {
        event.preventDefault(); const current = api; if (!current) return;
        void action(send, async () => { await current.guide(task, input.value); guidanceDrafts.delete(task.task_id); await load(); });
      });
      article.append(guidance);
    }
  }
  const controls = element("div", "task-card__actions");
  controls.append(button(expanded.has(task.task_id) ? "Hide progress" : "Show progress", async () => {
    if (expanded.has(task.task_id)) expanded.delete(task.task_id); else expanded.add(task.task_id);
    await load();
  }));
  if (home.role !== "viewer") {
    for (const [label, verb, availability] of [
      ["Pause", "pause", card.pause], ["Resume", "resume", card.resume], ["Cancel", "cancel", card.cancel],
    ] as const) {
      if ((verb === "pause" && card.resume.enabled) || (verb === "resume" && !card.resume.enabled) || task.phase === "closed") continue;
      const control = button(label, async () => {
        if (!api) return;
        await api.changeState(task.task_id, verb, task.state_revision); await load();
      });
      control.disabled = !availability.enabled;
      const reason = actionReason(availability); if (reason) control.title = reason;
      controls.append(control);
    }
    if (card.review.enabled) controls.append(button("Review result", async () => prepareAudience(article, card), true));
    if (card.review.reason === "fresh_assurance_required") controls.append(button("Confirm sign-in to review", async () => {
      article.querySelector(".review-panel")?.remove(); article.append(assurancePanel());
    }));
    if (task.phase === "closed") controls.append(button("Start a follow-up", async () => {
      clearReviewTarget();
      drafts.set(home.project_id, { bot: task.bot_id, brief: "", files: [], ...(task.result === null ? {} : { followsTaskId: task.task_id }) });
      await load(task.result === null ? "Describe the next assignment." : "The previous result will be included. Describe the next assignment.");
      page.querySelector<HTMLTextAreaElement>('textarea[name="brief"]')?.focus();
      page.querySelector(".start-panel")?.scrollIntoView({ block: "start" });
    }));
  } else article.append(element("p", "muted", "Read-only access"));
  article.append(controls);
  const review = reviews.get(task.task_id);
  if (review && !card.publication && review.digest === task.result_digest && review.state_revision === task.state_revision
    && review.task_revision === task.task_revision && new Date(review.expires_at).getTime() > Date.now()) {
    article.append(reviewPanel(card, review));
  } else if (review) reviews.delete(task.task_id);
  if (expanded.has(task.task_id)) article.append(historyPanel(card));
  return article;
}
function startPanel(home: WorkHome): HTMLElement {
  const panel = element("section", "start-panel");
  panel.append(element("h2", "section-title", "What would you like done?"),
    element("p", "muted", `Working in ${home.project_name}. Your assignment and result stay private until you choose to share.`));
  if (home.role === "viewer") { panel.append(notice("Your access is read-only.")); return panel; }
  const draft = drafts.get(home.project_id) ?? { brief: "", files: [], bot: home.agents.find((a) => a.state === "ready")?.bot_id ?? "" };
  drafts.set(home.project_id, draft);
  const form = element("form", "start-form");
  const label = element("label", "field"); const select = element("select", "field__control"); select.name = "agent";
  for (const agent of home.agents) {
    const option = element("option", undefined, `${agent.display_name} · ${agent.role_name}`);
    option.value = agent.bot_id; option.disabled = agent.state !== "ready"; select.append(option);
  }
  select.value = draft.bot; select.addEventListener("change", () => { draft.bot = select.value; });
  label.append(element("span", "field__label", "Agent"), select);
  const briefLabel = element("label", "field field--wide"); const brief = element("textarea", "field__control");
  brief.name = "brief"; brief.required = true; brief.maxLength = 4096; brief.rows = 3; brief.value = draft.brief;
  brief.placeholder = "Ask a clear question or describe the result you need…";
  brief.addEventListener("input", () => { draft.brief = brief.value; });
  briefLabel.append(element("span", "field__label", "Assignment"), brief);
  const submit = element("button", "button button--primary", "Send assignment"); submit.type = "submit";
  submit.disabled = !home.start.enabled;
  form.append(label, briefLabel, submit);
  const fileLabel = element("label", "field"); const files = element("input", "field__control");
  files.type = "file"; files.multiple = true; files.accept = ".txt,.md,.csv,.json,.log";
  fileLabel.classList.add("field--files");
  fileLabel.append(element("span", "field__label", "Reference files (text, up to 64 KB total)"), files);
  const fileStatus = element("p", "muted file-status", draft.files.map((file) => file.name).join(", "));
  files.addEventListener("click", () => {
    // The native chooser still owns this input while it is open. Invalidate
    // a refresh already in flight, then preserve the form until it closes.
    filePickerOpen = true;
    loadGeneration++;
  });
  files.addEventListener("cancel", () => { filePickerOpen = false; });
  files.addEventListener("change", () => {
    filePickerOpen = false;
    void action(submit, async () => {
      const selected = Array.from(files.files ?? []);
      if (selected.length > 4 || selected.reduce((size, file) => size + file.size, 0) > 65536) {
        throw new ApiError("invalid_input_files", 422);
      }
      const decoder = new TextDecoder("utf-8", { fatal: true });
      const loaded = await Promise.all(selected.map(async (file) => ({ name: file.name, content: decoder.decode(await file.arrayBuffer()) })));
      if (loaded.some((file) => file.content.includes("\0"))) throw new ApiError("invalid_input_files", 422);
      draft.files = loaded; fileStatus.textContent = loaded.map((file) => file.name).join(", ");
    });
  });
  form.insertBefore(fileLabel, submit); form.insertBefore(fileStatus, submit);
  if (draft.followsTaskId) form.insertBefore(notice("The previous result is included as reference material."), submit);
  if (!home.start.enabled) panel.append(notice(actionReason(home.start) ?? "No agent is available."));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const agent = home.agents.find((item) => item.bot_id === select.value && item.state === "ready");
    if (!api || !agent || !brief.value.trim()) return;
    const currentApi = api; const epoch = sessionEpoch;
    void action(submit, async () => {
      await currentApi.start({ botId: agent.bot_id, projectId: home.project_id, brief: brief.value.trim(), providerBinding: agent.provider_binding, files: draft.files, ...(draft.followsTaskId ? { followsTaskId: draft.followsTaskId } : {}) });
      if (epoch !== sessionEpoch) return;
      draft.brief = ""; draft.files = []; delete draft.followsTaskId;
      await load("Assignment received. You can follow its progress below.");
    });
  });
  panel.append(form); return panel;
}
function render(home: WorkHome, message?: string): void {
  const focused = (page.getRootNode() as Document | ShadowRoot).activeElement;
  const focusName = focused instanceof HTMLInputElement || focused instanceof HTMLTextAreaElement || focused instanceof HTMLSelectElement ? focused.name : "";
  const selection = focused instanceof HTMLTextAreaElement ? [focused.selectionStart, focused.selectionEnd] : null;
  page.replaceChildren();
  const header = element("header", "page-header"); const identity = element("div");
  identity.append(element("p", "eyebrow", "Radhouse · A home for your agents"), element("h1", "page-title", reviewTarget ? "Review your work" : "Your work home"));
  const context = element("label", "field project-picker"); const picker = element("select", "field__control"); picker.name = "project";
  for (const project of projects) { const option = element("option", undefined, project.display_name); option.value = project.project_id; picker.append(option); }
  picker.value = home.project_id;
  picker.addEventListener("change", () => {
    clearReviewTarget(); selectedProject = picker.value; sessionEpoch++; reviews.clear(); timelines.clear(); expanded.clear();
    selectedConversation = ""; conversationHistory = null; void load();
  });
  context.append(element("span", "field__label", "Project"), picker); identity.append(context); header.append(identity);
  header.append(button(`Sign out ${signedIn?.username ?? ""}`, async () => { await api?.logout(); loginScreen(); }));
  page.append(header);
  if (message) page.append(notice(message));
  if (reviewTarget) page.append(button("Show all work", async () => { clearReviewTarget(); await load(); }));
  const conversation = conversationLinks.find(link => link.link_id === selectedConversation);
  if (!reviewTarget && conversation && conversationHistory && api && signedIn) {
    const draft = conversationDrafts.get(conversation.link_id) ?? { content: "", reply: null, files: [] };
    conversationDrafts.set(conversation.link_id, draft);
    page.append(conversationPanel(api, conversation, conversationHistory, draft, signedIn.principal_id,
      async () => load(), taskId => {
        const card = Array.from(page.querySelectorAll<HTMLElement>("[data-task-id]")).find(node => node.dataset.taskId === taskId);
        card?.scrollIntoView({ block: "start", behavior: "smooth" });
        card?.querySelector<HTMLButtonElement>("button")?.focus();
      }, action, open => { filePickerOpen = open; if (open) loadGeneration++; }));
  } else if (!reviewTarget) page.append(startPanel(home));
  const roster = element("section", "section"); roster.append(element("h2", "section-title", "Your agents"));
  const grid = element("div", "agent-grid");
  for (const agent of home.agents) {
    const card = element("article", "agent-card"); card.append(element("h3", "agent-card__name", agent.display_name),
      element("p", "agent-card__role", agent.role_name), element("p", "muted", agent.state === "ready" ? "Ready for an assignment" : "Temporarily unavailable"));
    const link = conversationLinks.find(item => item.bot_id === agent.bot_id);
    if (link) card.append(button(`Talk to ${agent.display_name}`, async () => { selectedConversation = link.link_id; await load(); }));
    grid.append(card);
  }
  roster.append(grid); if (!reviewTarget) page.append(roster);
  const work = element("section", "section"); work.append(element("h2", "section-title", "Your work"));
  if (home.tasks.length === 0) work.append(element("p", "empty", "Start with one clear assignment. Its progress and result will appear here."));
  const list = element("div", "task-list");
  for (const card of home.tasks) if (!reviewTarget || card.task.task_id === reviewTarget.task_id) list.append(taskCard(card, home));
  work.append(list); page.append(work);
  const allowed = new Set(home.tasks.map((card) => card.task.task_id));
  for (const id of reviews.keys()) if (!allowed.has(id)) reviews.delete(id);
  for (const id of timelines.keys()) if (!allowed.has(id)) timelines.delete(id);
  if (focusName === "brief" || focusName === "agent" || focusName === "project" || focusName.startsWith("conversation-") || focusName.startsWith("guide-")) {
    const next = Array.from(page.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>("[name]")).find(node => node.name === focusName);
    next?.focus(); if (next instanceof HTMLTextAreaElement && selection) next.setSelectionRange(selection[0] ?? 0, selection[1] ?? 0);
  }
}
async function load(message?: string): Promise<void> {
  if (disposed) return;
  const generation = ++loadGeneration;
  try {
    if (!api) {
      const session = await client.currentSession();
      if (generation !== loadGeneration) return;
      applySession(session);
    }
    const current = api; if (!current) return;
    if (reviewToken && !reviewTarget) {
      const resolved = await current.resolveReview(reviewToken);
      if (generation !== loadGeneration) return;
      reviewTarget = resolved; selectedProject = resolved.project_id;
    }
    const available = await current.projects();
    if (generation !== loadGeneration) return;
    const project = available.find((p) => p.project_id === selectedProject) ?? available[0];
    if (!project) { page.replaceChildren(notice("No active project is assigned. Ask your administrator to provide access.")); return; }
    if (reviewTarget && (project.project_id !== reviewTarget.project_id
        || project.conversation_id !== reviewTarget.conversation_id || project.binding_revision !== reviewTarget.binding_revision)) {
      throw new ApiError("review_link_denied", 403);
    }
    const scoped = current.forProject(project);
    const home = await scoped.home();
    if (generation !== loadGeneration) return;
    const links = reviewTarget ? [] : await scoped.conversations();
    if (generation !== loadGeneration) return;
    const link = links.find(item => item.link_id === selectedConversation) ?? links[0];
    const history = link ? await scoped.conversationHistory(link.link_id, conversationDrafts.get(link.link_id)?.before) : null;
    if (generation !== loadGeneration) return;
    conversationLinks = links; selectedConversation = link?.link_id ?? ""; conversationHistory = history;
    if (reviewTarget && !home.tasks.some(card => card.task.task_id === reviewTarget?.task_id)) throw new ApiError("review_link_denied", 403);
    api = scoped; selectedProject = project.project_id; projects = available; render(home, message);
  } catch (error) {
    if (generation !== loadGeneration) return;
    if (error instanceof ApiError && error.status === 401) loginScreen();
    else if (error instanceof ApiError && error.code === "fresh_assurance_required" && api) {
      page.replaceChildren(notice("Confirm your sign-in to open this exact review."), assurancePanel());
    } else page.replaceChildren(notice(errorMessage(error), true),
      button("Open work home", async () => { clearReviewTarget(); await load(); }), button("Try again", async () => load()));
  }
}
const onReviewLink = () => {
  reviewToken = new URLSearchParams(window.location.hash.slice(1)).get("review");
  reviewTarget = null; reviews.clear(); sessionEpoch++; void load();
};
window.addEventListener("hashchange", onReviewLink);
void load();
const interval = window.setInterval(() => {
  // Temporary assurance/audience forms retain their fields; every submit still
  // performs current server checks. Prepared reviews can refresh normally.
  if (api && !filePickerOpen && actionsInFlight === 0 && page.querySelector(".review-panel form, .audience-choice") === null
      && !Array.from(page.querySelectorAll<HTMLTextAreaElement>(".guidance-form textarea")).some((input) =>
        input.value || input === (page.getRootNode() as Document | ShadowRoot).activeElement)) void load();
}, 10_000);

return () => { disposed = true; window.removeEventListener("hashchange", onReviewLink); loadGeneration++; sessionEpoch++; window.clearInterval(interval); drafts.clear(); reviews.clear(); timelines.clear(); conversationDrafts.clear(); guidanceDrafts.clear(); page.replaceChildren(); };
}
