import { isAgentWorkspaceSnapshot, isDirective, isRecord, isWorkspaceEvent } from "../domain/agentWorkspace";
import type { AgentWorkspaceSnapshot, InteractionDirective, WorkspaceEvent, WorkspaceObservationType } from "../domain/agentWorkspace";
import { identityHeaders } from "./authHeaders";
import type { RequestIdentity } from "./authHeaders";

const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

function headers(identity: RequestIdentity, idempotencyKey?: string): HeadersInit {
  return { Accept: "application/json", "Content-Type": "application/json", ...identityHeaders(identity), ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}) };
}

async function payload(response: Response): Promise<Record<string, unknown>> {
  const value: unknown = await response.json();
  if (!response.ok) throw new Error(`WORKSPACE_HTTP_${response.status}`);
  if (!isRecord(value)) throw new Error("INVALID_WORKSPACE_RESPONSE");
  return value;
}

export const agentWorkspaceClient = {
  async create(sessionId: string, mode: "guest" | "demo" | "authenticated", identity: RequestIdentity): Promise<{ workspace: AgentWorkspaceSnapshot; events_url: string; replayed: boolean }> {
    const response = await fetch(`${baseUrl}/api/v1/agent-workspaces`, { method: "POST", headers: headers(identity), body: JSON.stringify({ session_id: sessionId, mode }) });
    const value = await payload(response);
    if (!isAgentWorkspaceSnapshot(value.workspace) || typeof value.events_url !== "string" || typeof value.replayed !== "boolean") throw new Error("INVALID_WORKSPACE_CREATED");
    return value as unknown as { workspace: AgentWorkspaceSnapshot; events_url: string; replayed: boolean };
  },

  async observe(workspaceId: string, type: WorkspaceObservationType, value: Record<string, unknown>, identity: RequestIdentity): Promise<AgentWorkspaceSnapshot> {
    const observationId = globalThis.crypto.randomUUID();
    const response = await fetch(`${baseUrl}/api/v1/agent-workspaces/${encodeURIComponent(workspaceId)}/observations`, {
      method: "POST", headers: headers(identity, observationId), body: JSON.stringify({ observation_id: observationId, event_type: type, payload: value }),
    });
    const result = await payload(response);
    if (!isAgentWorkspaceSnapshot(result.workspace)) throw new Error("INVALID_WORKSPACE_OBSERVATION");
    return result.workspace;
  },

  async action(workspaceId: string, directiveId: string, action: "ACCEPT" | "DISMISS" | "UNDO", identity: RequestIdentity): Promise<InteractionDirective> {
    const response = await fetch(`${baseUrl}/api/v1/agent-workspaces/${encodeURIComponent(workspaceId)}/directives/${encodeURIComponent(directiveId)}/actions`, {
      method: "POST", headers: headers(identity), body: JSON.stringify({ action }),
    });
    const result = await payload(response);
    if (!isDirective(result.directive)) throw new Error("INVALID_DIRECTIVE_ACTION");
    return result.directive;
  },

  async stream(eventsUrl: string, workspaceId: string, getIdentity: () => RequestIdentity, onEvent: (event: WorkspaceEvent) => void, signal: AbortSignal): Promise<void> {
    let last = 0; let retryDelayMs = 600;
    while (!signal.aborted) {
      try {
        const response = await fetch(`${baseUrl}${eventsUrl}`, { headers: { Accept: "text/event-stream", ...identityHeaders(getIdentity()), ...(last ? { "Last-Event-ID": String(last) } : {}) }, cache: "no-store", signal });
        if (!response.ok || !response.body) throw new Error(`WORKSPACE_STREAM_HTTP_${response.status}`);
        const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
        while (!signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split("\n\n"); buffer = frames.pop() ?? "";
          for (const frame of frames) {
            const line = frame.split("\n").find((item) => item.startsWith("data: "));
            if (!line) continue;
            const event: unknown = JSON.parse(line.slice(6));
            if (!isWorkspaceEvent(event) || event.workspace_id !== workspaceId) throw new Error("INVALID_WORKSPACE_EVENT");
            if (event.sequence > last) { last = event.sequence; onEvent(event); }
          }
        }
        retryDelayMs = 600;
      } catch (error) {
        if (signal.aborted || (error instanceof Error && error.message.startsWith("INVALID_"))) throw error;
        await new Promise((resolve) => globalThis.setTimeout(resolve, retryDelayMs));
        retryDelayMs = Math.min(retryDelayMs * 2, 5_000);
      }
    }
  },
};
