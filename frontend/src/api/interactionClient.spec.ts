import { describe, expect, it, vi } from "vitest";

import type { InteractionClient } from "../domain/interaction";
import {
  createInteractionClient,
  InteractionApiError,
} from "./interactionClient";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const impressionResponse = {
  accepted_count: 1,
  replayed_count: 0,
  rejected_count: 0,
  results: [{
    impression_uuid: "00000000-0000-4000-8000-000000000001",
    status: "ACCEPTED",
    is_valid_exposure: true,
    error_code: null,
    agent_action: {
      step_no: null,
      agent_name: "FeedbackLearningAgent",
      agent_version: "feedback-learning-rule-v1",
      message_type: null,
      action: "OBSERVE",
      target: "UserProfileAgent",
      reason_code: "IMPRESSION_RECORDED",
      confidence: 1,
      parameters: {},
      evidence_refs: [],
    },
  }],
};

describe("interactionClient", () => {
  it("posts an impression with an explicit idempotency key and demo identity", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse(impressionResponse));
    const client = createInteractionClient({ baseUrl: "http://backend:8000/", fetcher, demoUserId: 1001 });

    await expect(client.recordImpressions({
      impressions: [{
        impression_uuid: "00000000-0000-4000-8000-000000000001",
        recommendation_item_id: 129,
        position: 1,
        rendered_at: "2030-01-20T12:05:00.000Z",
        visible_started_at: "2030-01-20T12:05:00.000Z",
        visible_ms: 1500,
        max_visible_ratio: 0.8,
      }],
    }, { idempotencyKey: "g5-impression-0001" })).resolves.toMatchObject({ accepted_count: 1 });

    expect(fetcher).toHaveBeenCalledWith(
      "http://backend:8000/api/v1/recommendation-impressions/batch",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Idempotency-Key": "g5-impression-0001",
          "X-Demo-User-Id": "1001",
        }),
      }),
    );
  });

  it("binds feedback and direct behavior idempotency keys to their UUIDs", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(jsonResponse({
        feedback_uuid: "00000000-0000-4000-8000-000000000002",
        feedback_id: 1,
        status: "ACCEPTED",
        behavior_event_id: 2,
        profile_update_status: "PENDING",
        resource_state: { state_type: "HIDDEN" },
      }))
      .mockResolvedValueOnce(jsonResponse({
        event_uuid: "00000000-0000-4000-8000-000000000003",
        event_id: 3,
        status: "ACCEPTED",
        profile_update_status: "PENDING",
      }));
    const client: InteractionClient = createInteractionClient({ fetcher });

    await client.recordFeedback(129, {
      feedback_uuid: "00000000-0000-4000-8000-000000000002",
      impression_uuid: "00000000-0000-4000-8000-000000000001",
      feedback_type: "NOT_INTERESTED",
      reason_code: "TOPIC_NOT_INTERESTED",
    });
    await client.appendBehavior({
      event_uuid: "00000000-0000-4000-8000-000000000003",
      session_id: "00000000-0000-4000-8000-000000000004",
      event_type: "CLICK_RECOMMENDATION",
      resource_id: 6850,
      recommendation_item_id: 129,
      impression_uuid: "00000000-0000-4000-8000-000000000001",
      occurred_at: "2030-01-20T12:06:00.000Z",
    });

    expect(fetcher.mock.calls[0][1]).toEqual(expect.objectContaining({
      headers: expect.objectContaining({ "Idempotency-Key": "00000000-0000-4000-8000-000000000002" }),
    }));
    expect(fetcher.mock.calls[1][1]).toEqual(expect.objectContaining({
      headers: expect.objectContaining({ "Idempotency-Key": "00000000-0000-4000-8000-000000000003" }),
    }));
  });

  it("rejects an invalid success response through the typed error boundary", async () => {
    const client = createInteractionClient({
      fetcher: vi.fn().mockResolvedValue(jsonResponse({ status: "ACCEPTED" })),
    });

    await expect(client.appendBehavior({
      event_uuid: "00000000-0000-4000-8000-000000000003",
      session_id: "00000000-0000-4000-8000-000000000004",
      event_type: "VIEW_RESOURCE",
      resource_id: 6850,
      occurred_at: "2030-01-20T12:06:00.000Z",
    })).rejects.toBeInstanceOf(InteractionApiError);
  });
});
