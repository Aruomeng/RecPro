import { describe, expect, it } from "vitest";
import { isAgentWorkspaceSnapshot, isDirective, isWorkspaceEvent } from "./agentWorkspace";

const agent = (name: string) => ({
  name, role: `${name} 角色`, goal: "完成受约束的局部任务", state: "IDLE",
  last_action: null, target: null, reason_code: null, confidence: null, duration_ms: null,
  tools: ["bounded_tool"], evidence_refs: [], updated_at: "2026-08-20T00:00:00Z",
});
const names = ["IntentUnderstandingAgent", "UserProfileAgent", "ResourceSemanticAgent", "RecommendationPolicyAgent", "CandidateRecallAgent", "RankingAgent", "ExplanationAgent", "FeedbackLearningAgent"];
const directive = {
  directive_id: "00000000-0000-4000-8000-000000000001", directive_version: 1,
  type: "SUGGEST_NEXT_ACTION", scope: "global", behavior: "SUGGESTION",
  payload: { label: "继续探索" }, reason_codes: ["CONTEXT_READY"], evidence_refs: ["workspace:context"],
  confidence: 0.82, created_at: "2026-08-20T00:00:00Z", expires_at: "2026-08-20T00:10:00Z", reversible: true, status: "PROPOSED",
};
const event = {
  schema_version: "agent-workspace-event-v1", sequence: 1, event_type: "AGENT_COMPLETED",
  workspace_id: "00000000-0000-4000-8000-000000000002", context_version: 2,
  occurred_at: "2026-08-20T00:00:00Z", agent_name: "RecommendationPolicyAgent",
};

describe("Agent Workspace public decoders", () => {
  it("accepts the exact eight-agent public snapshot", () => {
    expect(isAgentWorkspaceSnapshot({
      schema_version: "agent-workspace-v1", workspace_id: event.workspace_id,
      session_id: "00000000-0000-4000-8000-000000000003", mode: "guest", context_version: 2,
      orchestrator: { name: "RecommendationOrchestrator", role: "编排器", state: "OBSERVING", current_route: "/" },
      agents: names.map(agent), directives: [directive], recent_events: [event], sources: [],
    })).toBe(true);
  });

  it("rejects unknown directive types and malformed SSE sequence", () => {
    expect(isDirective({ ...directive, type: "EXECUTE_ARBITRARY_DOM" })).toBe(false);
    expect(isWorkspaceEvent({ ...event, sequence: 0 })).toBe(false);
  });

  it("rejects snapshots that hide or invent Agent roles", () => {
    expect(isAgentWorkspaceSnapshot({
      schema_version: "agent-workspace-v1", workspace_id: event.workspace_id,
      session_id: event.workspace_id, mode: "guest", context_version: 2,
      orchestrator: {}, agents: names.slice(0, 7).map(agent), directives: [], recent_events: [], sources: [],
    })).toBe(false);
  });
});
