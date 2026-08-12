export type ResourceType = "BOOK" | "PAPER";
export type RecommendationOutputType = "TOPIC_RESOURCES";
export type TriggerScene = "HOME" | "SEARCH_AFTER" | "RESOURCE_DETAIL" | "FEEDBACK_REFRESH" | "EXPLANATION";
export type TaskStatus =
  | "CREATED"
  | "UNDERSTANDING"
  | "PROBING"
  | "DECIDING"
  | "WAITING_CLARIFICATION"
  | "RECALLING"
  | "RANKING"
  | "REPLANNING"
  | "EXPLAINING"
  | "PERSISTING"
  | "COMPLETED"
  | "DEGRADED_COMPLETED"
  | "FAILED";

export type AvailabilityStatus =
  | "AVAILABLE_BORROW"
  | "AVAILABLE_ONLINE"
  | "REFERENCE_ONLY"
  | "TEMPORARILY_UNAVAILABLE"
  | "REMOVED";

export interface RecommendationRequest {
  request_id: string;
  session_id: string;
  scene: "SEARCH_AFTER";
  input_text: string;
  requested_resource_types: ResourceType[];
  requested_output_type: RecommendationOutputType;
  limit: number;
}

export interface RecommendationClient {
  createTask(request: RecommendationRequest, options?: { signal?: AbortSignal }): Promise<RecommendationExecution>;
  submitClarification(
    taskId: string,
    contextVersion: number,
    answers: Record<string, string>,
    idempotencyKey: string,
    options?: { signal?: AbortSignal },
  ): Promise<RecommendationExecution>;
}

export interface RecommendationFailure {
  readonly kind: "recommendation_api_error";
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
}

export interface ResourceSummary {
  resource_id: number;
  resource_type: ResourceType;
  title: string;
  authors: string[];
  publication_year?: number;
  availability_status: AvailabilityStatus;
}

export interface RecommendationItem {
  item_id: number;
  resource: ResourceSummary;
  rank_no: number;
  group_id?: number;
  reason_summary: string;
  evidence_confidence: number;
  unavailable_now: boolean;
}

export interface ClarificationQuestion {
  slot: string;
  question: string;
  options: string[];
  required: boolean;
}

export interface InteractionDecision {
  output_type: string;
  delivery_strategy: string;
  explanation_level: string;
  adaptation_state: string;
  decision_reason_codes: string[];
  decision_reason: string;
  policy_version: string;
}

export interface VersionBundle {
  config_bundle: string;
  policy: string;
  ranking: string;
  behavior_formula: string;
  embedding?: string;
  graph?: string;
  prompt?: string;
  dataset: string;
}

export interface RecommendationExecution {
  task_id: string;
  record_id?: number;
  trace_id: string;
  status: TaskStatus;
  context_version: number;
  evaluation_at?: string;
  decision: InteractionDecision;
  groups?: Array<{ group_id: number; group_type: string; group_key: string; title: string; goal?: string; order_no: number }>;
  items?: RecommendationItem[];
  questions?: ClarificationQuestion[];
  warnings: string[];
  versions?: VersionBundle;
}

export function createRequestId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") return globalThis.crypto.randomUUID();
  return `local-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function isRecommendationFailure(value: unknown): value is RecommendationFailure {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<RecommendationFailure>;
  return (
    candidate.kind === "recommendation_api_error" &&
    typeof candidate.status === "number" &&
    typeof candidate.code === "string" &&
    typeof candidate.retryable === "boolean"
  );
}

export function isRecommendationExecution(value: unknown): value is RecommendationExecution {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const candidate = value as Partial<RecommendationExecution>;
  return (
    typeof candidate.task_id === "string" && candidate.task_id.length > 0 &&
    typeof candidate.trace_id === "string" && candidate.trace_id.length > 0 &&
    typeof candidate.status === "string" &&
    typeof candidate.context_version === "number" && candidate.context_version >= 1 &&
    typeof candidate.decision === "object" && candidate.decision !== null &&
    Array.isArray(candidate.warnings) && candidate.warnings.every((item) => typeof item === "string") &&
    (candidate.items === undefined || (Array.isArray(candidate.items) && candidate.items.every(isRecommendationItem))) &&
    (candidate.questions === undefined || (Array.isArray(candidate.questions) && candidate.questions.every(isClarificationQuestion)))
  );
}

function isRecommendationItem(value: unknown): value is RecommendationItem {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const candidate = value as Partial<RecommendationItem>;
  const resource = candidate.resource as Partial<ResourceSummary> | undefined;
  return (
    typeof candidate.item_id === "number" && candidate.item_id >= 1 &&
    typeof candidate.rank_no === "number" && candidate.rank_no >= 1 &&
    typeof candidate.reason_summary === "string" && candidate.reason_summary.length > 0 &&
    typeof candidate.evidence_confidence === "number" && candidate.evidence_confidence >= 0 && candidate.evidence_confidence <= 1 &&
    typeof candidate.unavailable_now === "boolean" &&
    typeof resource === "object" && resource !== null &&
    typeof resource.resource_id === "number" && resource.resource_id >= 1 &&
    (resource.resource_type === "BOOK" || resource.resource_type === "PAPER") &&
    typeof resource.title === "string" && resource.title.length > 0 &&
    Array.isArray(resource.authors) && resource.authors.every((author) => typeof author === "string") &&
    typeof resource.availability_status === "string"
  );
}

function isClarificationQuestion(value: unknown): value is ClarificationQuestion {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const candidate = value as Partial<ClarificationQuestion>;
  return (
    typeof candidate.slot === "string" && candidate.slot.length > 0 &&
    typeof candidate.question === "string" && candidate.question.length > 0 &&
    Array.isArray(candidate.options) && candidate.options.length > 0 && candidate.options.every((item) => typeof item === "string" && item.length > 0) &&
    typeof candidate.required === "boolean"
  );
}
