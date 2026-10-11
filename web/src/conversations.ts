import type { RadhouseApi } from "./api.js";
import { attachmentPicker } from "./files.js";
import type { AttachedFile } from "./files.js";

export interface ConversationLink {
  link_id: string;
  bot_id: string;
  display_name: string;
  channel_id: string;
  error_code: string | null;
}
export interface ConversationMessage {
  message_id: string;
  author: string;
  content: string;
  source: string;
  state: string;
  task_id: string | null;
  created_at: number;
  sequence: number;
  files: AttachedFile[];
}
export interface ConversationHistory {
  messages: ConversationMessage[];
  cursor: number;
  error_code: string | null;
}
export interface ConversationDraft {
  content: string;
  reply: ConversationMessage | null;
  files: AttachedFile[];
  before?: number;
  scroll?: number;
  atBottom?: boolean;
}

function node<K extends keyof HTMLElementTagNameMap>(tag: K, className: string, text?: string): HTMLElementTagNameMap[K] {
  const result = document.createElement(tag);
  result.className = className;
  if (text !== undefined) result.textContent = text;
  return result;
}

/** Shared owner conversation; all content is text, never executable markup. */
export function conversationPanel(api: RadhouseApi, link: ConversationLink, history: ConversationHistory,
  draft: ConversationDraft, owner: string, refresh: () => Promise<void>, review: (taskId: string) => void,
  run: (button: HTMLButtonElement, work: () => Promise<void>) => Promise<void>,
  filePicker: (open: boolean) => void, canWrite = true): HTMLElement {
  const panel = node("section", "conversation-panel");
  panel.dataset.conversationId = link.link_id;
  const heading = node("div", "conversation-heading");
  heading.append(node("span", "agent-avatar", link.display_name.slice(0, 1)),
    node("h2", "section-title", link.display_name), node("span", "muted", "Your conversation · also in Buzz"));
  panel.append(heading);
  const contextHelp = node("p", "notice",
    "New tasks continue this agent thread. Start fresh thread begins without its prior transcript. Earlier messages and task results stay here; replying to an earlier task returns to its thread. Saved memory and permissions are unchanged.");
  contextHelp.setAttribute("role", "note");
  panel.append(contextHelp);
  if (history.error_code) {
    const hold = node("p", "notice notice--error", "Buzz delivery needs attention. Your conversation is saved here; replies may be delayed.");
    hold.setAttribute("role", "status"); panel.append(hold);
  }
  const historyControls = node("div", "conversation-history-controls");
  if (history.messages.length === 100) {
    const older = node("button", "button button--secondary", "Earlier messages"); older.type = "button";
    older.onclick = () => void run(older, async () => { const first = history.messages[0]; if (first) draft.before = first.sequence; await refresh(); });
    historyControls.append(older);
  }
  if (draft.before !== undefined) {
    const latest = node("button", "button button--secondary", "Latest messages"); latest.type = "button";
    latest.onclick = () => void run(latest, async () => { delete draft.before; await refresh(); });
    historyControls.append(latest);
  }
  panel.append(historyControls);
  const list = node("div", "conversation-messages");
  list.setAttribute("role", "log"); list.setAttribute("aria-label", `Conversation with ${link.display_name}`);
  list.onscroll = () => { draft.scroll = list.scrollTop; draft.atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40; };
  queueMicrotask(() => { if (list.isConnected) list.scrollTop = draft.atBottom !== false ? list.scrollHeight : (draft.scroll ?? 0); });
  if (!history.messages.length) list.append(node("p", "empty", "Ask Researcher a question or give it an assignment. Its progress and result will stay in this conversation."));
  for (const message of history.messages) {
    const own = message.author === owner;
    const item = node("article", `conversation-message${own ? " conversation-message--own" : ""}${message.state === "fresh_context" ? " conversation-message--context-boundary" : ""}`);
    item.append(node("p", "message-author", own ? `You · ${message.source === "buzz" ? "Buzz" : "Radhouse"}` : link.display_name),
      node("p", "message-content", message.content));
    for (const [index, file] of message.files.entries()) {
      const details = node("details", "message-reference");
      details.dataset.viewKey = `${message.message_id}:file:${index}`;
      details.append(node("summary", "", file.name));
      if (file.encoding === "base64" && file.media_type.startsWith("image/")) {
        const image = node("img", "message-reference__image");
        image.src = `data:${file.media_type};base64,${file.content}`;
        image.alt = file.name; image.loading = "lazy";
        details.append(image);
      } else {
        details.append(node("pre", "message-content", file.content));
      }
      item.append(details);
    }
    const controls = node("div", "message-controls");
    const time = node("time", "muted", new Date(message.created_at * 1000).toLocaleString());
    time.dateTime = new Date(message.created_at * 1000).toISOString(); controls.append(time);
    if (message.task_id) {
      const reply = node("button", "button button--secondary", "Reply"); reply.type = "button";
      reply.onclick = () => { draft.reply = message; clearReply.hidden = false; replyLabel.textContent = `Replying to: ${message.content.slice(0, 100)}`; composer.focus(); };
      const details = node("button", "button button--secondary", message.state === "result" ? "Review result" : "Task details"); details.type = "button";
      details.onclick = () => { if (message.task_id) review(message.task_id); };
      if (canWrite) controls.append(reply);
      controls.append(details);
    }
    item.append(controls); list.append(item);
  }
  panel.append(list);
  if (!canWrite) {
    panel.append(node("p", "notice", "Your access is read-only. You can read this conversation and its shared results."));
    return panel;
  }
  const form = node("form", "conversation-compose");
  const replyLabel = node("p", "muted", draft.reply ? `Replying to: ${draft.reply.content.slice(0, 100)}` : "");
  const clearReply = node("button", "button button--secondary", "Clear reply"); clearReply.type = "button";
  clearReply.hidden = draft.reply === null;
  clearReply.onclick = () => { draft.reply = null; replyLabel.textContent = ""; clearReply.hidden = true; };
  const label = node("label", "field");
  const composer = node("textarea", "field__control"); composer.name = `conversation-${link.link_id}`;
  composer.rows = 3; composer.required = true; composer.maxLength = 4096; composer.value = draft.content;
  composer.placeholder = `Message ${link.display_name}…`; composer.oninput = () => { draft.content = composer.value; };
  label.append(node("span", "field__label", `Message ${link.display_name}`), composer);
  const submit = node("button", "button button--primary", "Send message"); submit.type = "submit";
  const fresh = node("button", "button button--secondary", "Start fresh thread"); fresh.type = "button";
  fresh.setAttribute("aria-label", "Start fresh thread");
  fresh.onclick = () => void run(fresh, async () => {
    await api.sendMessage(link.link_id, "Start fresh thread", null, []);
    draft.reply = null;
    delete draft.before;
    await refresh();
  });
  const attachments = attachmentPicker(composer, draft, work => run(submit, work), filePicker);
  form.append(replyLabel, clearReply, label, attachments, submit, fresh);
  form.onsubmit = event => {
    event.preventDefault(); if (!draft.content.trim()) return;
    void run(submit, async () => {
      await api.sendMessage(link.link_id, draft.content, draft.reply?.message_id ?? null, draft.files);
      draft.content = ""; draft.reply = null; draft.files = []; delete draft.before;
      await refresh();
    });
  };
  panel.append(form);
  return panel;
}
