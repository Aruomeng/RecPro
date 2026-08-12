import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import type { InteractionClient } from "../domain/interaction";
import InteractionPanel from "./InteractionPanel.vue";

const item = {
  item_id: 129,
  rank_no: 1,
  reason_summary: "主题匹配",
  evidence_confidence: 0.9,
  unavailable_now: false,
  resource: {
    resource_id: 6850,
    resource_type: "BOOK" as const,
    title: "智慧图书馆与阅读推广",
    authors: ["作者"],
    availability_status: "AVAILABLE_BORROW" as const,
  },
};

function createClient(): InteractionClient {
  return {
    recordImpressions: vi.fn().mockResolvedValue({
      accepted_count: 1,
      replayed_count: 0,
      rejected_count: 0,
      results: [{
        impression_uuid: "00000000-0000-4000-8000-000000000001",
        status: "ACCEPTED",
        is_valid_exposure: true,
      }],
    }),
    recordFeedback: vi.fn().mockResolvedValue({
      feedback_uuid: "00000000-0000-4000-8000-000000000002",
      feedback_id: 1,
      status: "ACCEPTED",
      behavior_event_id: 2,
      profile_update_status: "PENDING",
    }),
    appendBehavior: vi.fn().mockResolvedValue({
      event_uuid: "00000000-0000-4000-8000-000000000003",
      event_id: 3,
      status: "ACCEPTED",
      profile_update_status: "PENDING",
    }),
  };
}

describe("InteractionPanel", () => {
  it("does not call the interaction port while the opt-in boundary is disabled", async () => {
    const client = createClient();
    const wrapper = mount(InteractionPanel, {
      props: {
        items: [item],
        sessionId: "00000000-0000-4000-8000-000000000004",
        enabled: false,
        client,
      },
    });

    await wrapper.get("button").trigger("click");
    expect(client.recordImpressions).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("交互 API 默认关闭");
  });

  it("requires an impression before feedback and behavior, then keeps all three ports explicit", async () => {
    const client = createClient();
    const wrapper = mount(InteractionPanel, {
      props: {
        items: [item],
        taskId: "00000000-0000-4000-8000-000000000005",
        sessionId: "00000000-0000-4000-8000-000000000004",
        enabled: true,
        client,
      },
    });
    const buttons = () => wrapper.findAll(".interaction-panel__actions button");

    await buttons()[1].trigger("click");
    expect(client.recordFeedback).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("请先记录曝光");

    await buttons()[0].trigger("click");
    await buttons()[1].trigger("click");
    await buttons()[2].trigger("click");

    expect(client.recordImpressions).toHaveBeenCalledTimes(1);
    expect(client.recordFeedback).toHaveBeenCalledTimes(1);
    expect(client.appendBehavior).toHaveBeenCalledTimes(1);
    expect(client.appendBehavior).toHaveBeenCalledWith(
      expect.objectContaining({
        event_type: "CLICK_RECOMMENDATION",
        recommendation_item_id: 129,
        resource_id: 6850,
        impression_uuid: "00000000-0000-4000-8000-000000000001",
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });
});
