<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { healthClient } from "./api/healthClient";
import { interactionClient } from "./api/interactionClient";
import { recommendationClient } from "./api/recommendationClient";
import RecommendationWorkbench from "./components/RecommendationWorkbench.vue";
import SystemStatus from "./components/SystemStatus.vue";
import type { LivenessResponse, Loadable, ReadinessResponse } from "./domain/health";

const liveness = ref<Loadable<LivenessResponse>>({ phase: "loading" });
const readiness = ref<Loadable<ReadinessResponse>>({ phase: "loading" });
const isRefreshing = ref(false);
let activeController: AbortController | undefined;

const recommendationPipelineEnabled = computed(
  () => readiness.value.phase === "success" && readiness.value.value.can_recommend,
);
const interactionPipelineEnabled = import.meta.env.VITE_G5_INTERACTION_ENABLED === "true";

async function refresh(): Promise<void> {
  activeController?.abort();
  const controller = new AbortController();
  activeController = controller;
  isRefreshing.value = true;
  liveness.value = { phase: "loading" };
  readiness.value = { phase: "loading" };

  try {
    const [liveResult, readyResult] = await Promise.allSettled([
      healthClient.getLiveness({ signal: controller.signal }),
      healthClient.getReadiness({ signal: controller.signal }),
    ]);

    if (controller.signal.aborted) return;

    liveness.value = liveResult.status === "fulfilled"
      ? { phase: "success", value: liveResult.value }
      : { phase: "error", error: liveResult.reason };
    readiness.value = readyResult.status === "fulfilled"
      ? { phase: "success", value: readyResult.value }
      : { phase: "error", error: readyResult.reason };
  } finally {
    if (activeController === controller) isRefreshing.value = false;
  }
}

onMounted(refresh);
onBeforeUnmount(() => activeController?.abort());
</script>

<template>
  <main class="page-shell">
    <header class="hero">
      <div class="hero__copy">
        <p class="phase-label"><span>G8</span> 核心验收已通过</p>
        <h1>智慧图书馆多智能体推荐系统</h1>
        <p>
          页面同时核验运行依赖与推荐能力；只有显式研究组合根就绪时，才允许发送真实推荐请求。
        </p>
      </div>
      <button class="refresh-button" type="button" :disabled="isRefreshing" :aria-busy="isRefreshing" @click="refresh">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M20 12a8 8 0 1 1-2.34-5.66M20 4v6h-6" />
        </svg>
        {{ isRefreshing ? "检查中…" : "重新检查" }}
      </button>
    </header>

    <aside class="scope-note" aria-label="当前阶段说明">
      <span class="scope-note__mark" aria-hidden="true">i</span>
      <p><strong>运行边界：</strong>默认 Compose 保持安全待机；真实 MySQL、Neo4j、Chroma 与 DeepSeek 仅由显式研究组合根启用。</p>
    </aside>

    <SystemStatus :liveness="liveness" :readiness="readiness" />

    <RecommendationWorkbench
      :pipeline-enabled="recommendationPipelineEnabled"
      :client="recommendationClient"
      :interaction-enabled="interactionPipelineEnabled"
      :interaction-client="interactionClient"
    />

    <footer>
      <span>LibraMAS · Multi-Agent System for Smart Library</span>
      <span>运行核验 + 推荐与反馈工作台</span>
    </footer>
  </main>
</template>
