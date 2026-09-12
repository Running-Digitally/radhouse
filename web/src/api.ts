import type { Envelope, Review, TaskSummary, WorkHome } from "./types.js";
import { parseWorkHome } from "./contract.js";

export interface AuthSession {
  principal_id: string;
  username: string;
  assurance_until: string;
  conversation_id: string;
  binding_revision: number;
  project_id: string;
  csrf_token: string;
}

export class ApiError extends Error {
  constructor(public readonly code: string, public readonly status: number) {
    super(code);
  }
}

export class RadhouseApi {
  constructor(
    private readonly conversationId: string,
    private readonly bindingRevision: number,
    private readonly csrfToken: string,
  ) {}

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
    });
  }

  private envelope(): Envelope {
    return {
      channel: "radhouse",
      event_id: crypto.randomUUID(),
      conversation_id: this.conversationId,
      binding_revision: this.bindingRevision,
      command_key: crypto.randomUUID(),
      mirrored: false,
    };
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

  async start(input: {
    botId: string;
    projectId: string;
    brief: string;
    providerBinding: string;
  }): Promise<TaskSummary> {
    return this.request<TaskSummary>("/tasks", {
      method: "POST",
      body: JSON.stringify({
        envelope: this.envelope(),
        start: {
          bot_id: input.botId,
          project_id: input.projectId,
          brief: input.brief,
          provider_binding: input.providerBinding,
          resource_key: null,
          budget: 3,
        },
      }),
    });
  }

  async changeState(
    taskId: string,
    action: "cancel" | "pause" | "resume",
    expectedRevision: number,
  ): Promise<TaskSummary> {
    return this.request<TaskSummary>(`/tasks/${encodeURIComponent(taskId)}/${action}`, {
      method: "POST",
      body: JSON.stringify({
        envelope: this.envelope(),
        expected_state_revision: expectedRevision,
      }),
    });
  }

  async prepareReview(task: TaskSummary, audience: string[]): Promise<Review> {
    return this.request<Review>(`/tasks/${encodeURIComponent(task.task_id)}/review`, {
      method: "POST",
      body: JSON.stringify({
        envelope: this.envelope(),
        expected_state_revision: task.state_revision,
        audience,
        ttl_seconds: 300,
      }),
    });
  }

  async publish(review: Review, content: string): Promise<void> {
    await this.request(`/reviews/${encodeURIComponent(review.review_id)}/publish`, {
      method: "POST",
      body: JSON.stringify({
        envelope: this.envelope(),
        expected_revision: review.revision,
        content,
        audience: review.audience,
      }),
    });
  }

  private async request<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    if (init.body !== undefined) headers.set("Content-Type", "application/json");
    if (init.method && init.method !== "GET" && init.method !== "HEAD") {
      headers.set("X-Radhouse-CSRF", this.csrfToken);
    }
    const response = await fetch(path, {
      ...init,
      credentials: "same-origin",
      redirect: "error",
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

async function authRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    redirect: "error",
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
