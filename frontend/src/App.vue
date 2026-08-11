<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";

import { healthClient } from "./api/healthClient";
import { recommendationClient } from "./api/recommendationClient";
import RecommendationWorkbench from "./components/RecommendationWorkbench.vue";
import SystemStatus from "./components/SystemStatus.vue";
import type { LivenessResponse, Loadable, ReadinessResponse } from "./domain/health";

const liveness = ref<Loadable<LivenessResponse>>({ phase: "loading" });
const readiness = ref<Loadable<ReadinessResponse>>({ phase: "loading" });
const isRefreshing = ref(false);
let activeController: AbortController | undefined;

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
        <p class="phase-label"><span>G1</span> 可启动工程骨架</p>
        <h1>系统状态，一眼可核验</h1>
        <p>
          当前页面只报告真实健康状态。进程存活不等于依赖就绪，依赖就绪也不代表推荐能力已经实现。
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
      <p><strong>运行边界：</strong>默认运行时仍不会自动启用推荐链；下面的本地演示不访问后端，也不写入任何数据库。</p>
    </aside>

    <SystemStatus :liveness="liveness" :readiness="readiness" />

    <RecommendationWorkbench :pipeline-enabled="false" :client="recommendationClient" />

    <footer>
      <span>LibraMAS · Multi-Agent System for Smart Library</span>
      <span>状态核验 + 推荐工作台</span>
    </footer>
  </main>
</template>
