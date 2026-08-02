export type ReadinessStatus = "READY" | "DEGRADED" | "NOT_READY";
export type ComponentStatus = "UP" | "DOWN" | "DISABLED" | "MOCK" | "UNKNOWN";

export interface LivenessResponse {
  status: "UP";
  service: "recpro-backend";
  version: string;
  time: string;
}

export interface ComponentReadiness {
  status: ComponentStatus;
  required: boolean;
  active_version?: string;
  provider?: string;
  error_code?: string;
}

export interface ReadinessResponse {
  status: ReadinessStatus;
  can_recommend: false;
  components: Record<string, ComponentReadiness>;
  config_bundle_version: string;
  checked_at: string;
}

export interface ErrorResponse {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
    retryable: boolean;
  };
  request_id: string;
  trace_id: string;
}

export interface HealthFailure {
  readonly kind: "health_api_error";
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
  readonly requestId?: string;
  readonly traceId?: string;
  readonly details: Record<string, unknown>;
}

export function isHealthFailure(value: unknown): value is HealthFailure {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<HealthFailure>;
  return (
    candidate.kind === "health_api_error" &&
    typeof candidate.status === "number" &&
    typeof candidate.code === "string" &&
    typeof candidate.retryable === "boolean" &&
    typeof candidate.details === "object" &&
    candidate.details !== null
  );
}

export type Loadable<T> =
  | { phase: "loading" }
  | { phase: "success"; value: T }
  | { phase: "error"; error: unknown };

export function isRecommendationPipelineDisabled(readiness: ReadinessResponse): boolean {
  return readiness.components.recommendation_pipeline?.status === "DISABLED";
}
