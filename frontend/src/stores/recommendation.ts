import { computed, ref, watch } from "vue";
import { defineStore } from "pinia";

import { recommendationRunClient } from "../api/recommendationRunClient";
import type { AgentProgressEvent, RunAccepted } from "../api/recommendationRunClient";
import type { RecommendationExecution, RecommendationOutputType } from "../domain/recommendation";
import { createRequestId } from "../domain/recommendation";
import { useSessionStore } from "./session";
import { useAgentWorkspaceStore } from "./agentWorkspace";

export const AGENT_ROLES = [
  ["IntentUnderstandingAgent", "意图理解"], ["UserProfileAgent", "用户画像"],
  ["ResourceSemanticAgent", "语义探测"], ["RecommendationPolicyAgent", "策略规划"],
  ["CandidateRecallAgent", "候选召回"], ["RankingAgent", "排序重排"],
  ["ExplanationAgent", "证据解释"], ["FeedbackLearningAgent", "反馈学习"],
] as const;

export const useRecommendationStore = defineStore("recommendation", () => {
  const session = useSessionStore();
  const workspace = useAgentWorkspaceStore();
  const query = ref("多智能体系统与智慧图书馆");
  const outputType = ref<RecommendationOutputType>("TOPIC_RESOURCES");
  const phase = ref<"idle" | "starting" | "streaming" | "clarification" | "success" | "error">("idle");
  const run = ref<RunAccepted | null>(null);
  const result = ref<RecommendationExecution | null>(null);
  const events = ref<AgentProgressEvent[]>([]);
  const error = ref("");
  const answers = ref<Record<string, string>>({});
  let controller: AbortController | undefined;

  const items = computed(() => result.value?.items ?? []);
  const agentStates = computed(() => Object.fromEntries(AGENT_ROLES.map(([name]) => {
    const related = events.value.filter((event) => event.agent_name === name);
    const latest = related.at(-1);
    let state = "waiting";
    if (latest?.event_type === "AGENT_STARTED") state = "working";
    if (latest?.event_type === "AGENT_COMPLETED") state = latest.outcome === "FAILED" ? "failed" : latest.fallback_used ? "degraded" : "complete";
    return [name, { state, event: latest }];
  })));

  async function consume(accepted: RunAccepted): Promise<void> {
    run.value = accepted;
    phase.value = "streaming";
    await recommendationRunClient.stream(accepted, session.userId, (event) => {
      events.value.push(event);
      if (event.event_type === "TASK_FAILED") error.value = `协作任务失败：${event.error_code ?? "UNKNOWN"}`;
    }, controller?.signal);
    const state = await recommendationRunClient.state(accepted.task_id, session.userId);
    if (state.result) {
      result.value = state.result;
      phase.value = state.result.status === "WAITING_CLARIFICATION" ? "clarification" : "success";
    } else if (state.error_code) {
      phase.value = "error";
      error.value = `协作任务失败：${state.error_code}`;
    }
  }

  async function start(selectedOutput = outputType.value): Promise<void> {
    const input = query.value.trim();
    if (!input) { error.value = "请输入想探索的主题。"; return; }
    controller?.abort();
    controller = new AbortController();
    outputType.value = selectedOutput;
    phase.value = "starting";
    result.value = null;
    events.value = [];
    answers.value = {};
    error.value = "";
    session.setBusy(true);
    try {
      await workspace.observe("QUERY_SUBMITTED", { query: input, output_type: selectedOutput });
      await workspace.observe("RECOMMENDATION_STARTED", { query: input, output_type: selectedOutput });
      const accepted = await recommendationRunClient.create({
        request_id: createRequestId(), session_id: session.sessionId, scene: "SEARCH_AFTER", input_text: input,
        requested_resource_types: ["BOOK"], requested_output_type: selectedOutput, limit: selectedOutput === "READING_PATH" ? 8 : 8,
        constraints: { personalization_mode: session.mode === "demo" ? "PROFILE" : "ANONYMOUS" },
      }, session.userId, controller.signal, workspace.workspaceId);
      await consume(accepted);
    } catch (caught) {
      if (!controller.signal.aborted) { phase.value = "error"; error.value = caught instanceof Error ? caught.message : "推荐任务暂时失败。"; }
    } finally { session.setBusy(false); }
  }

  async function clarify(): Promise<void> {
    if (!result.value) return;
    session.setBusy(true);
    controller = new AbortController();
    try {
      const accepted = await recommendationRunClient.clarify(result.value.task_id, result.value.context_version, answers.value, createRequestId(), session.userId, workspace.workspaceId);
      events.value = [];
      await consume(accepted);
    } catch (caught) { phase.value = "error"; error.value = caught instanceof Error ? caught.message : "澄清提交失败。"; }
    finally { session.setBusy(false); }
  }

  function clear(): void { controller?.abort(); phase.value = "idle"; run.value = null; result.value = null; events.value = []; answers.value = {}; error.value = ""; }
  watch(() => session.resetEpoch, clear);

  return { query, outputType, phase, run, result, events, error, answers, items, agentStates, start, clarify, clear };
});
