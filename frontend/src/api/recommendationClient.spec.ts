import { describe, expect, it, vi } from "vitest";

import {
  createRecommendationClient,
  RecommendationApiError,
} from "./recommendationClient";
import type { RecommendationClient } from "../domain/recommendation";

const execution = {
  task_id: "00000000-0000-4000-8000-000000000001",
  trace_id: "00000000-0000-4000-8000-000000000002",
  status: "COMPLETED",
  context_version: 1,
  decision: {
    output_type: "TOPIC_RESOURCES",
    delivery_strategy: "DIRECT",
    explanation_level: "SUMMARY",
    adaptation_state: "NORMAL",
    decision_reason_codes: ["TOPIC"],
    decision_reason: "topic",
    policy_version: "policy-g3-v1",
  },
  items: [],
  warnings: [],
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("recommendationClient", () => {
  it("posts a typed task with idempotency and demo identity headers", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse(execution));
    const client: RecommendationClient = createRecommendationClient({ baseUrl: "http://backend:8000/", fetcher, demoUserId: 1001 });

    await expect(client.createTask({
      request_id: "00000000-0000-4000-8000-000000000003",
      session_id: "00000000-0000-4000-8000-000000000004",
      scene: "SEARCH_AFTER",
      input_text: "多智能体",
      requested_resource_types: ["BOOK"],
      requested_output_type: "TOPIC_RESOURCES",
      limit: 6,
    })).resolves.toMatchObject({ status: "COMPLETED" });

    expect(fetcher).toHaveBeenCalledWith(
      "http://backend:8000/api/v1/recommendation-tasks",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Idempotency-Key": "00000000-0000-4000-8000-000000000003",
          "X-Demo-User-Id": "1001",
        }),
        body: expect.stringContaining('"requested_output_type":"TOPIC_RESOURCES"'),
      }),
    );
  });

  it("preserves a stable disabled-pipeline error code", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({
      error: {
        code: "CORE_STORAGE_UNAVAILABLE",
        message: "localized server text",
        details: { recommendation_pipeline: "DISABLED" },
        retryable: false,
      },
      request_id: "00000000-0000-4000-8000-000000000003",
      trace_id: "00000000-0000-4000-8000-000000000004",
    }, 503));
    const client = createRecommendationClient({ fetcher });

    const error = await client.createTask({
      request_id: "00000000-0000-4000-8000-000000000003",
      session_id: "00000000-0000-4000-8000-000000000004",
      scene: "SEARCH_AFTER",
      input_text: "多智能体",
      requested_resource_types: ["BOOK"],
      requested_output_type: "TOPIC_RESOURCES",
      limit: 6,
    }).catch((reason: unknown) => reason);

    expect(error).toBeInstanceOf(RecommendationApiError);
    expect(error).toMatchObject({ status: 503, code: "CORE_STORAGE_UNAVAILABLE", retryable: false });
  });

  it("rejects a success payload that does not contain the task contract", async () => {
    const client = createRecommendationClient({
      fetcher: vi.fn().mockResolvedValue(jsonResponse({ status: "COMPLETED" })),
    });

    await expect(client.createTask({
      request_id: "00000000-0000-4000-8000-000000000003",
      session_id: "00000000-0000-4000-8000-000000000004",
      scene: "SEARCH_AFTER",
      input_text: "多智能体",
      requested_resource_types: ["BOOK"],
      requested_output_type: "TOPIC_RESOURCES",
      limit: 6,
    })).rejects.toMatchObject({
      code: "INVALID_RUN_RESULT",
      details: { path: "$.task_id" },
    });
  });
});
