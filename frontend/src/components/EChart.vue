<script setup lang="ts">
import { BarChart, GraphChart, PieChart, RadarChart, ScatterChart, SunburstChart } from "echarts/charts";
import { AriaComponent, GridComponent, LegendComponent, RadarComponent, TooltipComponent } from "echarts/components";
import { init, use } from "echarts/core";
import type { ECharts, EChartsCoreOption as EChartsOption } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps<{ option: EChartsOption; ariaLabel?: string }>();
const emit = defineEmits<{ chartClick: [params: unknown] }>();
const host = ref<HTMLDivElement | null>(null);
let chart: ECharts | undefined;
let observer: ResizeObserver | undefined;
let resizeFrame: number | undefined;

use([
  BarChart, GraphChart, PieChart, RadarChart, ScatterChart, SunburstChart,
  AriaComponent, GridComponent, LegendComponent, RadarComponent, TooltipComponent, CanvasRenderer,
]);

onMounted(() => {
  if (!host.value) return;
  chart = init(host.value, undefined, { renderer: "canvas" });
  chart.setOption(props.option);
  chart.on("click", (params) => emit("chartClick", params));
  observer = new ResizeObserver(() => {
    if (resizeFrame !== undefined) cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => { resizeFrame = undefined; chart?.resize(); });
  });
  observer.observe(host.value);
});
watch(() => props.option, (option) => chart?.setOption(option, { notMerge: true }), { deep: true });
onBeforeUnmount(() => {
  observer?.disconnect();
  if (resizeFrame !== undefined) cancelAnimationFrame(resizeFrame);
  chart?.dispose();
});
</script>

<template><div ref="host" class="echart" role="img" :aria-label="ariaLabel" /></template>
