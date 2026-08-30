<script setup lang="ts">
import type { RuntimeDiagnosticsLoadable, RuntimeMetricValue } from "../domain/runtimeDiagnostics";

const props = defineProps<{
  runtime: RuntimeDiagnosticsLoadable;
}>();

const emit = defineEmits<{
  refresh: [];
}>();

const metricLabels: Record<string, string> = {
  initialized: "已初始化",
  closed: "已关闭",
  min_size: "最小连接数",
  max_size: "最大连接数",
  recycle_seconds: "回收周期",
  acquire_timeout_seconds: "获取超时",
  pool_size: "池连接数",
  free_size: "空闲连接",
  active_leases: "活跃租约",
  pending_acquires: "等待获取",
  acquire_count: "获取次数",
  acquire_timeout_count: "获取超时次数",
  release_count: "释放次数",
  total_acquire_ms: "累计获取耗时",
  last_acquire_ms: "最近获取耗时",
  average_acquire_ms: "平均获取耗时",
};

const metricUnits: Record<string, string> = {
  recycle_seconds: "秒",
  acquire_timeout_seconds: "秒",
  total_acquire_ms: "毫秒",
  last_acquire_ms: "毫秒",
  average_acquire_ms: "毫秒",
  pool_size: "个",
  free_size: "个",
  active_leases: "个",
  pending_acquires: "个",
  acquire_count: "次",
  acquire_timeout_count: "次",
  release_count: "次",
};

function formatMetric(key: string, value: RuntimeMetricValue): string {
  if (value === null) return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  const formatted = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value);
  return metricUnits[key] ? `${formatted} ${metricUnits[key]}` : formatted;
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
    hour12: false,
  }).format(date);
}

function errorCode(error: unknown): string {
  if (typeof error === "object" && error !== null && "code" in error && typeof error.code === "string") return error.code;
  return "RUNTIME_DIAGNOSTICS_UNAVAILABLE";
}
</script>

<template>
  <section class="runtime-diagnostics" aria-labelledby="runtime-diagnostics-title" aria-live="polite">
    <div class="runtime-diagnostics__header">
      <div>
        <p class="eyebrow">03 / RUNTIME DIAGNOSTICS</p>
        <h2 id="runtime-diagnostics-title">运行时资源</h2>
        <p>仅研究管理员可见的只读快照，不包含连接凭据或业务数据。</p>
      </div>
      <button class="state-action runtime-diagnostics__refresh" type="button" :disabled="runtime.phase === 'loading'" @click="emit('refresh')">
        {{ runtime.phase === 'loading' ? '读取中…' : '刷新快照' }}
      </button>
    </div>

    <div v-if="runtime.phase === 'idle'" class="runtime-diagnostics__state">
      <strong>诊断未启用</strong>
      <span>需要研究管理员正式登录后才会请求该接口。</span>
    </div>
    <div v-else-if="runtime.phase === 'loading'" class="runtime-diagnostics__state">
      <strong>正在读取安全快照</strong>
      <span>此操作只读取进程内指标，不触发数据库或大模型调用。</span>
    </div>
    <div v-else-if="runtime.phase === 'error'" class="runtime-diagnostics__state runtime-diagnostics__state--error">
      <strong>运行时诊断暂不可用</strong>
      <span>错误码 {{ errorCode(runtime.error) }}。核心馆藏功能不受此只读诊断影响。</span>
      <button class="state-action" type="button" @click="emit('refresh')">再次读取</button>
    </div>
    <template v-else>
      <div class="runtime-diagnostics__summary">
        <div><span>资源快照</span><strong>{{ runtime.value.resource_count }}</strong><small>个显式注册资源</small></div>
        <div><span>生命周期</span><strong>{{ runtime.value.registry_closed ? '已关闭' : '运行中' }}</strong><small>注册表状态</small></div>
        <div><span>采集时间</span><strong>{{ formatTime(runtime.value.collected_at) }}</strong><small>UTC/本地化显示</small></div>
      </div>
      <div v-if="runtime.value.resources.length" class="runtime-diagnostics__resources">
        <article v-for="resource in runtime.value.resources" :key="resource.resource_type" class="runtime-resource-card">
          <div class="runtime-resource-card__heading"><h3>{{ resource.resource_type }}</h3><span>公开指标</span></div>
          <dl>
            <div v-for="(value, key) in resource.metrics" :key="key"><dt>{{ metricLabels[key] ?? key }}</dt><dd>{{ formatMetric(key, value) }}</dd></div>
          </dl>
        </article>
      </div>
      <div v-else class="runtime-diagnostics__state">
        <strong>当前没有可公开的资源快照</strong>
        <span>这不代表馆藏为空，只表示本次组合根未注册可观测运行时资源。</span>
      </div>
    </template>
  </section>
</template>
