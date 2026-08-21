export type AgentWorkspaceState = "IDLE" | "OBSERVING" | "PLANNING" | "WORKING" | "WAITING_USER" | "COMPLETED" | "DEGRADED" | "FAILED";
export type WorkspaceObservationType = "SESSION_STARTED" | "ROUTE_CHANGED" | "QUERY_SUBMITTED" | "GRAPH_NODE_SELECTED" | "RESOURCE_OPENED" | "RECOMMENDATION_STARTED" | "RECOMMENDATION_COMPLETED" | "FEEDBACK_RECORDED" | "READINESS_CHANGED" | "EXTERNAL_CONTEXT_UPDATED";
export type DirectiveType = "SUGGEST_TOPICS" | "SET_PRIMARY_ENTRY" | "PREFER_OUTPUT_TYPE" | "SET_EXPLANATION_DENSITY" | "SHOW_GUIDANCE" | "SHOW_DEGRADED_NOTICE" | "SUGGEST_NEXT_ACTION";

export interface WorkspaceAgent {
  name: string;
  role: string;
  goal: string;
  state: AgentWorkspaceState;
  last_action: string | null;
  target: string | null;
  reason_code: string | null;
  confidence: number | null;
  duration_ms: number | null;
  tools: string[];
  evidence_refs: string[];
  updated_at: string;
}

export interface InteractionDirective {
  directive_id: string;
  directive_version: number;
  type: DirectiveType;
  scope: string;
  behavior: "AUTO_APPLY" | "SUGGESTION" | "NOTICE";
  payload: Record<string, unknown>;
  reason_codes: string[];
  evidence_refs: string[];
  confidence: number;
  created_at: string;
  expires_at: string;
  reversible: boolean;
  status: "PROPOSED" | "AUTO_APPLIED" | "ACCEPTED" | "DISMISSED" | "UNDONE";
}

export interface WorkspaceEvent {
  schema_version: "agent-workspace-event-v1";
  sequence: number;
  event_type: string;
  workspace_id: string;
  context_version: number;
  occurred_at: string;
  agent_name?: string;
  action?: string;
  target?: string;
  reason_code?: string;
  confidence?: number;
  duration_ms?: number;
  outcome?: string;
  directive?: InteractionDirective;
  replayed?: boolean;
  [key: string]: unknown;
}

export interface WorkspaceContextSummary {
  route: string;
  query: string;
  external: Array<{
    source_id: string;
    kind: "EXTERNAL_DEMO";
    label: string;
    status: string;
    observed_at: string;
    expires_at: string;
    values: Record<string, string | number | boolean | null | string[]>;
  }>;
}

export interface AgentWorkspaceSnapshot {
  schema_version: "agent-workspace-v1";
  workspace_id: string;
  session_id: string;
  mode: "guest" | "demo" | "authenticated";
  context_version: number;
  orchestrator: { name: string; role: string; state: AgentWorkspaceState; current_route: string };
  agents: WorkspaceAgent[];
  directives: InteractionDirective[];
  recent_events: WorkspaceEvent[];
  sources: Array<{ source_id: string; kind: "INTERNAL" | "EXTERNAL_DEMO"; label: string; status: string; observed_at: string; expires_at: string }>;
  context_summary: WorkspaceContextSummary;
}

export const workspaceAgentStates: AgentWorkspaceState[] = ["IDLE", "OBSERVING", "PLANNING", "WORKING", "WAITING_USER", "COMPLETED", "DEGRADED", "FAILED"];

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isWorkspaceAgent(value: unknown): value is WorkspaceAgent {
  if (!isRecord(value)) return false;
  return typeof value.name === "string" && typeof value.role === "string" && typeof value.goal === "string" &&
    typeof value.state === "string" && workspaceAgentStates.includes(value.state as AgentWorkspaceState) &&
    Array.isArray(value.tools) && value.tools.every((item) => typeof item === "string") &&
    Array.isArray(value.evidence_refs) && value.evidence_refs.every((item) => typeof item === "string") && typeof value.updated_at === "string";
}

export function isDirective(value: unknown): value is InteractionDirective {
  if (!isRecord(value)) return false;
  const types: DirectiveType[] = ["SUGGEST_TOPICS", "SET_PRIMARY_ENTRY", "PREFER_OUTPUT_TYPE", "SET_EXPLANATION_DENSITY", "SHOW_GUIDANCE", "SHOW_DEGRADED_NOTICE", "SUGGEST_NEXT_ACTION"];
  return typeof value.directive_id === "string" && typeof value.type === "string" && types.includes(value.type as DirectiveType) &&
    typeof value.scope === "string" && ["AUTO_APPLY", "SUGGESTION", "NOTICE"].includes(String(value.behavior)) &&
    isRecord(value.payload) && Array.isArray(value.reason_codes) && Array.isArray(value.evidence_refs) &&
    typeof value.confidence === "number" && value.confidence >= 0 && value.confidence <= 1 && typeof value.created_at === "string" && typeof value.expires_at === "string";
}

export function isWorkspaceEvent(value: unknown): value is WorkspaceEvent {
  if (!isRecord(value)) return false;
  return value.schema_version === "agent-workspace-event-v1" && Number.isInteger(value.sequence) && Number(value.sequence) >= 1 &&
    typeof value.event_type === "string" && typeof value.workspace_id === "string" && Number.isInteger(value.context_version) && typeof value.occurred_at === "string" &&
    (value.replayed === undefined || typeof value.replayed === "boolean") &&
    (value.directive === undefined || isDirective(value.directive));
}

export function isAgentWorkspaceSnapshot(value: unknown): value is AgentWorkspaceSnapshot {
  if (!isRecord(value) || value.schema_version !== "agent-workspace-v1" || typeof value.workspace_id !== "string" || typeof value.session_id !== "string" || !["guest", "demo", "authenticated"].includes(String(value.mode))) return false;
  if (!isRecord(value.orchestrator) || !Array.isArray(value.agents) || value.agents.length !== 8 || !value.agents.every(isWorkspaceAgent)) return false;
  if (!Array.isArray(value.directives) || !value.directives.every(isDirective) || !Array.isArray(value.recent_events) || !value.recent_events.every(isWorkspaceEvent)) return false;
  if (!Array.isArray(value.sources) || !value.sources.every((source) => isRecord(source) && typeof source.source_id === "string" && ["INTERNAL", "EXTERNAL_DEMO"].includes(String(source.kind)) && typeof source.label === "string" && typeof source.status === "string" && typeof source.observed_at === "string" && typeof source.expires_at === "string")) return false;
  if (!isRecord(value.context_summary) || typeof value.context_summary.route !== "string" || typeof value.context_summary.query !== "string" || !Array.isArray(value.context_summary.external)) return false;
  return value.context_summary.external.every((source) => isRecord(source) && source.kind === "EXTERNAL_DEMO" && typeof source.source_id === "string" && typeof source.label === "string" && typeof source.status === "string" && typeof source.observed_at === "string" && typeof source.expires_at === "string" && isRecord(source.values) && Object.values(source.values).every((item) => item === null || ["string", "number", "boolean"].includes(typeof item) || (Array.isArray(item) && item.length <= 20 && item.every((entry) => typeof entry === "string"))));
}
