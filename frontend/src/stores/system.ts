import { computed, ref, watch } from "vue";
import { defineStore } from "pinia";

import { healthClient } from "../api/healthClient";
import { runtimeDiagnosticsClient } from "../api/runtimeDiagnosticsClient";
import type { LivenessResponse, Loadable, ReadinessResponse } from "../domain/health";
import type { RuntimeDiagnosticsLoadable } from "../domain/runtimeDiagnostics";
import { useAuthStore } from "./auth";

export const useSystemStore = defineStore("system", () => {
  const RUNTIME_REFRESH_INTERVAL_MS = 30_000;
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
  let runtimePollTimer: number | undefined;
  let runtimeController: AbortController | undefined;

  function stopRuntimePolling(): void {
    if (runtimePollTimer !== undefined) {
      window.clearInterval(runtimePollTimer);
      runtimePollTimer = undefined;
    }
    runtimeRequestId += 1;
    runtimeController?.abort("runtime-diagnostics-no-longer-visible");
    runtimeController = undefined;
  }

  function startRuntimePolling(): void {
    if (runtimePollTimer !== undefined || !canReadRuntimeDiagnostics.value || !drawerOpen.value) return;
    runtimePollTimer = window.setInterval(() => {
      if (document.visibilityState === "hidden") return;
      void refreshRuntime();
    }, RUNTIME_REFRESH_INTERVAL_MS);
  }

  function clearRuntimeDiagnostics(): void {
    stopRuntimePolling();
    runtimeDiagnostics.value = { phase: "idle" };
  }

  async function refreshRuntime(): Promise<void> {
    if (!canReadRuntimeDiagnostics.value || !auth.accessToken) {
      clearRuntimeDiagnostics();
      return;
    }
    if (runtimeDiagnostics.value.phase === "loading") return;
    const requestId = ++runtimeRequestId;
    const controller = new AbortController();
    runtimeController = controller;
    runtimeDiagnostics.value = { phase: "loading" };
    try {
      const value = await runtimeDiagnosticsClient.get(auth.accessToken, { signal: controller.signal });
      if (requestId !== runtimeRequestId || !canReadRuntimeDiagnostics.value) return;
      runtimeDiagnostics.value = { phase: "success", value };
    } catch (error) {
      if (requestId !== runtimeRequestId) return;
      if (error instanceof DOMException && error.name === "AbortError") return;
      runtimeDiagnostics.value = { phase: "error", error };
    } finally {
      if (runtimeController === controller) runtimeController = undefined;
    }
  }

  async function refresh(): Promise<void> {
    liveness.value = { phase: "loading" };
    readiness.value = { phase: "loading" };
    const accessToken = auth.accessToken;
    const shouldReadRuntimeDiagnostics = canReadRuntimeDiagnostics.value && Boolean(accessToken);
    const runtimeAlreadyLoading = runtimeDiagnostics.value.phase === "loading";
    const requestId = shouldReadRuntimeDiagnostics && !runtimeAlreadyLoading
      ? ++runtimeRequestId
      : undefined;
    const controller = requestId !== undefined ? new AbortController() : undefined;
    if (controller) runtimeController = controller;
    const runtime = requestId !== undefined && accessToken
      ? runtimeDiagnosticsClient.get(accessToken, { signal: controller?.signal })
      : undefined;
    if (runtime) runtimeDiagnostics.value = { phase: "loading" };
    else if (!shouldReadRuntimeDiagnostics) clearRuntimeDiagnostics();
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
    if (controller && runtimeController === controller) runtimeController = undefined;
  }

  watch(() => [drawerOpen.value, canReadRuntimeDiagnostics.value] as const, ([open, allowed]) => {
    if (open && allowed) {
      void refreshRuntime();
      startRuntimePolling();
    } else {
      stopRuntimePolling();
      if (runtimeDiagnostics.value.phase === "loading") runtimeDiagnostics.value = { phase: "idle" };
    }
  });

  return { liveness, readiness, runtimeDiagnostics, drawerOpen, recommendationEnabled, interactionEnabled, healthy, canReadRuntimeDiagnostics, refresh, refreshRuntime, clearRuntimeDiagnostics };
});
