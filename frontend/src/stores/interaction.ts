import { computed, ref, watch } from "vue";
import { defineStore } from "pinia";

import { createInteractionClient } from "../api/interactionClient";
import type { FeedbackReceipt, FeedbackType } from "../domain/interaction";
import type { RecommendationItem } from "../domain/recommendation";
import { createRequestId } from "../domain/recommendation";
import { useSessionStore } from "./session";
import { useSystemStore } from "./system";

export const useInteractionStore = defineStore("interaction", () => {
  const session = useSessionStore();
  const system = useSystemStore();
  const localFeedback = ref<string[]>([]);
  const receipt = ref<FeedbackReceipt | null>(null);
  const state = ref<"idle" | "sending" | "done" | "error">("idle");
  const impressionUuid = ref("");
  let exposureTimer: number | undefined;
  const canWrite = computed(() => session.mode === "demo" && system.interactionEnabled);

  function clearExposure(): void {
    if (exposureTimer !== undefined) window.clearTimeout(exposureTimer);
    exposureTimer = undefined;
  }

  function prepareExposure(item?: RecommendationItem): void {
    clearExposure();
    receipt.value = null;
    state.value = "idle";
    if (!item || !canWrite.value) return;
    const openedAt = new Date();
    impressionUuid.value = createRequestId();
    exposureTimer = window.setTimeout(async () => {
      try {
        const client = createInteractionClient({ demoUserId: session.userId });
        await client.recordImpressions({ impressions: [{
          impression_uuid: impressionUuid.value,
          recommendation_item_id: item.item_id,
          position: item.rank_no,
          rendered_at: openedAt.toISOString(),
          visible_started_at: openedAt.toISOString(),
          visible_ms: 1000,
          max_visible_ratio: 1,
        }] });
      } catch {
        // Telemetry failure must never block resource reading.
      }
    }, 1000);
  }

  async function submit(item: RecommendationItem | undefined, type: FeedbackType): Promise<void> {
    const label = type === "FAVORITE" ? "已喜欢" : type === "BORROW" ? "已标记借阅意向" : "已减少类似推荐";
    if (!canWrite.value || !item) {
      if (!localFeedback.value.includes(label)) localFeedback.value.push(label);
      return;
    }
    state.value = "sending";
    try {
      receipt.value = await createInteractionClient({ demoUserId: session.userId }).recordFeedback(item.item_id, {
        feedback_uuid: createRequestId(), impression_uuid: impressionUuid.value || undefined,
        feedback_type: type, reason_code: type === "NOT_INTERESTED" ? "TOPIC_NOT_INTERESTED" : undefined,
      });
      state.value = "done";
    } catch { state.value = "error"; }
  }

  watch(() => session.resetEpoch, () => {
    clearExposure(); localFeedback.value = []; receipt.value = null; state.value = "idle"; impressionUuid.value = "";
  }, { flush: "sync" });

  return { localFeedback, receipt, state, impressionUuid, canWrite, clearExposure, prepareExposure, submit };
});
