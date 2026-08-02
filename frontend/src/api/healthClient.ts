import type {
  ComponentReadiness,
  ComponentStatus,
  ErrorResponse,
  HealthFailure,
  LivenessResponse,
  ReadinessResponse,
  ReadinessStatus,
} from "../domain/health";

export const HEALTH_PATHS = {
  live: "/api/v1/health/live",
  ready: "/api/v1/health/ready",
} as const;

export type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export interface RequestOptions {
  signal?: AbortSignal;
}

export interface HealthClient {
  getLiveness(options?: RequestOptions): Promise<LivenessResponse>;
  getReadiness(options?: RequestOptions): Promise<ReadinessResponse>;
}

export class HealthApiError extends Error implements HealthFailure {
  readonly kind = "health_api_error" as const;
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
    this.name = "HealthApiError";
    this.status = params.status;
    this.code = params.code;
    this.retryable = params.retryable ?? false;
    this.requestId = params.requestId;
    this.traceId = params.traceId;
    this.details = params.details ?? {};
  }
}

const componentStatuses = new Set<ComponentStatus>([
  "UP",
  "DOWN",
  "DISABLED",
  "MOCK",
  "UNKNOWN",
]);
const readinessStatuses = new Set<ReadinessStatus>(["READY", "DEGRADED", "NOT_READY"]);
const healthErrorCodes = new Set([
  "INVALID_JSON",
  "NOT_FOUND",
  "CORE_STORAGE_UNAVAILABLE",
  "UNSAFE_DATABASE_PRIVILEGES",
  "CONFIG_BUNDLE_INVALID",
  "REQUEST_DEADLINE_EXCEEDED",
]);
const canonicalUuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function hasOnlyKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[] = [],
): boolean {
  const keys = Object.keys(value);
  const allowed = new Set([...required, ...optional]);
  return required.every((key) => key in value) && keys.every((key) => allowed.has(key));
}

function isDateTime(value: unknown): value is string {
  return (
    isNonEmptyString(value) &&
    /^\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}

function isCanonicalUuid(value: unknown): value is string {
  return typeof value === "string" && canonicalUuidPattern.test(value);
}

function isComponentReadiness(value: unknown): value is ComponentReadiness {
  if (!isRecord(value) || !componentStatuses.has(value.status as ComponentStatus)) {
    return false;
  }
  if (!hasOnlyKeys(value, ["status", "required"], ["active_version", "provider", "error_code"])) {
    return false;
  }
  if (typeof value.required !== "boolean") {
    return false;
  }
  return ["active_version", "provider", "error_code"].every(
    (field) => value[field] === undefined || typeof value[field] === "string",
  );
}

function isLivenessResponse(value: unknown): value is LivenessResponse {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["status", "service", "version", "time"]) &&
    value.status === "UP" &&
    value.service === "recpro-backend" &&
    isNonEmptyString(value.version) &&
    isDateTime(value.time)
  );
}

function isReadinessResponse(value: unknown): value is ReadinessResponse {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "status",
      "can_recommend",
      "components",
      "config_bundle_version",
      "checked_at",
    ]) ||
    !readinessStatuses.has(value.status as ReadinessStatus) ||
    typeof value.can_recommend !== "boolean" ||
    !isRecord(value.components) ||
    Object.keys(value.components).length === 0 ||
    !isNonEmptyString(value.config_bundle_version) ||
    !isDateTime(value.checked_at)
  ) {
    return false;
  }
  if (!Object.values(value.components).every(isComponentReadiness)) {
    return false;
  }
  if (value.can_recommend === true) {
    return false;
  }
  return true;
}

function isErrorResponse(value: unknown): value is ErrorResponse {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["error", "request_id", "trace_id"]) &&
    isRecord(value.error) &&
    hasOnlyKeys(value.error, ["code", "message", "details", "retryable"]) &&
    healthErrorCodes.has(value.error.code as string) &&
    isNonEmptyString(value.error.message) &&
    isRecord(value.error.details) &&
    typeof value.error.retryable === "boolean" &&
    isCanonicalUuid(value.request_id) &&
    isCanonicalUuid(value.trace_id)
  );
}

async function readJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("application/json")) {
    throw new HealthApiError({
      status: response.status,
      code: "INVALID_HEALTH_RESPONSE",
      message: "健康接口返回了非 JSON 响应。",
    });
  }

  try {
    return await response.json();
  } catch {
    throw new HealthApiError({
      status: response.status,
      code: "INVALID_HEALTH_RESPONSE",
      message: "健康接口返回的 JSON 无法解析。",
    });
  }
}

function toApiError(status: number, payload: unknown): HealthApiError {
  if (isErrorResponse(payload)) {
    return new HealthApiError({
      status,
      code: payload.error.code,
      message: payload.error.message,
      retryable: payload.error.retryable,
      requestId: payload.request_id,
      traceId: payload.trace_id,
      details: payload.error.details,
    });
  }

  return new HealthApiError({
    status,
    code: "INVALID_HEALTH_ERROR_RESPONSE",
    message: "健康接口返回了不符合契约的错误响应。",
  });
}

async function request<T>(params: {
  fetcher: Fetcher;
  url: string;
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
      method: "GET",
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    const payload = await readJson(response);

    if (!response.ok) {
      throw toApiError(response.status, payload);
    }
    if (!params.validate(payload)) {
      throw new HealthApiError({
        status: response.status,
        code: "INVALID_HEALTH_RESPONSE",
        message: "健康接口响应不符合冻结契约。",
      });
    }
    return payload;
  } catch (error) {
    if (timedOut) {
      throw new HealthApiError({
        status: 0,
        code: "HEALTH_REQUEST_TIMEOUT",
        message: "健康接口未在规定时间内响应。",
        retryable: true,
      });
    }
    throw error;
  } finally {
    globalThis.clearTimeout(timeout);
    params.signal?.removeEventListener("abort", abortFromCaller);
  }
}

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
}

export function createHealthClient(params: {
  baseUrl?: string;
  fetcher?: Fetcher;
  timeoutMs?: number;
} = {}): HealthClient {
  const baseUrl = normalizeBaseUrl(params.baseUrl ?? "");
  const fetcher = params.fetcher ?? globalThis.fetch.bind(globalThis);
  const timeoutMs = params.timeoutMs ?? 5_000;
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new RangeError("timeoutMs must be a positive finite number");
  }

  return {
    getLiveness(options = {}) {
      return request({
        fetcher,
        url: `${baseUrl}${HEALTH_PATHS.live}`,
        signal: options.signal,
        timeoutMs,
        validate: isLivenessResponse,
      });
    },
    getReadiness(options = {}) {
      return request({
        fetcher,
        url: `${baseUrl}${HEALTH_PATHS.ready}`,
        signal: options.signal,
        timeoutMs,
        validate: isReadinessResponse,
      });
    },
  };
}

export const healthClient = createHealthClient({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
});
