import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { healthClient } from "../api/healthClient";
import { runtimeDiagnosticsClient } from "../api/runtimeDiagnosticsClient";
import type { LivenessResponse, Loadable, ReadinessResponse } from "../domain/health";
import type { RuntimeDiagnosticsLoadable } from "../domain/runtimeDiagnostics";
import { useAuthStore } from "./auth";

export const useSystemStore = defineStore("system", () => {
  const auth = useAuthStore();
  const liveness = ref<Loadable<LivenessResponse>>({ phase: "loading" });
  const readiness = ref<Loadable<ReadinessResponse>>({ phase: "loading" });
  const runtimeDiagnostics = ref<RuntimeDiagnosticsLoadable>({ phase: "idle" });
  const drawerOpen = ref(false);

  const recommendationEnabled = computed(() => readiness.value.phase === "success" && readiness.value.value.can_recommend);
  const interactionEnabled = computed(() => readiness.value.phase === "success" && readiness.value.value.components.interaction_pipeline?.status === "UP");
  const healthy = computed(() => liveness.value.phase === "success" && readiness.value.phase === "success");
  const canReadRuntimeDiagnostics = computed(() => auth.authenticated && auth.permissions.includes("research.audit.read"));
  let runtimeRequestId = 0;

  function clearRuntimeDiagnostics(): void {
    runtimeRequestId += 1;
    runtimeDiagnostics.value = { phase: "idle" };
  }

  async function refreshRuntime(): Promise<void> {
    if (!canReadRuntimeDiagnostics.value || !auth.accessToken) {
      clearRuntimeDiagnostics();
      return;
    }
    if (runtimeDiagnostics.value.phase === "loading") return;
    const requestId = ++runtimeRequestId;
    runtimeDiagnostics.value = { phase: "loading" };
    try {
      const value = await runtimeDiagnosticsClient.get(auth.accessToken);
      if (requestId !== runtimeRequestId || !canReadRuntimeDiagnostics.value) return;
      runtimeDiagnostics.value = { phase: "success", value };
    } catch (error) {
      if (requestId !== runtimeRequestId) return;
      runtimeDiagnostics.value = { phase: "error", error };
    }
  }

  async function refresh(): Promise<void> {
    liveness.value = { phase: "loading" };
    readiness.value = { phase: "loading" };
    const requestId = canReadRuntimeDiagnostics.value && auth.accessToken && runtimeDiagnostics.value.phase !== "loading"
      ? ++runtimeRequestId
      : undefined;
    const runtime = requestId !== undefined
      ? runtimeDiagnosticsClient.get(auth.accessToken)
      : undefined;
    if (runtime) runtimeDiagnostics.value = { phase: "loading" };
    else clearRuntimeDiagnostics();
    const [live, ready, diagnostics] = await Promise.allSettled([
      healthClient.getLiveness(),
      healthClient.getReadiness(),
      runtime ?? Promise.resolve(undefined),
    ]);
    liveness.value = live.status === "fulfilled" ? { phase: "success", value: live.value } : { phase: "error", error: live.reason };
    readiness.value = ready.status === "fulfilled" ? { phase: "success", value: ready.value } : { phase: "error", error: ready.reason };
    if (runtime && requestId === runtimeRequestId && canReadRuntimeDiagnostics.value) runtimeDiagnostics.value = diagnostics.status === "fulfilled" && diagnostics.value
      ? { phase: "success", value: diagnostics.value }
      : { phase: "error", error: diagnostics.status === "rejected" ? diagnostics.reason : new Error("RUNTIME_DIAGNOSTICS_UNAVAILABLE") };
  }

  return { liveness, readiness, runtimeDiagnostics, drawerOpen, recommendationEnabled, interactionEnabled, healthy, canReadRuntimeDiagnostics, refresh, refreshRuntime, clearRuntimeDiagnostics };
});
