import { describe, expect, it } from "vitest";

import { decodeRecommendationExecution, isRecommendationExecution, isUuid, RecommendationDecodeError } from "./recommendation";
import realCompletedFixture from "../fixtures/recommendation-completed-public.json";

describe("recommendation identity", () => {
  it("accepts deterministic UUIDv5 identities used by approved replay plans", () => {
    expect(isUuid("f343aa37-5020-5276-aa90-0decd9692c91")).toBe(true);
    expect(isUuid("55848636-0fd0-5621-a5b4-6d4821a26b65")).toBe(true);
  });

  it("still accepts browser-generated UUIDv4 identities and rejects malformed values", () => {
    expect(isUuid("773bcfaa-5faf-4b17-95ae-44c4f747d60c")).toBe(true);
    expect(isUuid("not-a-uuid")).toBe(false);
  });
});

describe("recommendation execution contract", () => {
  it("accepts the sanitized public response captured from the persisted real replay", () => {
    const decoded = decodeRecommendationExecution(realCompletedFixture);
    expect(decoded.task_id).toBe("228c1064-7267-54f1-a68b-6584c11dae51");
    expect(decoded.items).toHaveLength(8);
    expect(decoded.items?.every((item) => item.evidence === null)).toBe(true);
  });
  it("accepts nullable optional fields emitted by the real FastAPI response", () => {
    expect(isRecommendationExecution({
      task_id: "208f35ac-80ae-54ea-93ab-458e6a3b6bd4",
      trace_id: "ccad4c86-8951-52cb-82af-de7e56c68201",
      status: "COMPLETED",
      context_version: 1,
      decision: {
        output_type: "TOPIC_RESOURCES",
        delivery_strategy: "DIRECT",
        explanation_level: "EVIDENCE",
        adaptation_state: "NORMAL",
        decision_reason_codes: ["DIRECT_PATH"],
        decision_reason: "输入和资源覆盖满足直接推荐条件。",
        policy_version: "policy-rule-v1",
      },
      items: [{
        item_id: 324,
        resource: {
          resource_id: 6452,
          resource_type: "BOOK",
          title: "智慧图书馆服务模式与阅读推广研究",
          authors: ["吴飞", "杨倩"],
          publication_year: 2024,
          availability_status: "REFERENCE_ONLY",
          difficulty_level: null,
        },
        rank_no: 1,
        reason_summary: "根据已验证证据生成推荐解释。",
        evidence_confidence: 0.82,
        unavailable_now: false,
        evidence: {
          score: 0.65,
          channels: ["MYSQL", "VECTOR"],
          channel_scores: { MYSQL: 0.6, VECTOR: 0.8 },
          channel_ranks: { MYSQL: 1, VECTOR: 2 },
          primary_channel: "VECTOR",
          evidence_refs: ["catalog:resource:6452:metadata:1"],
          negative_penalty: 0,
        },
      }],
      questions: null,
      warnings: [],
    })).toBe(true);
  });

  it("reports the exact invalid public field path without exposing a payload", () => {
    const malformed = {
      task_id: "208f35ac-80ae-54ea-93ab-458e6a3b6bd4", trace_id: "ccad4c86-8951-52cb-82af-de7e56c68201",
      status: "COMPLETED", context_version: 1,
      decision: { output_type: "TOPIC_RESOURCES", delivery_strategy: "DIRECT", explanation_level: "EVIDENCE", adaptation_state: "NORMAL", decision_reason_codes: ["DIRECT_PATH"], decision_reason: "ok", policy_version: "v1" },
      warnings: [],
      items: [{ item_id: 1, rank_no: 1, reason_summary: "依据", evidence_confidence: "0.8", unavailable_now: false, resource: { resource_id: 1, resource_type: "BOOK", title: "书", authors: [], availability_status: "AVAILABLE_BORROW" } }],
    };
    try { decodeRecommendationExecution(malformed); throw new Error("decoder unexpectedly accepted malformed result"); }
    catch (error) {
      expect(error).toBeInstanceOf(RecommendationDecodeError);
      expect((error as RecommendationDecodeError).path).toBe("$.items[0].evidence_confidence");
      expect((error as RecommendationDecodeError).expected).toContain("finite number");
      expect((error as RecommendationDecodeError).actualType).toBe("string");
    }
  });
});
