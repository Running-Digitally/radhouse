import type { Envelope } from "./types.js";

/** Retain only request identities, never prompts, results or credentials.
 * A response lost after commit must be retried with the same identity.
 */
export class CommandLedger {
  private readonly pending = new Map<string, Envelope>();

  constructor(private readonly storage: Storage | null = null) {}

  async prepare(scope: string, path: string, body: object, conversation: string, revision: number): Promise<{
    key: string; envelope: Envelope;
  }> {
    const bytes = new TextEncoder().encode(JSON.stringify({ scope, path, body, revision }));
    const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
      .map((item) => item.toString(16).padStart(2, "0")).join("");
    const key = `radhouse:command:${hash}`;
    let envelope = this.pending.get(key);
    if (!envelope) {
      try {
        const stored: unknown = JSON.parse(this.storage?.getItem(key) ?? "null");
        if (stored && typeof stored === "object" && "command_key" in stored && "event_id" in stored
          && typeof stored.command_key === "string" && typeof stored.event_id === "string"
          && /^[0-9a-f-]{36}$/.test(stored.command_key) && /^[0-9a-f-]{36}$/.test(stored.event_id)) {
          envelope = { channel: "radhouse", event_id: stored.event_id, command_key: stored.command_key,
            conversation_id: conversation, binding_revision: revision, mirrored: false };
        }
      } catch { /* In-memory retry protection remains available. */ }
    }
    envelope ??= { channel: "radhouse", event_id: crypto.randomUUID(), command_key: crypto.randomUUID(),
      conversation_id: conversation, binding_revision: revision, mirrored: false };
    this.pending.set(key, envelope);
    try { this.storage?.setItem(key, JSON.stringify({ event_id: envelope.event_id, command_key: envelope.command_key })); }
    catch { /* Storage may be disabled by the browser. */ }
    return { key, envelope };
  }

  complete(key: string): void {
    this.pending.delete(key);
    try { this.storage?.removeItem(key); } catch { /* No private data is persisted. */ }
  }
}
