import { createPinia, setActivePinia } from "pinia";
import { nextTick } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { agentWorkspaceClient } from "../api/agentWorkspaceClient";
import type { AgentWorkspaceSnapshot, WorkspaceEvent } from "../domain/agentWorkspace";
import { useAgentWorkspaceStore } from "./agentWorkspace";

vi.mock("../api/agentWorkspaceClient", () => ({
  agentWorkspaceClient: {
    create: vi.fn(),
    observe: vi.fn(),
    action: vi.fn(),
    stream: vi.fn(),
  },
}));

const agentNames = [
  "IntentUnderstandingAgent", "UserProfileAgent", "ResourceSemanticAgent", "RecommendationPolicyAgent",
  "CandidateRecallAgent", "RankingAgent", "ExplanationAgent", "FeedbackLearningAgent",
];

function snapshot(workspaceId: string, contextVersion: number, eventSequence = contextVersion): AgentWorkspaceSnapshot {
  const timestamp = "2026-08-30T06:00:00.000Z";
  return {
    schema_version: "agent-workspace-v2",
    workspace_id: workspaceId,
    session_id: "session-test",
    mode: "guest",
    context_version: contextVersion,
    orchestrator: {
      name: "Orchestrator",
      role: "全局协同调度",
      state: "OBSERVING",
      current_route: "/",
      current_observation: null,
    },
    agents: agentNames.map((name) => ({
      name,
      role: name.replace("Agent", ""),
      goal: "保持当前上下文一致",
      state: "IDLE",
      last_action: null,
      target: null,
      reason_code: null,
      confidence: null,
      duration_ms: null,
      tools: [],
      evidence_refs: [],
      updated_at: timestamp,
    })),
    directives: [],
    recent_events: eventSequence > 0 ? [{
      schema_version: "agent-workspace-event-v1",
      sequence: eventSequence,
      event_type: "OBSERVATION_COMPLETED",
      workspace_id: workspaceId,
      context_version: contextVersion,
      occurred_at: timestamp,
    }] : [],
    sources: [],
    context_summary: { route: "/", query: "", external: [] },
    session_topic_graph: { version: 1, nodes: [], edges: [], truncated: false },
  };
}

describe("agentWorkspace store concurrency boundaries", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(agentWorkspaceClient.create).mockResolvedValue({ workspace: snapshot("workspace-1", 1), events_url: "/events", replayed: false });
    vi.mocked(agentWorkspaceClient.observe).mockImplementation(async (workspaceId, _type, _payload, _identity) => snapshot(workspaceId, 2));
    vi.mocked(agentWorkspaceClient.action).mockResolvedValue({
      directive_id: "directive-1", directive_version: 1, type: "SHOW_GUIDANCE", scope: "global", behavior: "SUGGESTION",
      payload: {}, reason_codes: [], evidence_refs: [], confidence: 0.8, created_at: "2026-08-30T06:00:00.000Z",
      expires_at: "2026-08-30T06:05:00.000Z", reversible: true, status: "ACCEPTED",
    });
    vi.mocked(agentWorkspaceClient.stream).mockResolvedValue();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("ignores a stale stream failure after a workspace replacement", async () => {
    let rejectOldStream!: (reason: Error) => void;
    const oldStream = new Promise<void>((_resolve, reject) => { rejectOldStream = reject; });
    vi.mocked(agentWorkspaceClient.stream)
      .mockReturnValueOnce(oldStream)
      .mockResolvedValueOnce();
    const workspace = useAgentWorkspaceStore();

    await workspace.initialize();
    const oldOnEvent = vi.mocked(agentWorkspaceClient.stream).mock.calls[0]?.[3] as ((event: WorkspaceEvent) => void) | undefined;
    await workspace.initialize();
    expect(workspace.workspaceId).toBe("workspace-1");
    expect(workspace.state).toBe("online");

    rejectOldStream(new Error("old stream closed"));
    await oldStream.catch(() => undefined);
    oldOnEvent?.({
      schema_version: "agent-workspace-event-v1", sequence: 99, event_type: "AGENT_STARTED",
      workspace_id: "workspace-1", context_version: 99, occurred_at: "2026-08-30T06:00:00.000Z",
      agent_name: "RecommendationPolicyAgent",
    });
    await nextTick();
    expect(workspace.state).toBe("online");
    expect(workspace.error).toBe("");
    expect(workspace.events.some((event) => event.sequence === 99)).toBe(false);
  });

  it("does not apply an observation response from a replaced workspace", async () => {
    const workspace = useAgentWorkspaceStore();
    await workspace.initialize();
    let resolveObservation!: (value: AgentWorkspaceSnapshot) => void;
    const pending = new Promise<AgentWorkspaceSnapshot>((resolve) => { resolveObservation = resolve; });
    vi.mocked(agentWorkspaceClient.observe).mockReturnValueOnce(pending);

    const observation = workspace.observe("ROUTE_CHANGED", { route: "/graph" });
    await workspace.initialize();
    resolveObservation(snapshot("workspace-1", 99));
    await observation;

    expect(workspace.contextVersion).toBe(1);
    expect(workspace.state).toBe("online");
  });

  it("keeps the newest context when concurrent observations resolve out of order", async () => {
    const workspace = useAgentWorkspaceStore();
    await workspace.initialize();
    let resolveFirst!: (value: AgentWorkspaceSnapshot) => void;
    let resolveSecond!: (value: AgentWorkspaceSnapshot) => void;
    const first = new Promise<AgentWorkspaceSnapshot>((resolve) => { resolveFirst = resolve; });
    const second = new Promise<AgentWorkspaceSnapshot>((resolve) => { resolveSecond = resolve; });
    vi.mocked(agentWorkspaceClient.observe)
      .mockReturnValueOnce(first)
      .mockReturnValueOnce(second);

    const older = workspace.observe("ROUTE_CHANGED", { route: "/old" });
    const newer = workspace.observe("QUERY_SUBMITTED", { query: "多智能体" });
    resolveSecond(snapshot("workspace-1", 3, 3));
    await second;
    resolveFirst(snapshot("workspace-1", 2, 2));
    await Promise.all([older, newer]);

    expect(workspace.contextVersion).toBe(3);
    expect(workspace.snapshot?.recent_events[0]?.sequence).toBe(3);
  });
});
