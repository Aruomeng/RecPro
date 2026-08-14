export type ResourceType = "BOOK" | "PAPER";
export type RecommendationOutputType = "PERSONALIZED_FEED" | "TOPIC_RESOURCES" | "READING_PATH";
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
  constraints?: Record<string, unknown>;
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
  difficulty_level?: number | null;
}

export interface RecommendationEvidence {
  score: number;
  channels: string[];
  channel_scores: Record<string, number>;
  channel_ranks: Record<string, number>;
  primary_channel?: string;
  evidence_refs: string[];
  negative_penalty: number;
}

export interface RecommendationItem {
  item_id: number;
  resource: ResourceSummary;
  rank_no: number;
  group_id?: number;
  reason_summary: string;
  evidence_confidence: number;
  unavailable_now: boolean;
  evidence?: RecommendationEvidence;
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
  questions?: ClarificationQuestion[] | null;
  warnings: string[];
  agent_actions?: Array<{
    step_no?: number;
    agent_name: string;
    agent_version: string;
    message_type?: string;
    action: string;
    target: string;
    reason_code: string;
    confidence: number;
    parameters: Record<string, unknown>;
    evidence_refs: string[];
  }>;
  versions?: VersionBundle;
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(value: string): boolean {
  return UUID_PATTERN.test(value);
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
    (candidate.agent_actions === undefined || (Array.isArray(candidate.agent_actions) && candidate.agent_actions.every(isAgentAction))) &&
    (candidate.items === undefined || (Array.isArray(candidate.items) && candidate.items.every(isRecommendationItem))) &&
    (candidate.questions == null || (Array.isArray(candidate.questions) && candidate.questions.every(isClarificationQuestion)))
  );
}

function isAgentAction(value: unknown): boolean {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const action = value as Record<string, unknown>;
  return (
    typeof action.agent_name === "string" && action.agent_name.length > 0 &&
    typeof action.agent_version === "string" && action.agent_version.length > 0 &&
    typeof action.action === "string" && typeof action.target === "string" &&
    typeof action.reason_code === "string" && typeof action.confidence === "number" &&
    action.confidence >= 0 && action.confidence <= 1 &&
    typeof action.parameters === "object" && action.parameters !== null &&
    Array.isArray(action.evidence_refs)
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
    typeof resource.availability_status === "string" &&
    (resource.difficulty_level == null || (typeof resource.difficulty_level === "number" && resource.difficulty_level >= 1 && resource.difficulty_level <= 4)) &&
    (candidate.evidence === undefined || isRecommendationEvidence(candidate.evidence))
  );
}

function isRecommendationEvidence(value: unknown): value is RecommendationEvidence {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const candidate = value as Partial<RecommendationEvidence>;
  return (
    typeof candidate.score === "number" && candidate.score >= 0 && candidate.score <= 1 &&
    Array.isArray(candidate.channels) && candidate.channels.length > 0 && candidate.channels.every((item) => typeof item === "string") &&
    typeof candidate.channel_scores === "object" && candidate.channel_scores !== null &&
    typeof candidate.channel_ranks === "object" && candidate.channel_ranks !== null &&
    Array.isArray(candidate.evidence_refs) && candidate.evidence_refs.every((item) => typeof item === "string") &&
    typeof candidate.negative_penalty === "number" && candidate.negative_penalty >= 0 && candidate.negative_penalty <= 1
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
