export type RuntimeMetricValue = number | boolean | null;

export interface RuntimeMetricResource {
  resource_type: string;
  metrics: Record<string, RuntimeMetricValue>;
}

export interface RuntimeDiagnosticsResponse {
  schema_version: "runtime-diagnostics-v1";
  registry_closed: boolean;
  resource_count: number;
  resources: RuntimeMetricResource[];
  collected_at: string;
}

export type RuntimeDiagnosticsLoadable =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "success"; value: RuntimeDiagnosticsResponse }
  | { phase: "error"; error: unknown };

const runtimeMetricKeys = [
  "initialized",
  "closed",
  "min_size",
  "max_size",
  "recycle_seconds",
  "acquire_timeout_seconds",
  "pool_size",
  "free_size",
  "active_leases",
  "pending_acquires",
  "acquire_count",
  "acquire_timeout_count",
  "release_count",
  "total_acquire_ms",
  "last_acquire_ms",
  "average_acquire_ms",
] as const;

const runtimeMetricKeySet = new Set<string>(runtimeMetricKeys);
const resourceTypePattern = /^[A-Za-z0-9._-]{1,64}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(value: Record<string, unknown>, required: readonly string[], optional: readonly string[] = []): boolean {
  const allowed = new Set([...required, ...optional]);
  return required.every((key) => key in value) && Object.keys(value).every((key) => allowed.has(key));
}

function isDateTime(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 &&
    /^\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
}

function isMetricValue(value: unknown): value is RuntimeMetricValue {
  return value === null || typeof value === "boolean" || typeof value === "number" && Number.isFinite(value);
}

function isRuntimeMetricResource(value: unknown): value is RuntimeMetricResource {
  if (!isRecord(value) || !hasOnlyKeys(value, ["resource_type", "metrics"]) ||
      typeof value.resource_type !== "string" || !resourceTypePattern.test(value.resource_type) || !isRecord(value.metrics)) {
    return false;
  }
  return Object.entries(value.metrics).every(([key, metric]) => runtimeMetricKeySet.has(key) && isMetricValue(metric));
}

export function isRuntimeDiagnosticsResponse(value: unknown): value is RuntimeDiagnosticsResponse {
  if (!isRecord(value) || !hasOnlyKeys(value, ["schema_version", "registry_closed", "resource_count", "resources", "collected_at"]) ||
      value.schema_version !== "runtime-diagnostics-v1" || typeof value.registry_closed !== "boolean" ||
      typeof value.resource_count !== "number" || !Number.isInteger(value.resource_count) || value.resource_count < 0 || value.resource_count > 64 ||
      !Array.isArray(value.resources) || value.resources.length > 64 || value.resource_count !== value.resources.length ||
      !value.resources.every(isRuntimeMetricResource) || !isDateTime(value.collected_at)) {
    return false;
  }
  return true;
}

export { runtimeMetricKeys };
