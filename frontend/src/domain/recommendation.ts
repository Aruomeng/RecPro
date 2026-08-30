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
  readonly details?: Record<string, unknown>;
}

export interface ResourceSummary {
  resource_id: number;
  resource_type: ResourceType;
  title: string;
  authors: string[];
  publication_year?: number | null;
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
  graph_path_refs?: string[];
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
  evidence?: RecommendationEvidence | null;
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
    typeof candidate.retryable === "boolean" &&
    (candidate.details === undefined || (typeof candidate.details === "object" && candidate.details !== null && !Array.isArray(candidate.details)))
  );
}

export class RecommendationDecodeError extends Error {
  readonly path: string;
  readonly expected: string;
  readonly actualType: string;

  constructor(path: string, expected: string, actual: unknown) {
    super(`INVALID_RUN_RESULT at ${path}: expected ${expected}, received ${publicType(actual)}`);
    this.name = "RecommendationDecodeError";
    this.path = path;
    this.expected = expected;
    this.actualType = publicType(actual);
  }
}

function publicType(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  if (typeof value === "number" && !Number.isFinite(value)) return "non-finite number";
  return typeof value;
}

function assert(condition: boolean, path: string, expected: string, actual: unknown): asserts condition {
  if (!condition) throw new RecommendationDecodeError(path, expected, actual);
}

function record(value: unknown, path: string): Record<string, unknown> {
  assert(typeof value === "object" && value !== null && !Array.isArray(value), path, "object", value);
  return value as Record<string, unknown>;
}

function text(value: unknown, path: string, options: { nullable?: boolean } = {}): void {
  const nullable = options.nullable ?? false;
  if (nullable && value === null) return;
  assert(typeof value === "string" && value.length > 0, path, nullable ? "non-empty string or null" : "non-empty string", value);
}

function number(value: unknown, path: string, min?: number, max?: number, nullable = false): void {
  if (nullable && value === null) return;
  assert(typeof value === "number" && Number.isFinite(value) && (min === undefined || value >= min) && (max === undefined || value <= max), path, `finite number${min === undefined ? "" : ` >= ${min}`}${max === undefined ? "" : ` <= ${max}`}${nullable ? " or null" : ""}`, value);
}

function stringArray(value: unknown, path: string, options: { nonEmpty?: boolean } = {}): void {
  const nonEmpty = options.nonEmpty ?? false;
  assert(Array.isArray(value), path, "array of strings", value);
  if (nonEmpty) assert(value.length > 0, path, "non-empty array of strings", value);
  value.forEach((item, index) => text(item, `${path}[${index}]`));
}

const statuses: TaskStatus[] = ["CREATED", "UNDERSTANDING", "PROBING", "DECIDING", "WAITING_CLARIFICATION", "RECALLING", "RANKING", "REPLANNING", "EXPLAINING", "PERSISTING", "COMPLETED", "DEGRADED_COMPLETED", "FAILED"];
const outputs = ["PERSONALIZED_FEED", "TOPIC_RESOURCES", "BOOKLIST", "READING_PATH"];
const deliveries = ["DIRECT", "GUIDED", "DEGRADED"];
const explanationLevels = ["SUMMARY", "EVIDENCE", "LIMITED"];
const adaptations = ["NORMAL", "FEEDBACK_ADJUSTED"];
const availabilities: AvailabilityStatus[] = ["AVAILABLE_BORROW", "AVAILABLE_ONLINE", "REFERENCE_ONLY", "TEMPORARILY_UNAVAILABLE", "REMOVED"];

export function decodeRecommendationExecution(value: unknown): RecommendationExecution {
  const candidate = record(value, "$");
  text(candidate.task_id, "$.task_id");
  text(candidate.trace_id, "$.trace_id");
  assert(typeof candidate.status === "string" && statuses.includes(candidate.status as TaskStatus), "$.status", "known task status", candidate.status);
  number(candidate.context_version, "$.context_version", 1);
  if (candidate.record_id !== undefined) number(candidate.record_id, "$.record_id", 1, undefined, true);
  if (candidate.evaluation_at !== undefined) text(candidate.evaluation_at, "$.evaluation_at", { nullable: true });

  const decision = record(candidate.decision, "$.decision");
  assert(typeof decision.output_type === "string" && outputs.includes(decision.output_type), "$.decision.output_type", "known output type", decision.output_type);
  assert(typeof decision.delivery_strategy === "string" && deliveries.includes(decision.delivery_strategy), "$.decision.delivery_strategy", "known delivery strategy", decision.delivery_strategy);
  assert(typeof decision.explanation_level === "string" && explanationLevels.includes(decision.explanation_level), "$.decision.explanation_level", "known explanation level", decision.explanation_level);
  assert(typeof decision.adaptation_state === "string" && adaptations.includes(decision.adaptation_state), "$.decision.adaptation_state", "known adaptation state", decision.adaptation_state);
  stringArray(decision.decision_reason_codes, "$.decision.decision_reason_codes", { nonEmpty: true });
  text(decision.decision_reason, "$.decision.decision_reason");
  text(decision.policy_version, "$.decision.policy_version");

  stringArray(candidate.warnings, "$.warnings");
  if (candidate.groups != null) {
    assert(Array.isArray(candidate.groups), "$.groups", "array or null", candidate.groups);
    candidate.groups.forEach((raw, index) => {
      const group = record(raw, `$.groups[${index}]`);
      number(group.group_id, `$.groups[${index}].group_id`, 1);
      text(group.group_type, `$.groups[${index}].group_type`);
      assert(typeof group.group_key === "string", `$.groups[${index}].group_key`, "string", group.group_key);
      assert(typeof group.title === "string", `$.groups[${index}].title`, "string", group.title);
      if (group.goal !== undefined) text(group.goal, `$.groups[${index}].goal`, { nullable: true });
      number(group.order_no, `$.groups[${index}].order_no`, 1);
    });
  }
  if (candidate.items != null) {
    assert(Array.isArray(candidate.items), "$.items", "array or null", candidate.items);
    candidate.items.forEach((raw, index) => decodeItem(raw, `$.items[${index}]`));
  }
  if (candidate.questions != null) {
    assert(Array.isArray(candidate.questions), "$.questions", "array or null", candidate.questions);
    candidate.questions.forEach((raw, index) => decodeQuestion(raw, `$.questions[${index}]`));
  }
  if (candidate.agent_actions !== undefined) {
    assert(Array.isArray(candidate.agent_actions), "$.agent_actions", "array", candidate.agent_actions);
    candidate.agent_actions.forEach((raw, index) => decodeAgentAction(raw, `$.agent_actions[${index}]`));
  }
  if (candidate.versions != null) decodeVersions(candidate.versions, "$.versions");
  return value as RecommendationExecution;
}

export function isRecommendationExecution(value: unknown): value is RecommendationExecution {
  try { decodeRecommendationExecution(value); return true; }
  catch (error) { if (error instanceof RecommendationDecodeError) return false; throw error; }
}

function decodeAgentAction(value: unknown, path: string): void {
  const action = record(value, path);
  if (action.step_no !== undefined) number(action.step_no, `${path}.step_no`, 1, undefined, true);
  text(action.agent_name, `${path}.agent_name`); text(action.agent_version, `${path}.agent_version`);
  if (action.message_type !== undefined) text(action.message_type, `${path}.message_type`, { nullable: true });
  text(action.action, `${path}.action`); text(action.target, `${path}.target`); text(action.reason_code, `${path}.reason_code`);
  number(action.confidence, `${path}.confidence`, 0, 1);
  record(action.parameters, `${path}.parameters`);
  stringArray(action.evidence_refs, `${path}.evidence_refs`);
}

function decodeItem(value: unknown, path: string): void {
  const item = record(value, path);
  number(item.item_id, `${path}.item_id`, 1); number(item.rank_no, `${path}.rank_no`, 1);
  if (item.group_id !== undefined) number(item.group_id, `${path}.group_id`, 1, undefined, true);
  text(item.reason_summary, `${path}.reason_summary`); number(item.evidence_confidence, `${path}.evidence_confidence`, 0, 1);
  assert(typeof item.unavailable_now === "boolean", `${path}.unavailable_now`, "boolean", item.unavailable_now);
  const resource = record(item.resource, `${path}.resource`);
  number(resource.resource_id, `${path}.resource.resource_id`, 1);
  assert(resource.resource_type === "BOOK" || resource.resource_type === "PAPER", `${path}.resource.resource_type`, "BOOK or PAPER", resource.resource_type);
  text(resource.title, `${path}.resource.title`); stringArray(resource.authors, `${path}.resource.authors`);
  if (resource.publication_year !== undefined) number(resource.publication_year, `${path}.resource.publication_year`, 1, undefined, true);
  assert(typeof resource.availability_status === "string" && availabilities.includes(resource.availability_status as AvailabilityStatus), `${path}.resource.availability_status`, "known availability status", resource.availability_status);
  if (resource.difficulty_level !== undefined) number(resource.difficulty_level, `${path}.resource.difficulty_level`, 1, 4, true);
  if (item.evidence != null) decodeEvidence(item.evidence, `${path}.evidence`);
}

function decodeEvidence(value: unknown, path: string): void {
  const evidence = record(value, path);
  number(evidence.score, `${path}.score`, 0, 1); stringArray(evidence.channels, `${path}.channels`, { nonEmpty: true });
  const scores = record(evidence.channel_scores, `${path}.channel_scores`);
  Object.entries(scores).forEach(([key, score]) => number(score, `${path}.channel_scores.${key}`, 0));
  const ranks = record(evidence.channel_ranks, `${path}.channel_ranks`);
  Object.entries(ranks).forEach(([key, rank]) => number(rank, `${path}.channel_ranks.${key}`, 1));
  if (evidence.primary_channel !== undefined) text(evidence.primary_channel, `${path}.primary_channel`, { nullable: true });
  stringArray(evidence.evidence_refs, `${path}.evidence_refs`, { nonEmpty: true });
  if (evidence.graph_path_refs !== undefined) stringArray(evidence.graph_path_refs, `${path}.graph_path_refs`);
  number(evidence.negative_penalty, `${path}.negative_penalty`, 0, 1);
}

function decodeQuestion(value: unknown, path: string): void {
  const question = record(value, path);
  text(question.slot, `${path}.slot`); text(question.question, `${path}.question`);
  stringArray(question.options, `${path}.options`, { nonEmpty: true });
  assert(typeof question.required === "boolean", `${path}.required`, "boolean", question.required);
}

function decodeVersions(value: unknown, path: string): void {
  const versions = record(value, path);
  ["config_bundle", "policy", "ranking", "behavior_formula", "dataset"].forEach((key) => text(versions[key], `${path}.${key}`));
  ["embedding", "graph", "prompt"].forEach((key) => { if (versions[key] !== undefined) text(versions[key], `${path}.${key}`, { nullable: true }); });
}
