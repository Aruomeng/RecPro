export type FeedbackType = "FAVORITE" | "BORROW" | "REJECT" | "NOT_INTERESTED" | "RATE";

export type NegativeReasonCode =
  | "TOPIC_NOT_INTERESTED"
  | "ALREADY_READ"
  | "TOO_BASIC"
  | "TOO_ADVANCED"
  | "LOW_QUALITY"
  | "NOT_NOW"
  | "REPEATED"
  | "OTHER";

export type DirectBehaviorEventType =
  | "SEARCH"
  | "VIEW_RESOURCE"
  | "VIEW_EXPLANATION"
  | "CLICK_RECOMMENDATION"
  | "ACCESS_PAPER_FULLTEXT";

export interface AgentAction {
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
}

export interface ImpressionInput {
  impression_uuid: string;
  recommendation_item_id: number;
  position: number;
  rendered_at: string;
  visible_started_at?: string;
  visible_ms: number;
  max_visible_ratio: number;
}

export interface ImpressionBatchRequest {
  impressions: ImpressionInput[];
}

export interface ImpressionResult {
  impression_uuid: string;
  status: "ACCEPTED" | "REPLAYED" | "REJECTED";
  is_valid_exposure: boolean;
  error_code?: string;
  agent_action?: AgentAction;
}

export interface ImpressionBatchResponse {
  accepted_count: number;
  replayed_count: number;
  rejected_count: number;
  results: ImpressionResult[];
}

export interface FeedbackRequest {
  feedback_uuid: string;
  impression_uuid?: string;
  feedback_type: FeedbackType;
  reason_code?: NegativeReasonCode;
  rating?: number;
  content?: string;
}

export interface FeedbackReceipt {
  feedback_uuid: string;
  feedback_id: number;
  status: "ACCEPTED" | "APPLIED" | "REPLAYED";
  behavior_event_id: number;
  resource_state?: { state_type: string; suppress_until?: string };
  profile_update_status: "APPLIED" | "PENDING" | "NOT_REQUIRED";
  profile_version_before?: number;
  profile_version_after?: number;
  agent_action?: AgentAction;
}

export interface BehaviorEventRequest {
  event_uuid: string;
  session_id: string;
  task_id?: string;
  event_type: DirectBehaviorEventType;
  resource_id?: number;
  recommendation_item_id?: number;
  impression_uuid?: string;
  query_text?: string;
  dwell_ms?: number;
  position?: number;
  occurred_at: string;
}

export interface BehaviorEventReceipt {
  event_uuid: string;
  event_id: number;
  status: "ACCEPTED" | "APPLIED" | "REPLAYED";
  profile_update_status: "APPLIED" | "PENDING" | "NOT_REQUIRED";
  agent_action?: AgentAction;
}

export interface InteractionClient {
  recordImpressions(
    request: ImpressionBatchRequest,
    options?: { signal?: AbortSignal; idempotencyKey?: string },
  ): Promise<ImpressionBatchResponse>;
  recordFeedback(
    itemId: number,
    request: FeedbackRequest,
    options?: { signal?: AbortSignal },
  ): Promise<FeedbackReceipt>;
  appendBehavior(
    request: BehaviorEventRequest,
    options?: { signal?: AbortSignal },
  ): Promise<BehaviorEventReceipt>;
}

export interface InteractionFailure {
  readonly kind: "interaction_api_error";
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
}

export function isInteractionFailure(value: unknown): value is InteractionFailure {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<InteractionFailure>;
  return (
    candidate.kind === "interaction_api_error" &&
    typeof candidate.status === "number" &&
    typeof candidate.code === "string" &&
    typeof candidate.retryable === "boolean"
  );
}
