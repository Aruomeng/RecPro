<script setup lang="ts">
import { computed } from "vue";

import type { LivenessResponse, Loadable, ReadinessResponse } from "../domain/health";
import { isHealthFailure } from "../domain/health";
import {
  componentNames,
  componentStatusNames,
  componentTone,
  presentReadiness,
  presentReadinessError,
} from "../presentation/healthPresentation";
import StatusBadge from "./StatusBadge.vue";

const props = defineProps<{
  liveness: Loadable<LivenessResponse>;
  readiness: Loadable<ReadinessResponse>;
}>();

const readinessCopy = computed(() => {
  if (props.readiness.phase === "success") return presentReadiness(props.readiness.value);
  if (props.readiness.phase === "error") return presentReadinessError(props.readiness.error);
  return { label: "正在检查", detail: "正在读取组件与推荐能力状态。", tone: "neutral" as const };
});

const traceId = computed(() => {
  if (props.readiness.phase !== "error" || !isHealthFailure(props.readiness.error)) {
    return undefined;
  }
  return props.readiness.error.traceId;
});

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
    hour12: false,
  }).format(date);
}
</script>

<template>
  <div class="status-layout" aria-live="polite">
    <section class="status-card status-card--primary" aria-labelledby="process-title">
      <div class="status-card__header">
        <div>
          <p class="eyebrow">01 / PROCESS</p>
          <h2 id="process-title">后端进程</h2>
        </div>
        <StatusBadge
          v-if="liveness.phase === 'success'"
          label="进程存活"
          tone="positive"
        />
        <StatusBadge
          v-else-if="liveness.phase === 'error'"
          label="无法连接"
          tone="negative"
        />
        <StatusBadge v-else label="检查中" tone="neutral" />
      </div>

      <template v-if="liveness.phase === 'success'">
        <p class="status-card__description">事件循环响应正常。此检查不访问数据库或外部服务。</p>
        <dl class="metadata-grid">
          <div>
            <dt>服务</dt>
            <dd>{{ liveness.value.service }}</dd>
          </div>
          <div>
            <dt>版本</dt>
            <dd>{{ liveness.value.version }}</dd>
          </div>
          <div>
            <dt>响应时间</dt>
            <dd><time :datetime="liveness.value.time">{{ formatTime(liveness.value.time) }}</time></dd>
          </div>
        </dl>
      </template>
      <p v-else-if="liveness.phase === 'error'" class="status-card__description">
        无法读取存活接口。请确认后端已启动，且反向代理可以访问后端服务。
      </p>
      <p v-else class="status-card__description">正在确认后端进程是否可以响应请求。</p>
    </section>

    <section class="status-card" aria-labelledby="capability-title">
      <div class="status-card__header">
        <div>
          <p class="eyebrow">02 / CAPABILITY</p>
          <h2 id="capability-title">推荐能力</h2>
        </div>
        <StatusBadge :label="readinessCopy.label" :tone="readinessCopy.tone" />
      </div>
      <p class="status-card__description">{{ readinessCopy.detail }}</p>
      <p v-if="traceId" class="trace-line">
        诊断追踪号：<code>{{ traceId }}</code>
      </p>

      <template v-if="readiness.phase === 'success'">
        <div class="readiness-meta">
          <span>配置版本 {{ readiness.value.config_bundle_version }}</span>
          <time :datetime="readiness.value.checked_at">检查于 {{ formatTime(readiness.value.checked_at) }}</time>
        </div>
        <ul class="component-list" aria-label="组件状态">
          <li v-for="(component, name) in readiness.value.components" :key="name">
            <div>
              <strong>{{ componentNames[name] ?? name }}</strong>
              <span>{{ component.required ? "必要组件" : "可选组件" }}</span>
            </div>
            <StatusBadge :label="componentStatusNames[component.status]" :tone="componentTone(component)" />
            <small v-if="component.error_code">错误码 {{ component.error_code }}</small>
            <small v-else-if="component.active_version">版本 {{ component.active_version }}</small>
            <small v-else-if="component.provider">提供方 {{ component.provider }}</small>
          </li>
        </ul>
      </template>
    </section>
  </div>
</template>
