<script setup lang="ts">
import { AriaComponent, GridComponent, LegendComponent, TitleComponent, TooltipComponent } from "echarts/components";
import { init, registerTheme, use } from "echarts/core";
import type { ECharts, EChartsCoreOption as EChartsOption } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = withDefaults(defineProps<{
  option: EChartsOption;
  ariaLabel?: string;
  empty?: boolean;
  emptyText?: string;
  loading?: boolean;
  error?: string;
}>(), { ariaLabel: "数据可视化", empty: false, emptyText: "暂无可展示数据", loading: false, error: "" });
const emit = defineEmits<{ chartClick: [params: unknown] }>();
const host = ref<HTMLDivElement | null>(null);
let chart: ECharts | undefined;
let observer: ResizeObserver | undefined;
let resizeFrame: number | undefined;

use([
  AriaComponent, GridComponent, LegendComponent, TitleComponent, TooltipComponent, CanvasRenderer,
]);
registerTheme("libramas-blue", {
  color: ["#2563eb", "#0891b2", "#4f46e5", "#0d9488", "#60a5fa", "#818cf8", "#38bdf8"],
  textStyle: { color: "#334155", fontFamily: "Inter, PingFang SC, Microsoft YaHei, sans-serif", fontSize: 13 },
  title: { textStyle: { color: "#0f172a" }, subtextStyle: { color: "#64748b" } },
  legend: { textStyle: { color: "#475569", fontSize: 13 } },
  tooltip: { backgroundColor: "#ffffff", borderColor: "#dbe4f0", textStyle: { color: "#0f172a", fontSize: 13 }, extraCssText: "box-shadow:0 10px 28px rgba(15,23,42,.12);border-radius:10px" },
  categoryAxis: { axisLine: { lineStyle: { color: "#cbd5e1" } }, axisLabel: { color: "#64748b", fontSize: 12 }, splitLine: { lineStyle: { color: "#eef2f7" } } },
  valueAxis: { axisLine: { lineStyle: { color: "#cbd5e1" } }, axisLabel: { color: "#64748b", fontSize: 12 }, splitLine: { lineStyle: { color: "#eef2f7" } } },
});

function render(option: EChartsOption): void {
  if (!chart) return;
  const reduced = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  chart.setOption({ animation: !reduced, aria: { enabled: true, decal: { show: true } }, ...option }, { notMerge: true });
}

onMounted(() => {
  if (!host.value) return;
  chart = init(host.value, "libramas-blue", { renderer: "canvas" });
  render(props.option);
  chart.on("click", (params) => emit("chartClick", params));
  observer = new ResizeObserver(() => {
    if (resizeFrame !== undefined) cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => { resizeFrame = undefined; chart?.resize(); });
  });
  observer.observe(host.value);
});
watch(() => props.option, render, { deep: true });
onBeforeUnmount(() => {
  observer?.disconnect();
  if (resizeFrame !== undefined) cancelAnimationFrame(resizeFrame);
  chart?.dispose();
});
</script>

<template>
  <div class="echart-shell">
    <div ref="host" class="echart" role="img" tabindex="0" :aria-label="`${ariaLabel}。可使用鼠标或触控查看提示。`" />
    <div v-if="loading || error || empty" class="echart-status" role="status">
      <span>{{ loading ? '正在读取真实数据…' : error || emptyText }}</span>
    </div>
  </div>
</template>
