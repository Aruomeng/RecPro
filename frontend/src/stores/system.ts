import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { healthClient } from "../api/healthClient";
import type { LivenessResponse, Loadable, ReadinessResponse } from "../domain/health";

export const useSystemStore = defineStore("system", () => {
  const liveness = ref<Loadable<LivenessResponse>>({ phase: "loading" });
  const readiness = ref<Loadable<ReadinessResponse>>({ phase: "loading" });
  const drawerOpen = ref(false);

  const recommendationEnabled = computed(() => readiness.value.phase === "success" && readiness.value.value.can_recommend);
  const interactionEnabled = computed(() => readiness.value.phase === "success" && readiness.value.value.components.interaction_pipeline?.status === "UP");
  const healthy = computed(() => liveness.value.phase === "success" && readiness.value.phase === "success");

  async function refresh(): Promise<void> {
    liveness.value = { phase: "loading" };
    readiness.value = { phase: "loading" };
    const [live, ready] = await Promise.allSettled([healthClient.getLiveness(), healthClient.getReadiness()]);
    liveness.value = live.status === "fulfilled" ? { phase: "success", value: live.value } : { phase: "error", error: live.reason };
    readiness.value = ready.status === "fulfilled" ? { phase: "success", value: ready.value } : { phase: "error", error: ready.reason };
  }

  return { liveness, readiness, drawerOpen, recommendationEnabled, interactionEnabled, healthy, refresh };
});
