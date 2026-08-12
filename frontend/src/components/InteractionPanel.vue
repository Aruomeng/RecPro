<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";

import type { InteractionClient } from "../domain/interaction";
import { isInteractionFailure } from "../domain/interaction";
import { createRequestId } from "../domain/recommendation";
import type { RecommendationItem } from "../domain/recommendation";

const props = withDefaults(defineProps<{
  items: RecommendationItem[];
  taskId?: string;
  sessionId: string;
  enabled?: boolean;
  client: InteractionClient;
}>(), {
  enabled: false,
});

const selectedItemId = ref<number | null>(null);
const phase = ref<"idle" | "loading" | "success" | "error" | "demo">("idle");
const action = ref<"impression" | "feedback" | "behavior" | null>(null);
const impressionUuid = ref<string | null>(null);
const notice = ref("");
const errorMessage = ref("");
let activeController: AbortController | undefined;

const selectedItem = computed(() => {
  if (!props.items.length) return undefined;
  return props.items.find((item) => item.item_id === selectedItemId.value) ?? props.items[0];
});
const isBusy = computed(() => phase.value === "loading");
const modeLabel = computed(() => props.enabled ? "交互 API 已显式启用" : "交互 API 默认关闭");

function selectItem(itemId: number): void {
  selectedItemId.value = itemId;
  impressionUuid.value = null;
  notice.value = "已切换资源；请先显式记录曝光，再发送反馈或点击行为。";
  errorMessage.value = "";
}

function requireEnabled(): boolean {
  if (!props.enabled) {
    phase.value = "idle";
    notice.value = "G5 交互 API 默认关闭；启用前需要独立的运行环境和 ChangePlan 审批。";
    return false;
  }
  if (!selectedItem.value) {
    errorMessage.value = "请先加载至少一条推荐资源。";
    phase.value = "error";
    return false;
  }
  return true;
}

function startAction(kind: "impression" | "feedback" | "behavior"): AbortController {
  activeController?.abort();
  const controller = new AbortController();
  activeController = controller;
  action.value = kind;
  phase.value = "loading";
  errorMessage.value = "";
  notice.value = "正在通过显式交互 API 发送请求。";
  return controller;
}

async function recordImpression(): Promise<void> {
  if (!requireEnabled()) return;
  const item = selectedItem.value;
  if (!item) return;
  const controller = startAction("impression");
  const now = new Date().toISOString();
  const uuid = createRequestId();
  try {
    const response = await props.client.recordImpressions({
      impressions: [{
        impression_uuid: uuid,
        recommendation_item_id: item.item_id,
        position: item.rank_no,
        rendered_at: now,
        visible_started_at: now,
        visible_ms: 1500,
        max_visible_ratio: 0.8,
      }],
    }, { signal: controller.signal, idempotencyKey: uuid });
    if (controller.signal.aborted) return;
    const result = response.results[0];
    if (!result || result.status === "REJECTED") {
      throw new Error(result?.error_code ?? "IMPRESSION_REJECTED");
    }
    impressionUuid.value = result.impression_uuid;
    phase.value = "success";
    notice.value = result.status === "REPLAYED" ? "曝光已幂等重放。" : "曝光已提交，未自动触发其他行为。";
  } catch (error) {
    if (controller.signal.aborted) return;
    phase.value = "error";
    errorMessage.value = presentError(error);
  } finally {
    if (activeController === controller) activeController = undefined;
    action.value = null;
  }
}

async function recordFeedback(): Promise<void> {
  if (!requireEnabled()) return;
  const item = selectedItem.value;
  if (!item) return;
  if (!impressionUuid.value) {
    errorMessage.value = "请先记录曝光，再发送反馈；这样反馈能与可审计 impression 关联。";
    phase.value = "error";
    return;
  }
  const controller = startAction("feedback");
  const uuid = createRequestId();
  try {
    const response = await props.client.recordFeedback(item.item_id, {
      feedback_uuid: uuid,
      impression_uuid: impressionUuid.value,
      feedback_type: "NOT_INTERESTED",
      reason_code: "TOPIC_NOT_INTERESTED",
    }, { signal: controller.signal });
    if (controller.signal.aborted) return;
    phase.value = "success";
    notice.value = response.status === "REPLAYED"
      ? "反馈已幂等重放。"
      : `反馈已提交，画像状态：${response.profile_update_status}。`;
  } catch (error) {
    if (controller.signal.aborted) return;
    phase.value = "error";
    errorMessage.value = presentError(error);
  } finally {
    if (activeController === controller) activeController = undefined;
    action.value = null;
  }
}

async function recordClick(): Promise<void> {
  if (!requireEnabled()) return;
  const item = selectedItem.value;
  if (!item) return;
  if (!impressionUuid.value) {
    errorMessage.value = "请先记录曝光，再发送点击行为；这样行为能与 recommendation item 关联。";
    phase.value = "error";
    return;
  }
  const controller = startAction("behavior");
  const uuid = createRequestId();
  try {
    const response = await props.client.appendBehavior({
      event_uuid: uuid,
      session_id: props.sessionId,
      task_id: props.taskId,
      event_type: "CLICK_RECOMMENDATION",
      resource_id: item.resource.resource_id,
      recommendation_item_id: item.item_id,
      impression_uuid: impressionUuid.value,
      dwell_ms: 2000,
      position: item.rank_no,
      occurred_at: new Date().toISOString(),
    }, { signal: controller.signal });
    if (controller.signal.aborted) return;
    phase.value = "success";
    notice.value = response.status === "REPLAYED"
      ? "点击行为已幂等重放。"
      : `点击行为已提交，画像状态：${response.profile_update_status}。`;
  } catch (error) {
    if (controller.signal.aborted) return;
    phase.value = "error";
    errorMessage.value = presentError(error);
  } finally {
    if (activeController === controller) activeController = undefined;
    action.value = null;
  }
}

function loadDemo(): void {
  activeController?.abort();
  phase.value = "demo";
  action.value = null;
  notice.value = "已加载交互演示状态：不会访问 API，也不会写入 MySQL、Neo4j 或 Chroma。";
  errorMessage.value = "";
}

function presentError(error: unknown): string {
  if (isInteractionFailure(error)) {
    const messages: Record<string, string> = {
      CORE_STORAGE_UNAVAILABLE: "交互能力当前未就绪。",
      RESOURCE_ACCESS_FORBIDDEN: "当前用户不能操作该推荐资源。",
      REQUEST_ID_MISMATCH: "幂等键与事实 UUID 不一致。",
      INVALID_IMPRESSION_REFERENCE: "反馈必须引用有效的曝光事实。",
      DERIVED_EVENT_NOT_ALLOWED: "派生行为必须通过反馈接口产生。",
      INTERACTION_REQUEST_TIMEOUT: "交互请求超时，请稍后重试。",
    };
    return messages[error.code] ?? `交互请求失败（${error.code}）。`;
  }
  return error instanceof Error ? error.message : "交互请求暂时失败，请稍后重试。";
}

onBeforeUnmount(() => activeController?.abort());
</script>

<template>
  <section class="interaction-panel" aria-labelledby="interaction-title">
    <div class="interaction-panel__header">
      <div>
        <p class="eyebrow">G5 / INTERACTION WORKBENCH</p>
        <h3 id="interaction-title">反馈与行为闭环</h3>
        <p class="interaction-panel__lede">
          曝光、反馈和点击分别对应独立事实；页面不会自动上报，只有显式启用并点击操作时才访问交互 API。
        </p>
      </div>
      <span class="interaction-panel__mode" :class="{ 'interaction-panel__mode--ready': enabled }">
        <span aria-hidden="true" />{{ modeLabel }}
      </span>
    </div>

    <div v-if="items.length" class="interaction-panel__body">
      <label class="interaction-panel__select" for="interaction-item">操作资源</label>
      <select id="interaction-item" :value="selectedItem?.item_id" :disabled="isBusy" @change="selectItem(Number(($event.target as HTMLSelectElement).value))">
        <option v-for="item in items" :key="item.item_id" :value="item.item_id">
          {{ item.rank_no }} · {{ item.resource.title }}
        </option>
      </select>
      <p v-if="selectedItem" class="interaction-panel__resource">
        当前资源：{{ selectedItem.resource.title }} · item={{ selectedItem.item_id }} · resource={{ selectedItem.resource.resource_id }}
      </p>
      <div class="interaction-panel__actions">
        <button class="secondary-action" type="button" :disabled="isBusy" @click="recordImpression">
          {{ action === "impression" ? "提交中…" : "记录曝光" }}
        </button>
        <button class="secondary-action" type="button" :disabled="isBusy" @click="recordFeedback">
          {{ action === "feedback" ? "提交中…" : "不感兴趣" }}
        </button>
        <button class="primary-action" type="button" :disabled="isBusy" @click="recordClick">
          {{ action === "behavior" ? "提交中…" : "记录点击" }}
        </button>
        <button class="secondary-action" type="button" :disabled="isBusy" @click="loadDemo">查看交互演示</button>
      </div>
    </div>
    <p v-else class="interaction-panel__empty">完成一次推荐请求后，这里会显示可操作的推荐资源。</p>

    <p v-if="notice" class="workbench-note" role="status"><span aria-hidden="true">i</span>{{ notice }}</p>
    <p v-if="errorMessage" class="workbench-error" role="alert">{{ errorMessage }}</p>
    <p v-if="impressionUuid" class="interaction-panel__audit">当前曝光 UUID：<code>{{ impressionUuid }}</code></p>
  </section>
</template>
