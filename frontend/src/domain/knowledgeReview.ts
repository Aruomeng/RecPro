export type KnowledgeReviewStatus = "PENDING" | "APPROVED" | "REJECTED" | "EVIDENCE_REQUESTED";
export type KnowledgeReviewAction = "APPROVE" | "REJECT" | "REQUEST_EVIDENCE";

export interface KnowledgeReviewActionFact {
  fact_uuid: string;
  version: number;
  action: KnowledgeReviewAction;
  librarian_user_id: number;
  reason_code: string;
  occurred_at: string;
}

export interface KnowledgeReview {
  proposal_uuid: string;
  proposal_type: string;
  graph_version: string;
  subject_id: string;
  relation_type: string;
  object_id: string;
  source_refs: string[];
  reason_codes: string[];
  confidence: number;
  agent_name: string;
  task_id?: string;
  workspace_id?: string;
  idempotency_sha256: string;
  occurred_at: string;
  status: KnowledgeReviewStatus;
  actions: KnowledgeReviewActionFact[];
}

function record(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function text(value: unknown): value is string { return typeof value === "string" && value.length > 0; }
function strings(value: unknown, max: number): value is string[] { return Array.isArray(value) && value.length > 0 && value.length <= max && value.every(text); }
const statuses = new Set(["PENDING", "APPROVED", "REJECTED", "EVIDENCE_REQUESTED"]);
const actions = new Set(["APPROVE", "REJECT", "REQUEST_EVIDENCE"]);

export function decodeKnowledgeReview(value: unknown): KnowledgeReview {
  if (!record(value) || !text(value.proposal_uuid) || !text(value.proposal_type) || !text(value.graph_version) ||
    !text(value.subject_id) || !text(value.relation_type) || !text(value.object_id) || !strings(value.source_refs, 20) ||
    !strings(value.reason_codes, 8) || typeof value.confidence !== "number" || value.confidence < 0 || value.confidence > 1 ||
    !text(value.agent_name) || !text(value.idempotency_sha256) || value.idempotency_sha256.length !== 64 ||
    !text(value.occurred_at) || !text(value.status) || !statuses.has(value.status) || !Array.isArray(value.actions) ||
    !value.actions.every((item) => record(item) && text(item.fact_uuid) && Number.isInteger(item.version) && Number(item.version) > 0 && text(item.action) && actions.has(item.action) && Number.isInteger(item.librarian_user_id) && Number(item.librarian_user_id) > 0 && text(item.reason_code) && text(item.occurred_at))) {
    throw new Error("INVALID_KNOWLEDGE_REVIEW_RESPONSE");
  }
  return value as unknown as KnowledgeReview;
}

export function decodeKnowledgeReviewList(value: unknown): KnowledgeReview[] {
  if (!record(value) || !Array.isArray(value.items) || value.items.length > 100) throw new Error("INVALID_KNOWLEDGE_REVIEW_RESPONSE");
  return value.items.map(decodeKnowledgeReview);
}
