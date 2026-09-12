import { ApiError, RadhouseApi } from "./api.js";
import type { AuthSession } from "./api.js";
import { actionReason, blockerMessages, phaseLabel } from "./view-model.js";
import type { ActionState, AgentSummary, Review, TaskCard, WorkHome } from "./types.js";

function requiredRoot(): HTMLElement {
  const node = document.querySelector<HTMLElement>("#app");
  if (!node) throw new Error("radhouse_app_root_missing");
  return node;
}

const root = requiredRoot();

let api: RadhouseApi | null = null;
let signedIn: AuthSession | null = null;

function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function setBusy(button: HTMLButtonElement, busy: boolean, busyLabel = "Working…"): void {
  if (busy) button.dataset.previousLabel = button.textContent ?? "";
  button.disabled = busy;
  button.textContent = busy ? busyLabel : button.dataset.previousLabel ?? button.textContent;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const known: Record<string, string> = {
      stale_state: "This task changed. The latest state is loading now.",
      fresh_assurance_required: "Please confirm your sign-in and try again.",
      binding_denied: "This work-home link is no longer current. Open it again from Radhouse.",
      access_denied: "Your access to this project or agent changed.",
      invalid_server_response: "Radhouse returned an unexpected response. No task was submitted.",
      invalid_credentials: "That username, password, or authenticator code was not accepted.",
      authentication_required: "Please sign in to continue.",
      request_origin_denied: "Radhouse rejected this page origin.",
      csrf_denied: "Your session changed. Sign in again before retrying.",
    };
    return known[error.code] ?? `Radhouse could not complete that action (${error.code}).`;
  }
  return "Radhouse could not reach the control service. Your task was not resubmitted.";
}

function useSession(session: AuthSession): void {
  signedIn = session;
  api = new RadhouseApi(
    session.conversation_id, session.binding_revision, session.csrf_token,
  );
}

function loginScreen(message?: string): void {
  api = null;
  signedIn = null;
  root.replaceChildren();
  const card = element("section", "login-card");
  card.append(
    element("p", "eyebrow", "Radhouse · A home for your agents"),
    element("h1", "page-title", "Welcome home"),
    element("p", "muted", "Sign in with your local Radhouse account."),
  );
  if (message) card.append(statusBanner(message, "error"));
  const form = element("form", "login-form");
  const fields: Array<[string, string, string, string]> = [
    ["username", "Username", "text", "username"],
    ["password", "Password", "password", "current-password"],
    ["totp", "Authenticator code", "text", "one-time-code"],
  ];
  const inputs = new Map<string, HTMLInputElement>();
  for (const [name, label, type, autocomplete] of fields) {
    const wrapper = element("label", "field field--wide");
    wrapper.append(element("span", "field__label", label));
    const input = element("input", "field__control");
    input.name = name;
    input.type = type;
    input.setAttribute("autocomplete", autocomplete);
    input.required = true;
    if (name === "totp") {
      input.inputMode = "numeric";
      input.pattern = "[0-9]{6}";
      input.maxLength = 6;
    }
    inputs.set(name, input);
    wrapper.append(input);
    form.append(wrapper);
  }
  const submit = element("button", "button button--primary", "Sign in");
  submit.type = "submit";
  form.append(submit);
  form.addEventListener("submit", (event) => void (async () => {
    event.preventDefault();
    setBusy(submit, true, "Signing in…");
    try {
      const session = await RadhouseApi.login(
        inputs.get("username")?.value ?? "",
        inputs.get("password")?.value ?? "",
        inputs.get("totp")?.value ?? "",
      );
      useSession(session);
      await load();
    } catch (error) {
      loginScreen(errorMessage(error));
    }
  })());
  card.append(form);
  root.append(card);
}

function statusBanner(message: string, tone: "info" | "error" = "info"): HTMLElement {
  const banner = element("div", `notice notice--${tone}`, message);
  banner.setAttribute("role", tone === "error" ? "alert" : "status");
  return banner;
}

function actionButton(
  label: string,
  state: ActionState,
  onClick: (button: HTMLButtonElement) => Promise<void>,
): HTMLButtonElement {
  const button = element("button", "button button--secondary", label);
  button.type = "button";
  button.disabled = !state.enabled;
  const reason = actionReason(state);
  if (reason) button.title = reason;
  button.addEventListener("click", () => void onClick(button));
  return button;
}

async function runAction(
  task: TaskCard,
  action: "cancel" | "pause" | "resume",
  button: HTMLButtonElement,
): Promise<void> {
  if (!api) return;
  setBusy(button, true);
  try {
    await api.changeState(task.task.task_id, action, task.task.state_revision);
    await load();
  } catch (error) {
    root.prepend(statusBanner(errorMessage(error), "error"));
    setBusy(button, false);
  }
}

function reviewPanel(task: TaskCard, review: Review): HTMLElement {
  const panel = element("section", "review-panel");
  panel.append(
    element("h4", "review-panel__title", "Confirm this exact result"),
    element("p", "muted", `Audience: ${review.audience.join(", ")} · Expires ${new Date(review.expires_at).toLocaleTimeString()}`),
  );
  const result = element("pre", "result", task.task.result ?? "");
  const publish = element("button", "button button--primary", "Approve and publish");
  publish.type = "button";
  publish.addEventListener("click", () => void (async () => {
    if (!api || task.task.result === null) return;
    setBusy(publish, true, "Publishing…");
    try {
      await api.publish(review, task.task.result);
      await load("Result published to the reviewed audience.");
    } catch (error) {
      panel.prepend(statusBanner(errorMessage(error), "error"));
      setBusy(publish, false);
    }
  })());
  panel.append(result, publish);
  return panel;
}

function taskCard(card: TaskCard, home: WorkHome): HTMLElement {
  const task = card.task;
  const article = element("article", "task-card");
  const heading = element("div", "task-card__heading");
  const title = element("h3", "task-card__title", task.brief);
  const phase = element("span", `phase phase--${task.phase}`, phaseLabel(task.phase));
  heading.append(title, phase);
  const context = element(
    "p", "task-card__context",
    `Agent ${task.bot_id} · Model service ${task.provider_binding}${task.model_id ? ` · Serving ${task.model_id}` : ""}`,
  );
  article.append(heading, context);

  const messages = blockerMessages(card);
  if (messages.length) {
    const list = element("ul", "blockers");
    for (const message of messages) list.append(element("li", "blockers__item", message));
    article.append(list);
  }
  if (task.result !== null) {
    article.append(element("pre", "result", task.result));
  }
  if (home.role === "viewer") {
    article.append(element("p", "muted", "Read-only access"));
    return article;
  }

  const actions = element("div", "task-card__actions");
  if (card.resume.enabled) {
    actions.append(actionButton("Resume", card.resume, (button) => runAction(card, "resume", button)));
  } else if (task.phase !== "closed") {
    actions.append(actionButton("Pause", card.pause, (button) => runAction(card, "pause", button)));
  }
  if (task.phase !== "closed") {
    actions.append(actionButton("Cancel", card.cancel, (button) => runAction(card, "cancel", button)));
  }
  if (task.result !== null) {
    const review = actionButton("Review result", card.review, async (button) => {
      if (!api) return;
      setBusy(button, true, "Preparing review…");
      try {
        const prepared = await api.prepareReview(task, [home.principal_id]);
        article.append(reviewPanel(card, prepared));
        actions.remove();
      } catch (error) {
        article.prepend(statusBanner(errorMessage(error), "error"));
        setBusy(button, false);
      }
    });
    actions.append(review);
  }
  if (actions.childElementCount) article.append(actions);
  return article;
}

function agentOption(agent: AgentSummary): HTMLOptionElement {
  const option = element("option");
  option.value = agent.bot_id;
  option.textContent = `${agent.display_name} · ${agent.role_name}`;
  option.dataset.providerBinding = agent.provider_binding;
  return option;
}

function startPanel(home: WorkHome): HTMLElement {
  const section = element("section", "start-panel");
  section.append(element("h2", "section-title", "What would you like done?"));
  if (!home.start.enabled) {
    section.append(statusBanner(actionReason(home.start) ?? "Starting work is unavailable."));
    return section;
  }
  const form = element("form", "start-form");
  const selectLabel = element("label", "field");
  selectLabel.append(element("span", "field__label", "Agent"));
  const select = element("select", "field__control");
  select.name = "agent";
  for (const agent of home.agents) select.append(agentOption(agent));
  selectLabel.append(select);
  const briefLabel = element("label", "field field--wide");
  briefLabel.append(element("span", "field__label", "Assignment"));
  const brief = element("textarea", "field__control");
  brief.name = "brief";
  brief.required = true;
  brief.maxLength = 4096;
  brief.rows = 3;
  brief.placeholder = "Research a question, review a repository, or prepare a useful brief…";
  briefLabel.append(brief);
  const submit = element("button", "button button--primary", "Start task");
  submit.type = "submit";
  form.append(selectLabel, briefLabel, submit);
  form.addEventListener("submit", (event) => void (async () => {
    event.preventDefault();
    if (!api || !brief.value.trim()) return;
    const selected = select.selectedOptions[0];
    if (!selected) return;
    setBusy(submit, true, "Starting…");
    try {
      await api.start({
        botId: selected.value,
        projectId: home.project_id,
        brief: brief.value.trim(),
        providerBinding: selected.dataset.providerBinding ?? "",
      });
      await load("Task added. Your agent will pick it up shortly.");
    } catch (error) {
      section.prepend(statusBanner(errorMessage(error), "error"));
      setBusy(submit, false);
    }
  })());
  section.append(form);
  return section;
}

function render(home: WorkHome, message?: string): void {
  root.replaceChildren();
  const header = element("header", "page-header");
  const identity = element("div");
  identity.append(
    element("p", "eyebrow", "Radhouse · A home for your agents"),
    element("h1", "page-title", "Your work home"),
    element("p", "muted", `${home.project_name} · ${home.role}`),
  );
  header.append(identity);
  if (api && signedIn) {
    const signOut = element(
      "button", "button button--secondary", `Sign out ${signedIn.username}`,
    );
    signOut.type = "button";
    signOut.addEventListener("click", () => void (async () => {
      try { await api?.logout(); } finally { loginScreen(); }
    })());
    header.append(signOut);
  }
  root.append(header);
  if (message) root.append(statusBanner(message));
  root.append(startPanel(home));

  const roster = element("section", "section");
  roster.append(element("h2", "section-title", "Your agents"));
  const agentGrid = element("div", "agent-grid");
  for (const agent of home.agents) {
    const card = element("article", "agent-card");
    card.append(
      element("h3", "agent-card__name", agent.display_name),
      element("p", "agent-card__role", agent.role_name),
      element("p", "muted", `${agent.state} · ${agent.provider_binding}`),
    );
    agentGrid.append(card);
  }
  roster.append(agentGrid);
  root.append(roster);

  const work = element("section", "section");
  work.append(element("h2", "section-title", "Current work"));
  if (home.tasks.length === 0) {
    work.append(element("p", "empty", "No tasks here yet. Start with one clear assignment."));
  } else {
    const list = element("div", "task-list");
    for (const card of home.tasks) list.append(taskCard(card, home));
    work.append(list);
  }
  root.append(work);
}

async function load(message?: string): Promise<void> {
  if (!api) {
    try {
      useSession(await RadhouseApi.currentSession());
    } catch (error) {
      loginScreen(error instanceof ApiError && error.status !== 401 ? errorMessage(error) : undefined);
      return;
    }
  }
  const currentApi = api;
  if (!currentApi) return;
  try {
    render(await currentApi.home(), message);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) loginScreen();
    else root.replaceChildren(statusBanner(errorMessage(error), "error"));
  }
}

void load();
window.setInterval(() => {
  const active = document.activeElement;
  const editing = active instanceof HTMLInputElement
    || active instanceof HTMLTextAreaElement
    || active instanceof HTMLSelectElement;
  if (!editing && root.querySelector(".review-panel") === null) void load();
}, 10_000);
