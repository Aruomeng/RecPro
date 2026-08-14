import type {
  BehaviorEventReceipt,
  BehaviorEventRequest,
  FeedbackReceipt,
  FeedbackRequest,
  ImpressionBatchRequest,
  ImpressionBatchResponse,
  InteractionClient,
} from "../domain/interaction";

export const INTERACTION_PATHS = {
  impressions: "/api/v1/recommendation-impressions/batch",
  feedback: (itemId: number) => `/api/v1/recommendation-items/${encodeURIComponent(String(itemId))}/feedback`,
  behavior: "/api/v1/behavior-events",
} as const;

export const DEFAULT_INTERACTION_TIMEOUT_MS = 30_000;

export type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export class InteractionApiError extends Error {
  readonly kind = "interaction_api_error" as const;
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
  readonly requestId?: string;
  readonly traceId?: string;
  readonly details: Record<string, unknown>;

  constructor(params: {
    status: number;
    code: string;
    message: string;
    retryable?: boolean;
    requestId?: string;
    traceId?: string;
    details?: Record<string, unknown>;
  }) {
    super(params.message);
    this.name = "InteractionApiError";
    this.status = params.status;
    this.code = params.code;
    this.retryable = params.retryable ?? false;
    this.requestId = params.requestId;
    this.traceId = params.traceId;
    this.details = params.details ?? {};
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1;
}

function hasOnlyKeys(value: Record<string, unknown>, required: readonly string[], optional: readonly string[] = []): boolean {
  const allowed = new Set([...required, ...optional]);
  return required.every((key) => key in value) && Object.keys(value).every((key) => allowed.has(key));
}

function isStatus(value: unknown, allowed: readonly string[]): boolean {
  return typeof value === "string" && allowed.includes(value);
}

function isAgentAction(value: unknown): boolean {
  if (!isRecord(value) || !hasOnlyKeys(
    value,
    ["agent_name", "agent_version", "action", "target", "reason_code", "confidence", "parameters", "evidence_refs"],
    ["step_no", "message_type"],
  )) return false;
  return (
    isNonEmptyString(value.agent_name) &&
    isNonEmptyString(value.agent_version) &&
    isNonEmptyString(value.action) &&
    isNonEmptyString(value.target) &&
    isNonEmptyString(value.reason_code) &&
    typeof value.confidence === "number" && value.confidence >= 0 && value.confidence <= 1 &&
    isRecord(value.parameters) &&
    Array.isArray(value.evidence_refs) && value.evidence_refs.every(isNonEmptyString) &&
    (value.step_no === undefined || value.step_no === null || isPositiveInteger(value.step_no)) &&
    (value.message_type === undefined || value.message_type === null || isNonEmptyString(value.message_type))
  );
}

function isImpressionResult(value: unknown): boolean {
  if (!isRecord(value) || !hasOnlyKeys(value, ["impression_uuid", "status", "is_valid_exposure"], ["error_code", "agent_action"])) return false;
  return (
    isNonEmptyString(value.impression_uuid) &&
    isStatus(value.status, ["ACCEPTED", "REPLAYED", "REJECTED"]) &&
    typeof value.is_valid_exposure === "boolean" &&
    (value.error_code === undefined || isNonEmptyString(value.error_code)) &&
    (value.agent_action === undefined || isAgentAction(value.agent_action))
  );
}

function isImpressionBatchResponse(value: unknown): value is ImpressionBatchResponse {
  if (!isRecord(value) || !hasOnlyKeys(value, ["accepted_count", "replayed_count", "rejected_count", "results"])) return false;
  return (
    typeof value.accepted_count === "number" && value.accepted_count >= 0 &&
    typeof value.replayed_count === "number" && value.replayed_count >= 0 &&
    typeof value.rejected_count === "number" && value.rejected_count >= 0 &&
    Array.isArray(value.results) && value.results.every(isImpressionResult)
  );
}

function isResourceState(value: unknown): boolean {
  if (!isRecord(value) || !hasOnlyKeys(value, ["state_type"], ["suppress_until"])) return false;
  return isNonEmptyString(value.state_type) && (value.suppress_until === undefined || isNonEmptyString(value.suppress_until));
}

function isFeedbackReceipt(value: unknown): value is FeedbackReceipt {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(
      value,
      ["feedback_uuid", "feedback_id", "status", "behavior_event_id", "profile_update_status"],
      ["resource_state", "profile_version_before", "profile_version_after", "agent_action"],
    )
  ) return false;
  return (
    isNonEmptyString(value.feedback_uuid) &&
    isPositiveInteger(value.feedback_id) &&
    isStatus(value.status, ["ACCEPTED", "APPLIED", "REPLAYED"]) &&
    isPositiveInteger(value.behavior_event_id) &&
    isStatus(value.profile_update_status, ["APPLIED", "PENDING", "NOT_REQUIRED"]) &&
    (value.resource_state === undefined || isResourceState(value.resource_state)) &&
    (value.profile_version_before === undefined || isPositiveInteger(value.profile_version_before)) &&
    (value.profile_version_after === undefined || isPositiveInteger(value.profile_version_after)) &&
    (value.agent_action === undefined || isAgentAction(value.agent_action))
  );
}

function isBehaviorReceipt(value: unknown): value is BehaviorEventReceipt {
  if (!isRecord(value) || !hasOnlyKeys(value, ["event_uuid", "event_id", "status", "profile_update_status"], ["agent_action"])) return false;
  return (
    isNonEmptyString(value.event_uuid) &&
    isPositiveInteger(value.event_id) &&
    isStatus(value.status, ["ACCEPTED", "APPLIED", "REPLAYED"]) &&
    isStatus(value.profile_update_status, ["APPLIED", "PENDING", "NOT_REQUIRED"]) &&
    (value.agent_action === undefined || isAgentAction(value.agent_action))
  );
}

async function readJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("application/json")) {
    throw new InteractionApiError({
      status: response.status,
      code: "INVALID_INTERACTION_RESPONSE",
      message: "交互接口返回了非 JSON 响应。",
    });
  }
  try {
    return await response.json();
  } catch {
    throw new InteractionApiError({
      status: response.status,
      code: "INVALID_INTERACTION_RESPONSE",
      message: "交互接口返回的 JSON 无法解析。",
    });
  }
}

function toApiError(status: number, payload: unknown): InteractionApiError {
  if (isRecord(payload) && isRecord(payload.error) && isNonEmptyString(payload.error.code) && isNonEmptyString(payload.error.message)) {
    return new InteractionApiError({
      status,
      code: payload.error.code,
      message: payload.error.message,
      retryable: typeof payload.error.retryable === "boolean" ? payload.error.retryable : false,
      requestId: isNonEmptyString(payload.request_id) ? payload.request_id : undefined,
      traceId: isNonEmptyString(payload.trace_id) ? payload.trace_id : undefined,
      details: isRecord(payload.error.details) ? payload.error.details : {},
    });
  }
  return new InteractionApiError({
    status,
    code: "INVALID_INTERACTION_ERROR_RESPONSE",
    message: "交互接口返回了不符合冻结契约的错误响应。",
  });
}

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
}

async function post<T>(params: {
  fetcher: Fetcher;
  url: string;
  body: unknown;
  idempotencyKey: string;
  demoUserId: number;
  signal?: AbortSignal;
  timeoutMs: number;
  validate: (value: unknown) => value is T;
}): Promise<T> {
  if (params.idempotencyKey.trim().length < 8) throw new TypeError("idempotencyKey must contain at least 8 characters");
  const controller = new AbortController();
  let timedOut = false;
  const abortFromCaller = () => controller.abort(params.signal?.reason);
  if (params.signal?.aborted) abortFromCaller();
  else params.signal?.addEventListener("abort", abortFromCaller, { once: true });
  const timeout = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, params.timeoutMs);
  try {
    const response = await params.fetcher(params.url, {
      method: "POST",
      cache: "no-store",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "Idempotency-Key": params.idempotencyKey,
        "X-Demo-User-Id": String(params.demoUserId),
      },
      body: JSON.stringify(params.body),
      signal: controller.signal,
    });
    const payload = await readJson(response);
    if (!response.ok) throw toApiError(response.status, payload);
    if (!params.validate(payload)) {
      throw new InteractionApiError({
        status: response.status,
        code: "INVALID_INTERACTION_RESPONSE",
        message: "交互接口响应不符合冻结契约。",
      });
    }
    return payload;
  } catch (error) {
    if (timedOut) {
      throw new InteractionApiError({
        status: 0,
        code: "INTERACTION_REQUEST_TIMEOUT",
        message: "交互接口未在规定时间内响应。",
        retryable: true,
      });
    }
    throw error;
  } finally {
    globalThis.clearTimeout(timeout);
    params.signal?.removeEventListener("abort", abortFromCaller);
  }
}

export function createInteractionClient(params: {
  baseUrl?: string;
  fetcher?: Fetcher;
  timeoutMs?: number;
  demoUserId?: number;
} = {}): InteractionClient {
  const baseUrl = normalizeBaseUrl(params.baseUrl ?? "");
  const fetcher = params.fetcher ?? globalThis.fetch.bind(globalThis);
  const timeoutMs = params.timeoutMs ?? DEFAULT_INTERACTION_TIMEOUT_MS;
  const demoUserId = params.demoUserId ?? 1001;
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new RangeError("timeoutMs must be a positive finite number");
  if (!Number.isInteger(demoUserId) || demoUserId < 1) throw new RangeError("demoUserId must be a positive integer");

  return {
    recordImpressions(request, options = {}) {
      if (!Array.isArray(request.impressions) || request.impressions.length < 1) {
        throw new TypeError("at least one impression is required");
      }
      return post({
        fetcher,
        url: `${baseUrl}${INTERACTION_PATHS.impressions}`,
        body: request,
        idempotencyKey: options.idempotencyKey ?? request.impressions[0].impression_uuid,
        demoUserId,
        signal: options.signal,
        timeoutMs,
        validate: isImpressionBatchResponse,
      });
    },
    recordFeedback(itemId, request, options = {}) {
      if (!Number.isInteger(itemId) || itemId < 1) throw new RangeError("itemId must be a positive integer");
      if (request.feedback_uuid.trim().length < 8) throw new TypeError("feedback_uuid must not be blank");
      return post({
        fetcher,
        url: `${baseUrl}${INTERACTION_PATHS.feedback(itemId)}`,
        body: request,
        idempotencyKey: request.feedback_uuid,
        demoUserId,
        signal: options.signal,
        timeoutMs,
        validate: isFeedbackReceipt,
      });
    },
    appendBehavior(request, options = {}) {
      if (request.event_uuid.trim().length < 8) throw new TypeError("event_uuid must not be blank");
      return post({
        fetcher,
        url: `${baseUrl}${INTERACTION_PATHS.behavior}`,
        body: request,
        idempotencyKey: request.event_uuid,
        demoUserId,
        signal: options.signal,
        timeoutMs,
        validate: isBehaviorReceipt,
      });
    },
  };
}

export const interactionClient = createInteractionClient({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
});

export type { InteractionClient } from "../domain/interaction";
