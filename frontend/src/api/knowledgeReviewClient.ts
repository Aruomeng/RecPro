import { decodeKnowledgeReview, decodeKnowledgeReviewList } from "../domain/knowledgeReview";
import type { KnowledgeReview, KnowledgeReviewAction, KnowledgeReviewStatus } from "../domain/knowledgeReview";

const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

async function payload(response: Response): Promise<unknown> {
  const value: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(`KNOWLEDGE_REVIEW_HTTP_${response.status}`);
  return value;
}

function headers(token: string): Record<string, string> {
  if (!token) throw new Error("AUTH_ACCESS_TOKEN_REQUIRED");
  return { Accept: "application/json", Authorization: `Bearer ${token}` };
}

export const knowledgeReviewClient = {
  async list(token: string, status?: KnowledgeReviewStatus): Promise<KnowledgeReview[]> {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return decodeKnowledgeReviewList(await payload(await fetch(`${baseUrl}/api/v1/librarian/knowledge-reviews${query}`, { headers: headers(token), cache: "no-store" })));
  },
  async act(token: string, proposalId: string, action: KnowledgeReviewAction, reasonCode: string, idempotencyKey: string): Promise<{ review: KnowledgeReview; replayed: boolean; neo4j_write_count: number }> {
    const value = await payload(await fetch(`${baseUrl}/api/v1/librarian/knowledge-reviews/${encodeURIComponent(proposalId)}/actions`, {
      method: "POST",
      headers: { ...headers(token), "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ action, reason_code: reasonCode }),
    }));
    if (typeof value !== "object" || value === null || !("review" in value) || !("replayed" in value) || !("neo4j_write_count" in value) || typeof value.replayed !== "boolean" || value.neo4j_write_count !== 0) throw new Error("INVALID_KNOWLEDGE_REVIEW_RESPONSE");
    return { review: decodeKnowledgeReview(value.review), replayed: value.replayed, neo4j_write_count: 0 };
  },
};
