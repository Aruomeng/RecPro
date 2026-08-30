import { computed, ref, watch } from "vue";
import { defineStore } from "pinia";

import { agentWorkspaceClient } from "../api/agentWorkspaceClient";
import type { AgentWorkspaceSnapshot, InteractionDirective, WorkspaceAgent, WorkspaceEvent, WorkspaceObservationType } from "../domain/agentWorkspace";
import { useSessionStore } from "./session";
import { useAuthStore } from "./auth";

export const useAgentWorkspaceStore = defineStore("agentWorkspace", () => {
  const session = useSessionStore();
  const auth = useAuthStore();
  const workspaceId = ref("");
  const state = ref<"idle" | "connecting" | "online" | "degraded">("idle");
  const expanded = ref(false);
  const snapshot = ref<AgentWorkspaceSnapshot | null>(null);
  const agents = ref<WorkspaceAgent[]>([]);
  const events = ref<WorkspaceEvent[]>([]);
  const directives = ref<InteractionDirective[]>([]);
  const sources = ref<AgentWorkspaceSnapshot["sources"]>([]);
  const selectedAgentName = ref("RecommendationPolicyAgent");
  const error = ref("");
  let streamController: AbortController | undefined;
  let generation = 0;

  const activeCount = computed(() => agents.value.filter((agent) => ["OBSERVING", "PLANNING", "WORKING"].includes(agent.state)).length);
  const degradedCount = computed(() => agents.value.filter((agent) => ["DEGRADED", "FAILED"].includes(agent.state)).length);
  const selectedAgent = computed(() => agents.value.find((agent) => agent.name === selectedAgentName.value) ?? agents.value[0]);
  const suggestions = computed(() => directives.value.filter((directive) => directive.status === "PROPOSED" && directive.behavior === "SUGGESTION"));
  const notices = computed(() => directives.value.filter((directive) => directive.status !== "DISMISSED" && directive.type === "SHOW_DEGRADED_NOTICE"));
  const suggestedTopics = computed(() => {
    const directive = [...directives.value].reverse().find((item) => item.type === "SUGGEST_TOPICS" && ["PROPOSED", "AUTO_APPLIED", "ACCEPTED"].includes(item.status));
    return Array.isArray(directive?.payload.topics) ? directive.payload.topics.filter((item): item is string => typeof item === "string").slice(0, 6) : [];
  });
  const latestEvent = computed(() => events.value.at(-1));
  const contextVersion = computed(() => snapshot.value?.context_version ?? latestEvent.value?.context_version ?? 0);
  const currentObservation = computed(() => snapshot.value?.orchestrator.current_observation ?? null);
  const guidanceMessage = computed(() => {
    const value = [...directives.value].reverse().find((item) => item.type === "SHOW_GUIDANCE" && ["AUTO_APPLIED", "ACCEPTED"].includes(item.status));
    return typeof value?.payload.message === "string" ? value.payload.message : "Agent 会在不打断操作的前提下提供下一步建议。";
  });
  const explanationDensity = computed(() => {
    const value = [...directives.value].reverse().find((item) => item.type === "SET_EXPLANATION_DENSITY" && ["AUTO_APPLIED", "ACCEPTED"].includes(item.status));
    return value?.payload.density === "DETAILED" ? "DETAILED" : "BALANCED";
  });
  const primaryEntry = computed(() => {
    const value = [...directives.value].reverse().find((item) => item.type === "SET_PRIMARY_ENTRY" && ["AUTO_APPLIED", "ACCEPTED"].includes(item.status));
    return { route: typeof value?.payload.route === "string" ? value.payload.route : "/recommend", label: typeof value?.payload.label === "string" ? value.payload.label : "开始智能推荐" };
  });
  const preferredOutputType = computed(() => {
    const value = [...directives.value].reverse().find((item) => item.type === "PREFER_OUTPUT_TYPE" && item.status === "PROPOSED");
    return typeof value?.payload.output_type === "string" ? value.payload.output_type : null;
  });

  function applySnapshot(next: AgentWorkspaceSnapshot): void {
    snapshot.value = next;
    workspaceId.value = next.workspace_id;
    agents.value = next.agents;
    events.value = next.recent_events.slice(-80);
    directives.value = next.directives;
    sources.value = next.sources;
  }

  function clearRuntimeState(): void {
    workspaceId.value = "";
    snapshot.value = null;
    agents.value = [];
    events.value = [];
    directives.value = [];
    sources.value = [];
  }

  function applyEvent(event: WorkspaceEvent): void {
    if (events.value.some((item) => item.sequence === event.sequence)) return;
    events.value = [...events.value, event].slice(-80);
    if (event.directive) directives.value = [...directives.value.filter((item) => item.directive_id !== event.directive?.directive_id), event.directive];
    if (event.event_type === "DIRECTIVE_ACTIONED" && typeof event.directive_id === "string") {
      const status = event.action === "ACCEPT" ? "ACCEPTED" : event.action === "DISMISS" ? "DISMISSED" : event.action === "UNDO" ? "UNDONE" : undefined;
      if (status) directives.value = directives.value.map((directive) => directive.directive_id === event.directive_id ? { ...directive, status, updated_at: event.occurred_at } : directive);
    }
    if (event.event_type === "DIRECTIVE_EXPIRED" && typeof event.directive_id === "string") {
      directives.value = directives.value.map((directive) => directive.directive_id === event.directive_id ? { ...directive, status: "EXPIRED", updated_at: event.occurred_at } : directive);
    }
    const nestedType = event.event_type === "RECOMMENDATION_EVENT" && typeof event.recommendation_event_type === "string"
      ? event.recommendation_event_type
      : event.event_type;
    const isAgentStateEvent = ["AGENT_STARTED", "AGENT_COMPLETED", "AGENT_FAILED", "RECOMMENDATION_HISTORY_REPLAY"].includes(nestedType);
    if (event.agent_name && isAgentStateEvent) {
      agents.value = agents.value.map((agent) => {
        if (agent.name !== event.agent_name) return agent;
        const state = nestedType === "AGENT_STARTED"
          ? "WORKING"
          : nestedType === "AGENT_FAILED" || event.outcome === "FAILED" ? "FAILED"
          : event.fallback_used || ["DEGRADED", "PARTIAL"].includes(String(event.outcome)) ? "DEGRADED" : "COMPLETED";
        return {
          ...agent, state,
          last_action: typeof event.action === "string" ? event.action : agent.last_action,
          target: typeof event.target === "string" ? event.target : agent.target,
          reason_code: typeof event.reason_code === "string" ? event.reason_code : agent.reason_code,
          confidence: typeof event.confidence === "number" ? event.confidence : agent.confidence,
          duration_ms: typeof event.duration_ms === "number" ? event.duration_ms : agent.duration_ms,
          evidence_refs: Array.isArray(event.evidence_refs) ? event.evidence_refs.filter((item): item is string => typeof item === "string") : agent.evidence_refs,
          updated_at: event.occurred_at,
        };
      });
    }
    if (event.event_type === "OBSERVATION_FAILED") state.value = "degraded";
    if (event.event_type === "RECOMMENDATION_COMPLETED") state.value = "online";
    if (snapshot.value) {
      const orchestratorState = event.event_type === "RECOMMENDATION_COMPLETED"
        ? (event.status === "FAILED" ? "FAILED" : "COMPLETED")
        : event.event_type === "OBSERVATION_FAILED"
          ? "DEGRADED"
          : event.event_type === "OBSERVATION_COMPLETED"
            ? ["FAILED", "DEGRADED"].includes(String(event.outcome)) ? "DEGRADED" : "OBSERVING"
          : event.event_type === "OBSERVATION_SUPERSEDED"
            ? "OBSERVING"
            : event.event_type === "AGENT_STARTED" || event.event_type === "OBSERVATION_ACCEPTED" || nestedType === "AGENT_STARTED"
              ? "WORKING" : snapshot.value.orchestrator.state;
      const currentObservation = event.event_type === "OBSERVATION_ACCEPTED"
        ? { event_type: event.observation_type, context_version: event.context_version, status: "QUEUED" }
        : event.event_type === "OBSERVATION_COMPLETED"
          ? { event_type: event.observation_type, context_version: event.context_version, status: ["FAILED", "DEGRADED"].includes(String(event.outcome)) ? String(event.outcome) : "COMPLETED" }
          : event.event_type === "OBSERVATION_FAILED"
            ? { event_type: event.observation_type, context_version: event.context_version, status: "FAILED" }
            : snapshot.value.orchestrator.current_observation;
      snapshot.value = {
        ...snapshot.value,
        context_version: Math.max(snapshot.value.context_version, event.context_version),
        agents: agents.value,
        directives: directives.value,
        recent_events: events.value.slice(-40),
        orchestrator: { ...snapshot.value.orchestrator, state: orchestratorState, current_observation: currentObservation },
      };
    }
  }

  async function initialize(): Promise<void> {
    const token = ++generation;
    streamController?.abort();
    streamController = new AbortController();
    clearRuntimeState();
    state.value = "connecting";
    error.value = "";
    try {
      const created = await agentWorkspaceClient.create(session.sessionId, session.mode, auth.requestIdentity);
      if (token !== generation) return;
      applySnapshot(created.workspace);
      state.value = "online";
      void agentWorkspaceClient.stream(created.events_url, created.workspace.workspace_id, () => auth.requestIdentity, applyEvent, streamController.signal, auth.refresh).catch((caught) => {
        if (!streamController?.signal.aborted) { state.value = "degraded"; error.value = caught instanceof Error ? caught.message : "Agent 事件流已断开"; }
      });
    } catch (caught) {
      if (token !== generation) return;
      state.value = "degraded";
      error.value = caught instanceof Error ? caught.message : "Agent Workspace 暂不可用";
    }
  }

  async function observe(type: WorkspaceObservationType, payload: Record<string, unknown> = {}): Promise<void> {
    if (!workspaceId.value) return;
    try {
      applySnapshot(await agentWorkspaceClient.observe(workspaceId.value, type, payload, auth.requestIdentity));
      state.value = "online";
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : "情境观察未送达";
      state.value = "degraded";
    }
  }

  async function action(directive: InteractionDirective, value: "ACCEPT" | "DISMISS" | "UNDO"): Promise<void> {
    if (!workspaceId.value) return;
    try {
      const updated = await agentWorkspaceClient.action(workspaceId.value, directive.directive_id, value, auth.requestIdentity);
      directives.value = directives.value.map((item) => item.directive_id === updated.directive_id ? updated : item);
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : "交互策略处理失败";
      throw caught;
    }
  }

  function selectAgent(name: string): void { selectedAgentName.value = name; expanded.value = true; }
  function stop(): void { generation += 1; streamController?.abort(); streamController = undefined; state.value = "idle"; }

  watch(() => [session.sessionId, session.mode, session.userId, auth.accessToken] as const, () => {
    // The application shell owns initial startup. Once started, identity and
    // session changes reconnect the same global workspace automatically.
    if (state.value !== "idle") void initialize();
  });
  watch(() => auth.canUsePersonalization, (enabled, previous) => {
    if (enabled === previous || !workspaceId.value || snapshot.value?.mode !== "authenticated") return;
    // Re-evaluate the same session context after a consent change. The API
    // derives the effective flag from the current Bearer principal, so this
    // observation cannot be used to self-grant profile access.
    void observe("SESSION_STARTED", { reason: "PERSONALIZATION_CONSENT_CHANGED" });
  });

  return {
    workspaceId, state, expanded, snapshot, agents, events, directives, sources, selectedAgentName, selectedAgent, error,
    activeCount, degradedCount, suggestions, notices, suggestedTopics, latestEvent, contextVersion, currentObservation, guidanceMessage, explanationDensity, primaryEntry, preferredOutputType,
    initialize, observe, action, selectAgent, stop,
  };
});
