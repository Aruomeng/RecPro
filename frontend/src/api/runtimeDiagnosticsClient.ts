import type { RuntimeDiagnosticsResponse } from "../domain/runtimeDiagnostics";
import { isRuntimeDiagnosticsResponse } from "../domain/runtimeDiagnostics";

const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export interface RuntimeDiagnosticsRequestOptions {
  signal?: AbortSignal;
}

export class RuntimeDiagnosticsApiError extends Error {
  readonly kind = "runtime_diagnostics_api_error" as const;

  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly retryable = false,
    readonly requestId?: string,
    readonly traceId?: string,
  ) {
    super(message);
    this.name = "RuntimeDiagnosticsApiError";
  }
}

export interface RuntimeDiagnosticsClient {
  get(accessToken: string, options?: RuntimeDiagnosticsRequestOptions): Promise<RuntimeDiagnosticsResponse>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isErrorResponse(value: unknown): value is {
  error: { code: string; message: string; retryable: boolean };
  request_id: string;
  trace_id: string;
} {
  if (!isRecord(value) || !["error", "request_id", "trace_id"].every((key) => key in value) ||
      !isRecord(value.error)) {
    return false;
  }
  const error = value.error;
  return ["code", "message", "details", "retryable"].every((key) => key in error) &&
    typeof error.code === "string" && typeof error.message === "string" &&
    isRecord(error.details) && typeof error.retryable === "boolean" &&
    typeof value.request_id === "string" && uuidPattern.test(value.request_id) &&
    typeof value.trace_id === "string" && uuidPattern.test(value.trace_id) &&
    Object.keys(value).every((key) => ["error", "request_id", "trace_id"].includes(key)) &&
    Object.keys(error).every((key) => ["code", "message", "details", "retryable"].includes(key));
}

async function readJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("application/json")) {
    throw new RuntimeDiagnosticsApiError(response.status, "INVALID_RUNTIME_DIAGNOSTICS_RESPONSE", "运行时诊断接口返回了非 JSON 响应。", response.status >= 500);
  }
  try {
    return await response.json();
  } catch {
    throw new RuntimeDiagnosticsApiError(response.status, "INVALID_RUNTIME_DIAGNOSTICS_RESPONSE", "运行时诊断接口返回的 JSON 无法解析。", response.status >= 500);
  }
}

async function request(params: {
  accessToken: string;
  fetcher: typeof fetch;
  signal?: AbortSignal;
  timeoutMs: number;
}): Promise<RuntimeDiagnosticsResponse> {
  if (!params.accessToken.trim()) throw new RuntimeDiagnosticsApiError(401, "AUTHENTICATION_REQUIRED", "研究管理员身份已失效，请重新登录。", false);
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
    const response = await params.fetcher(`${baseUrl}/api/v1/debug/runtime`, {
      method: "GET",
      cache: "no-store",
      headers: { Accept: "application/json", Authorization: `Bearer ${params.accessToken}` },
      signal: controller.signal,
    });
    const payload = await readJson(response);
    if (!response.ok) {
      if (isErrorResponse(payload)) {
        throw new RuntimeDiagnosticsApiError(response.status, payload.error.code, payload.error.message, payload.error.retryable, payload.request_id, payload.trace_id);
      }
      throw new RuntimeDiagnosticsApiError(response.status, "INVALID_RUNTIME_DIAGNOSTICS_ERROR_RESPONSE", "运行时诊断接口返回了不符合契约的错误响应。", response.status >= 500);
    }
    if (!isRuntimeDiagnosticsResponse(payload)) {
      throw new RuntimeDiagnosticsApiError(response.status, "INVALID_RUNTIME_DIAGNOSTICS_RESPONSE", "运行时诊断响应不符合冻结契约。", false);
    }
    return payload;
  } catch (error) {
    if (timedOut) {
      throw new RuntimeDiagnosticsApiError(0, "RUNTIME_DIAGNOSTICS_REQUEST_TIMEOUT", "运行时诊断接口未在规定时间内响应。", true);
    }
    throw error;
  } finally {
    globalThis.clearTimeout(timeout);
    params.signal?.removeEventListener("abort", abortFromCaller);
  }
}

export function createRuntimeDiagnosticsClient(params: {
  fetcher?: typeof fetch;
  timeoutMs?: number;
} = {}): RuntimeDiagnosticsClient {
  const timeoutMs = params.timeoutMs ?? 5_000;
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new RangeError("timeoutMs must be a positive finite number");
  const fetcher = params.fetcher ?? globalThis.fetch.bind(globalThis);
  return {
    get(accessToken, options = {}) {
      return request({ accessToken, fetcher, signal: options.signal, timeoutMs });
    },
  };
}

export const runtimeDiagnosticsClient = createRuntimeDiagnosticsClient();
