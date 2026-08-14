import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import type { RecommendationClient } from "../domain/recommendation";
import RecommendationWorkbench from "./RecommendationWorkbench.vue";

const response = {
  task_id: "00000000-0000-4000-8000-000000000001",
  trace_id: "00000000-0000-4000-8000-000000000002",
  status: "COMPLETED" as const,
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
  items: [{
    item_id: 12,
    rank_no: 1,
    reason_summary: "主题匹配",
    evidence_confidence: 0.9,
    unavailable_now: false,
    resource: {
      resource_id: 42,
      resource_type: "BOOK" as const,
      title: "真实接口返回的书",
      authors: ["作者"],
      publication_year: 2025,
      availability_status: "AVAILABLE_BORROW" as const,
    },
  }],
  warnings: [],
};

const waitingResponse = {
  ...response,
  status: "WAITING_CLARIFICATION" as const,
  questions: [{
    slot: "resource_types",
    question: "你需要哪类资源？",
    options: ["BOOK", "PAPER"],
    required: true,
  }],
};

describe("RecommendationWorkbench", () => {
  it("keeps the real request disabled and makes the local demo boundary explicit", async () => {
    const createTask = vi.fn();
    const wrapper = mount(RecommendationWorkbench, {
      props: { pipelineEnabled: false, client: { createTask } as unknown as RecommendationClient },
    });

    await wrapper.find("form").trigger("submit");
    expect(createTask).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("真实推荐接口");

    await wrapper.find("button.secondary-action").trigger("click");
    expect(wrapper.text()).toContain("本地演示推荐");
    expect(wrapper.text()).toContain("不访问 API");
    expect(createTask).not.toHaveBeenCalled();
  });

  it("renders validated API results when the composition root explicitly enables the pipeline", async () => {
    const client: RecommendationClient = {
      createTask: vi.fn().mockResolvedValue(response),
      submitClarification: vi.fn(),
    };
    const wrapper = mount(RecommendationWorkbench, {
      props: { pipelineEnabled: true, client },
    });

    await wrapper.find("form").trigger("submit");
    expect(client.createTask).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("真实接口");
    expect(wrapper.text()).toContain("真实接口返回的书");
    expect(wrapper.text()).toContain("主题匹配");
  });

  it("sends the explicitly selected output form to the recommendation API", async () => {
    const createTask = vi.fn().mockResolvedValue(response);
    const wrapper = mount(RecommendationWorkbench, {
      props: { pipelineEnabled: true, client: { createTask, submitClarification: vi.fn() } as unknown as RecommendationClient },
    });

    await wrapper.get("#output-type").setValue("READING_PATH");
    await wrapper.find("form").trigger("submit");

    expect(createTask).toHaveBeenCalledWith(
      expect.objectContaining({ requested_output_type: "READING_PATH" }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("continues a waiting task with the same client port and an abort signal", async () => {
    const submitClarification = vi.fn().mockResolvedValue(response);
    const client: RecommendationClient = {
      createTask: vi.fn().mockResolvedValue(waitingResponse),
      submitClarification,
    };
    const wrapper = mount(RecommendationWorkbench, {
      props: { pipelineEnabled: true, client },
    });

    await wrapper.find("form").trigger("submit");
    await wrapper.find(".clarification-question select").setValue("BOOK");
    await wrapper.find(".clarification-panel .primary-action").trigger("click");

    expect(submitClarification).toHaveBeenCalledTimes(1);
    expect(submitClarification.mock.calls[0][0]).toBe(waitingResponse.task_id);
    expect(submitClarification.mock.calls[0][1]).toBe(1);
    expect(submitClarification.mock.calls[0][2]).toEqual({ resource_types: "BOOK" });
    expect(submitClarification.mock.calls[0][4]).toEqual(expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(wrapper.text()).toContain("真实接口");
  });
});
