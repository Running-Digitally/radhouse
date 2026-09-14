import type { Project, Review, TaskEvents, TaskSummary, WorkHome } from "./types.js";
import { parseWorkHome } from "./contract.js";
import { CommandLedger } from "./commands.js";
import type { ConversationLink, ConversationHistory, ConversationMessage } from "./conversations.js";

export interface AuthSession {
  principal_id: string;
  username: string;
  assurance_until: string;
  conversation_id: string;
  binding_revision: number;
  project_id: string;
  csrf_token: string;
}

export type Transport = (path: string, init: RequestInit) => Promise<Response>;
const browserTransport: Transport = (path, init) => fetch(path, { ...init,
  credentials: "same-origin", redirect: "error", signal: AbortSignal.timeout(20_000) });

export function operatorClient(transport: Transport = browserTransport) {
  return {
    currentSession: () => authRequest<AuthSession>("/auth/session", {}, transport),
    login: (username: string, password: string, totpCode: string) => authRequest<AuthSession>("/auth/login", {
      method: "POST", body: JSON.stringify({ username, password, totp_code: totpCode }),
      headers: { "Content-Type": "application/json" },
    }, transport),
    fromSession: (session: AuthSession) => new RadhouseApi(session.conversation_id, session.binding_revision,
      session.csrf_token, undefined, transport),
  };
}

export class ApiError extends Error {
  constructor(public readonly code: string, public readonly status: number) {
    super(code);
  }
}

export class RadhouseApi {
  private readonly commands: CommandLedger;
  constructor(
    private readonly conversationId: string,
    private readonly bindingRevision: number,
    private readonly csrfToken: string,
    commands?: CommandLedger,
    private readonly transport: Transport = browserTransport,
  ) {
    let storage: Storage | null = null;
    try { storage = globalThis.sessionStorage ?? null; } catch { /* Browser policy. */ }
    this.commands = commands ?? new CommandLedger(storage);
  }

  forProject(project: Project): RadhouseApi {
    return new RadhouseApi(project.conversation_id, project.binding_revision, this.csrfToken, this.commands, this.transport);
  }

  async projects(): Promise<Project[]> {
    const value = await this.request<unknown>("/projects");
    if (!Array.isArray(value) || value.length > 100 || value.some((item) =>
      typeof item !== "object" || item === null || typeof item.project_id !== "string"
      || typeof item.display_name !== "string" || typeof item.conversation_id !== "string"
      || !Number.isSafeInteger(item.binding_revision) || item.binding_revision < 1)) {
      throw new ApiError("invalid_server_response", 502);
    }
    return value as Project[];
  }

  async reauthenticate(password: string, totpCode: string): Promise<AuthSession> {
    return this.request<AuthSession>("/auth/reauthenticate", {
      method: "POST", body: JSON.stringify({ password, totp_code: totpCode }),
    });
  }

  static async currentSession(): Promise<AuthSession> {
    return authRequest<AuthSession>("/auth/session");
  }

  static async login(username: string, password: string, totpCode: string): Promise<AuthSession> {
    return authRequest<AuthSession>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password, totp_code: totpCode }),
      headers: { "Content-Type": "application/json" },
    });
  }

  async logout(): Promise<void> {
    await authRequest<void>("/auth/logout", {
      method: "POST",
      headers: { "X-Radhouse-CSRF": this.csrfToken },
    }, this.transport);
  }

  private query(): string {
    return new URLSearchParams({ conversation_id: this.conversationId,
      binding_revision: String(this.bindingRevision) }).toString();
  }

  private async command<T>(path: string, body: object): Promise<T> {
    const prepared = await this.commands.prepare(this.conversationId, path, body,
      this.conversationId, this.bindingRevision);
    const response = await this.request<T>(path, { method: "POST",
      body: JSON.stringify({ ...body, envelope: { ...prepared.envelope, channel: "radhouse" } }) });
    this.commands.complete(prepared.key);
    return response;
  }

  async home(): Promise<WorkHome> {
    const query = new URLSearchParams({
      conversation_id: this.conversationId,
      binding_revision: String(this.bindingRevision),
    });
    const response = await this.request<unknown>(`/work-home?${query}`);
    try {
      return parseWorkHome(response);
    } catch {
      throw new ApiError("invalid_server_response", 502);
    }
  }

  async conversations(): Promise<ConversationLink[]> {
    return this.request(`/conversations?${this.query()}`);
  }

  async resolveReview(locator: string): Promise<{ task_id: string; project_id: string; conversation_id: string; binding_revision: number }> {
    const value = await this.request<{ task_id: string; project_id: string; conversation_id: string; binding_revision: number }>("/reviews/resolve", {
      method: "POST", body: JSON.stringify({ locator }),
    });
    if (!value || !/^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value.task_id)
        || typeof value.project_id !== "string" || typeof value.conversation_id !== "string"
        || !Number.isSafeInteger(value.binding_revision) || value.binding_revision < 1) {
      throw new ApiError("invalid_server_response", 502);
    }
    return value;
  }

  async conversationHistory(linkId: string, before?: number): Promise<ConversationHistory> {
    const page = before === undefined ? "tail=true" : `before=${before}`;
    return this.request(`/conversations/${encodeURIComponent(linkId)}/messages?${this.query()}&${page}`);
  }

  async sendMessage(linkId: string, content: string, replyTo: string | null,
    files: { name: string; content: string }[]): Promise<ConversationMessage> {
    return this.command(`/conversations/${encodeURIComponent(linkId)}/messages`, {
      content, reply_to: replyTo, files,
    });
  }

  async start(input: {
    botId: string;
    projectId: string;
    brief: string;
    providerBinding: string;
    files?: { name: string; content: string }[];
    followsTaskId?: string;
  }): Promise<TaskSummary> {
    return this.command<TaskSummary>("/tasks", {
        start: {
          bot_id: input.botId,
          project_id: input.projectId,
          brief: input.brief,
          provider_binding: input.providerBinding,
          resource_key: null,
          budget: 3,
          files: input.files ?? [],
          follows_task_id: input.followsTaskId ?? null,
        },
    });
  }

  async changeState(
    taskId: string,
    action: "cancel" | "pause" | "resume",
    expectedRevision: number,
  ): Promise<TaskSummary> {
    return this.command<TaskSummary>(`/tasks/${encodeURIComponent(taskId)}/${action}`, {
        expected_state_revision: expectedRevision,
    });
  }

  async prepareReview(task: TaskSummary, audience: string[]): Promise<Review> {
    return this.command<Review>(`/tasks/${encodeURIComponent(task.task_id)}/review`, {
        expected_state_revision: task.state_revision,
        audience,
        ttl_seconds: 300,
    });
  }

  async publish(review: Review, content: string): Promise<void> {
    await this.command(`/reviews/${encodeURIComponent(review.review_id)}/publish`, {
        expected_revision: review.revision,
        content,
        audience: review.audience,
    });
  }

  async reviewAudience(taskId: string): Promise<string[]> {
    const value = await this.request<unknown>(`/tasks/${encodeURIComponent(taskId)}/review-audience?${this.query()}`);
    if (!Array.isArray(value) || value.length > 100 || value.some((item) => typeof item !== "string")) {
      throw new ApiError("invalid_server_response", 502);
    }
    return value as string[];
  }

  async events(taskId: string): Promise<TaskEvents> {
    return this.request<TaskEvents>(`/tasks/${encodeURIComponent(taskId)}/events?${this.query()}`);
  }

  async guide(task: TaskSummary, text: string): Promise<TaskSummary> {
    return this.command(`/tasks/${encodeURIComponent(task.task_id)}/guidance`, { expected_state_revision: task.state_revision, text });
  }

  async permission(task: TaskSummary, choice: "once" | "deny"): Promise<TaskSummary> {
    const permission = task.permission_request;
    if (!permission) throw new ApiError("permission_changed", 409);
    return this.command(`/tasks/${encodeURIComponent(task.task_id)}/permission`, {
      expected_state_revision: task.state_revision, request_id: permission.request_id, digest: permission.digest, choice,
    });
  }

  async resultText(taskId: string): Promise<string> {
    const response = await this.transport(this.resultUrl(taskId), {});
    if (!response.ok) throw new ApiError("result_unavailable", response.status);
    return response.text();
  }

  resultUrl(taskId: string): string {
    return `/tasks/${encodeURIComponent(taskId)}/result?${this.query()}`;
  }

  private async request<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    if (init.body !== undefined) headers.set("Content-Type", "application/json");
    if (init.method && init.method !== "GET" && init.method !== "HEAD") {
      headers.set("X-Radhouse-CSRF", this.csrfToken);
    }
    const response = await this.transport(path, {
      ...init,
      credentials: "same-origin",
      redirect: "error",
      signal: AbortSignal.timeout(20_000),
      headers,
    });
    if (!response.ok) {
      let code = "request_failed";
      try {
        const body = await response.json() as { code?: unknown };
        if (typeof body.code === "string") code = body.code;
      } catch {
        // The server's bounded status remains useful without exposing a raw body.
      }
      throw new ApiError(code, response.status);
    }
    return await response.json() as T;
  }
}

async function authRequest<T>(path: string, init: RequestInit = {}, transport: Transport = browserTransport): Promise<T> {
  const response = await transport(path, {
    ...init,
    credentials: "same-origin",
    redirect: "error",
    signal: AbortSignal.timeout(20_000),
  });
  if (!response.ok) {
    let code = response.status === 401 ? "authentication_required" : "request_failed";
    try {
      const body = await response.json() as { code?: unknown };
      if (typeof body.code === "string") code = body.code;
    } catch {
      // Return only a bounded application code.
    }
    throw new ApiError(code, response.status);
  }
  if (response.status === 204) return undefined as T;
  return await response.json() as T;
}
