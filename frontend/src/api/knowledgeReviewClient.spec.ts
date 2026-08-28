import { afterEach, describe, expect, it, vi } from "vitest";
import { knowledgeReviewClient } from "./knowledgeReviewClient";

afterEach(() => vi.unstubAllGlobals());

const review = {
  proposal_uuid: "dbc6d4be-3f59-5c0a-bf81-c9b220ff0588",
  proposal_type: "WORK_IDENTITY_REVIEW",
  graph_version: "lib-books-v2-20260828",
  subject_id: "book:1",
  relation_type: "INSTANCE_OF",
  object_id: "UNRESOLVED_WORK",
  source_refs: ["graph:v2:book:1"],
  reason_codes: ["WORK_ISBN_CONFLICT"],
  confidence: 0.6,
  agent_name: "ResourceSemanticAgent",
  task_id: null,
  workspace_id: null,
  idempotency_sha256: "a".repeat(64),
  occurred_at: "2026-08-28T00:00:00+08:00",
  status: "PENDING",
  actions: [],
};

describe("knowledge review client", () => {
  it("requires bearer auth and strictly decodes bounded proposals", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [review] }), { status: 200, headers: { "Content-Type": "application/json" } })));
    const result = await knowledgeReviewClient.list("token");
    expect(result[0].agent_name).toBe("ResourceSemanticAgent");
    const call = vi.mocked(fetch).mock.calls[0];
    expect((call[1]?.headers as Record<string, string>).Authorization).toBe("Bearer token");
  });

  it("rejects an unbounded review list", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: Array.from({ length: 101 }, () => review) }), { status: 200, headers: { "Content-Type": "application/json" } })));
    await expect(knowledgeReviewClient.list("token")).rejects.toThrow("INVALID_KNOWLEDGE_REVIEW_RESPONSE");
  });

  it("requires action responses to prove zero Neo4j writes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ review, replayed: false, neo4j_write_count: 1 }), { status: 200, headers: { "Content-Type": "application/json" } })));
    await expect(knowledgeReviewClient.act("token", review.proposal_uuid, "APPROVE", "EVIDENCE_ACCEPTED", "action-key-1")).rejects.toThrow("INVALID_KNOWLEDGE_REVIEW_RESPONSE");
  });
});
