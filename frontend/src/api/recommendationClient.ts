import { isRecommendationExecution } from "../domain/recommendation";
import type { RecommendationClient, RecommendationExecution, RecommendationRequest } from "../domain/recommendation";

export const RECOMMENDATION_PATHS = {
  tasks: "/api/v1/recommendation-tasks",
} as const;

export type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export interface RequestOptions {
  signal?: AbortSignal;
}

export class RecommendationApiError extends Error {
  readonly kind = "recommendation_api_error" as const;
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
    this.name = "RecommendationApiError";
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

async function readJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("application/json")) {
    throw new RecommendationApiError({
      status: response.status,
      code: "INVALID_RECOMMENDATION_RESPONSE",
      message: "推荐接口返回了非 JSON 响应。",
    });
  }
  try {
    return await response.json();
  } catch {
    throw new RecommendationApiError({
      status: response.status,
      code: "INVALID_RECOMMENDATION_RESPONSE",
      message: "推荐接口返回的 JSON 无法解析。",
    });
  }
}

function toApiError(status: number, payload: unknown): RecommendationApiError {
  if (isRecord(payload) && isRecord(payload.error)) {
    const error = payload.error;
    if (typeof error.code === "string" && typeof error.message === "string" && typeof error.retryable === "boolean") {
      return new RecommendationApiError({
        status,
        code: error.code,
        message: error.message,
        retryable: error.retryable,
        requestId: typeof payload.request_id === "string" ? payload.request_id : undefined,
        traceId: typeof payload.trace_id === "string" ? payload.trace_id : undefined,
        details: isRecord(error.details) ? error.details : {},
      });
    }
  }
  return new RecommendationApiError({
    status,
    code: "INVALID_RECOMMENDATION_ERROR_RESPONSE",
    message: "推荐接口返回了不符合冻结契约的错误响应。",
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
      throw new RecommendationApiError({
        status: response.status,
        code: "INVALID_RECOMMENDATION_RESPONSE",
        message: "推荐接口响应不符合冻结契约。",
      });
    }
    return payload;
  } catch (error) {
    if (timedOut) {
      throw new RecommendationApiError({
        status: 0,
        code: "RECOMMENDATION_REQUEST_TIMEOUT",
        message: "推荐接口未在规定时间内响应。",
        retryable: true,
      });
    }
    throw error;
  } finally {
    globalThis.clearTimeout(timeout);
    params.signal?.removeEventListener("abort", abortFromCaller);
  }
}

export function createRecommendationClient(params: {
  baseUrl?: string;
  fetcher?: Fetcher;
  timeoutMs?: number;
  demoUserId?: number;
} = {}): RecommendationClient {
  const baseUrl = normalizeBaseUrl(params.baseUrl ?? "");
  const fetcher = params.fetcher ?? globalThis.fetch.bind(globalThis);
  const timeoutMs = params.timeoutMs ?? 15_000;
  const demoUserId = params.demoUserId ?? 1001;
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new RangeError("timeoutMs must be a positive finite number");
  if (!Number.isInteger(demoUserId) || demoUserId < 1) throw new RangeError("demoUserId must be a positive integer");

  return {
    createTask(request, options = {}) {
      return post({
        fetcher,
        url: `${baseUrl}${RECOMMENDATION_PATHS.tasks}`,
        body: request,
        idempotencyKey: request.request_id,
        demoUserId,
        signal: options.signal,
        timeoutMs,
        validate: isRecommendationExecution,
      });
    },
    submitClarification(taskId, contextVersion, answers, idempotencyKey, options = {}) {
      if (!taskId.trim()) throw new TypeError("taskId must not be blank");
      if (!Number.isInteger(contextVersion) || contextVersion < 1) throw new RangeError("contextVersion must be positive");
      return post({
        fetcher,
        url: `${baseUrl}${RECOMMENDATION_PATHS.tasks}/${encodeURIComponent(taskId)}/clarifications`,
        body: { context_version: contextVersion, answers },
        idempotencyKey,
        demoUserId,
        signal: options.signal,
        timeoutMs,
        validate: isRecommendationExecution,
      });
    },
  };
}

export const recommendationClient = createRecommendationClient({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
});

export type { RecommendationClient } from "../domain/recommendation";
