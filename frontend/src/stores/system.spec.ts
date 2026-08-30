import { createPinia, setActivePinia } from "pinia";
import { nextTick } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { healthClient } from "../api/healthClient";
import { runtimeDiagnosticsClient } from "../api/runtimeDiagnosticsClient";
import type { LivenessResponse, ReadinessResponse } from "../domain/health";
import type { RuntimeDiagnosticsResponse } from "../domain/runtimeDiagnostics";
import { useAuthStore } from "./auth";
import { useSystemStore } from "./system";

vi.mock("../api/healthClient", () => ({
  healthClient: {
    getLiveness: vi.fn(),
    getReadiness: vi.fn(),
  },
}));

vi.mock("../api/runtimeDiagnosticsClient", () => ({
  runtimeDiagnosticsClient: {
    get: vi.fn(),
  },
}));

const liveness: LivenessResponse = {
  status: "UP",
  service: "recpro-backend",
  version: "test",
  time: "2026-08-30T06:00:00.000Z",
};

const readiness: ReadinessResponse = {
  status: "READY",
  can_recommend: false,
  components: {
    recommendation_pipeline: { status: "UNKNOWN", required: false },
  },
  config_bundle_version: "test",
  checked_at: "2026-08-30T06:00:00.000Z",
};

const diagnostics: RuntimeDiagnosticsResponse = {
  schema_version: "runtime-diagnostics-v1",
  registry_closed: false,
  resource_count: 0,
  resources: [],
  collected_at: "2026-08-30T06:00:00.000Z",
};

function authenticateAsResearchAdmin(): void {
  const auth = useAuthStore();
  auth.phase = "authenticated";
  auth.accessToken = "research-token";
  auth.account = {
    user_id: 10000,
    account_uuid: "846b1454-54a0-4e2b-a744-c10e840a1c73",
    display_name: "研究管理员",
    status: "ACTIVE",
    roles: ["research_admin"],
    must_change_password: false,
  };
  auth.permissions = ["research.audit.read"];
}

describe("system runtime diagnostics lifecycle", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(healthClient.getLiveness).mockResolvedValue(liveness);
    vi.mocked(healthClient.getReadiness).mockResolvedValue(readiness);
    vi.mocked(runtimeDiagnosticsClient.get).mockResolvedValue(diagnostics);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("aborts and clears a pending snapshot when the drawer closes", async () => {
    authenticateAsResearchAdmin();
    let resolvePending!: (value: RuntimeDiagnosticsResponse) => void;
    const pending = new Promise<RuntimeDiagnosticsResponse>((resolve) => { resolvePending = resolve; });
    vi.mocked(runtimeDiagnosticsClient.get).mockReturnValue(pending);
    const system = useSystemStore();

    system.drawerOpen = true;
    await nextTick();
    expect(system.runtimeDiagnostics.phase).toBe("loading");
    expect(runtimeDiagnosticsClient.get).toHaveBeenCalledWith("research-token", expect.objectContaining({ signal: expect.any(AbortSignal) }));

    system.drawerOpen = false;
    await nextTick();
    expect(system.runtimeDiagnostics).toEqual({ phase: "idle" });
    const options = vi.mocked(runtimeDiagnosticsClient.get).mock.calls[0]?.[1];
    expect(options?.signal?.aborted).toBe(true);

    resolvePending(diagnostics);
    await pending;
    expect(system.runtimeDiagnostics).toEqual({ phase: "idle" });
  });

  it("does not cancel an in-flight diagnostics request during a health refresh", async () => {
    authenticateAsResearchAdmin();
    let resolvePending!: (value: RuntimeDiagnosticsResponse) => void;
    const pending = new Promise<RuntimeDiagnosticsResponse>((resolve) => { resolvePending = resolve; });
    vi.mocked(runtimeDiagnosticsClient.get).mockReturnValue(pending);
    const system = useSystemStore();

    system.drawerOpen = true;
    await nextTick();
    await system.refresh();

    expect(runtimeDiagnosticsClient.get).toHaveBeenCalledTimes(1);
    expect(system.runtimeDiagnostics.phase).toBe("loading");
    resolvePending(diagnostics);
    await pending;
    system.drawerOpen = false;
    await nextTick();
  });
});
