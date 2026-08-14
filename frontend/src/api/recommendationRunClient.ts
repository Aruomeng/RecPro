import { isRecommendationExecution } from "../domain/recommendation";
import type { RecommendationExecution, RecommendationRequest } from "../domain/recommendation";

const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export interface RunAccepted {
  task_id: string;
  trace_id: string;
  context_version: number;
  status: string;
  events_url: string;
  replayed: boolean;
}

export interface AgentProgressEvent {
  schema_version: "agent-progress-v1";
  sequence: number;
  event_type: "TASK_ACCEPTED" | "STATE_CHANGED" | "AGENT_STARTED" | "AGENT_COMPLETED" | "TASK_COMPLETED" | "TASK_FAILED";
  task_id: string;
  trace_id: string;
  occurred_at: string;
  status?: string;
  agent_name?: string;
  agent_version?: string;
  message_type?: string;
  outcome?: string;
  action?: string;
  target?: string;
  reason_code?: string;
  confidence?: number;
  duration_ms?: number;
  fallback_used?: boolean;
  error_code?: string;
}

async function jsonResponse(response: Response): Promise<Record<string, unknown>> {
  const value: unknown = await response.json();
  if (!response.ok) throw new Error(`RUN_HTTP_${response.status}`);
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error("INVALID_RUN_RESPONSE");
  return value as Record<string, unknown>;
}

function headers(userId: number, idempotencyKey?: string): HeadersInit {
  return {
    Accept: "application/json",
    "Content-Type": "application/json",
    "X-Demo-User-Id": String(userId),
    ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
  };
}

function accepted(value: Record<string, unknown>): RunAccepted {
  if (typeof value.task_id !== "string" || typeof value.trace_id !== "string" || typeof value.events_url !== "string" ||
      typeof value.context_version !== "number" || typeof value.status !== "string" || typeof value.replayed !== "boolean") {
    throw new Error("INVALID_RUN_ACCEPTED");
  }
  return value as unknown as RunAccepted;
}

export const recommendationRunClient = {
  async create(request: RecommendationRequest, userId: number, signal?: AbortSignal): Promise<RunAccepted> {
    const response = await fetch(`${baseUrl}/api/v1/recommendation-runs`, {
      method: "POST", headers: headers(userId, request.request_id), body: JSON.stringify(request), signal,
    });
    return accepted(await jsonResponse(response));
  },

  async clarify(taskId: string, contextVersion: number, answers: Record<string, string>, idempotencyKey: string, userId: number): Promise<RunAccepted> {
    const response = await fetch(`${baseUrl}/api/v1/recommendation-runs/${encodeURIComponent(taskId)}/clarifications`, {
      method: "POST", headers: headers(userId, idempotencyKey), body: JSON.stringify({ context_version: contextVersion, answers }),
    });
    return accepted(await jsonResponse(response));
  },

  async state(taskId: string, userId: number): Promise<{ terminal: boolean; status: string; result?: RecommendationExecution; error_code?: string }> {
    const response = await fetch(`${baseUrl}/api/v1/recommendation-runs/${encodeURIComponent(taskId)}`, { headers: headers(userId), cache: "no-store" });
    const payload = await jsonResponse(response);
    const result = payload.result;
    if (result !== null && result !== undefined && !isRecommendationExecution(result)) throw new Error("INVALID_RUN_RESULT");
    if (typeof payload.terminal !== "boolean" || typeof payload.status !== "string") throw new Error("INVALID_RUN_STATE");
    return payload as unknown as { terminal: boolean; status: string; result?: RecommendationExecution; error_code?: string };
  },

  async stream(run: RunAccepted, userId: number, onEvent: (event: AgentProgressEvent) => void, signal?: AbortSignal): Promise<void> {
    let lastSequence = 0;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        const response = await fetch(`${baseUrl}${run.events_url}`, {
          headers: { Accept: "text/event-stream", "X-Demo-User-Id": String(userId), ...(lastSequence ? { "Last-Event-ID": String(lastSequence) } : {}) }, cache: "no-store", signal,
        });
        if (!response.ok || !response.body) throw new Error(`RUN_STREAM_HTTP_${response.status}`);
        const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) return;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split("\n\n"); buffer = frames.pop() ?? "";
          for (const frame of frames) {
            const line = frame.split("\n").find((part) => part.startsWith("data: "));
            if (!line) continue;
            const event: unknown = JSON.parse(line.slice(6));
            if (!validAgentEvent(event) || event.task_id !== run.task_id || event.trace_id !== run.trace_id) throw new Error("INVALID_AGENT_EVENT");
            if (event.sequence > lastSequence) { lastSequence = event.sequence; onEvent(event); }
          }
        }
      } catch (error) {
        if (signal?.aborted || attempt === 2 || (error instanceof Error && error.message.startsWith("INVALID_"))) throw error;
        await new Promise((resolve) => globalThis.setTimeout(resolve, 350 * (attempt + 1)));
      }
    }
  },
};

function validAgentEvent(value: unknown): value is AgentProgressEvent {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const event = value as Record<string, unknown>;
  const types = ["TASK_ACCEPTED", "STATE_CHANGED", "AGENT_STARTED", "AGENT_COMPLETED", "TASK_COMPLETED", "TASK_FAILED"];
  return event.schema_version === "agent-progress-v1" && typeof event.sequence === "number" && Number.isInteger(event.sequence) && event.sequence >= 1 &&
    typeof event.event_type === "string" && types.includes(event.event_type) && typeof event.task_id === "string" && typeof event.trace_id === "string" && typeof event.occurred_at === "string" &&
    (event.confidence === undefined || (typeof event.confidence === "number" && event.confidence >= 0 && event.confidence <= 1)) &&
    (event.duration_ms === undefined || (typeof event.duration_ms === "number" && event.duration_ms >= 0));
}
