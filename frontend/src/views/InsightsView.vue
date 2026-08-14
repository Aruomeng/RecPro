<script setup lang="ts">
import { computed, onMounted } from "vue";
import type { EChartsCoreOption as EChartsOption } from "echarts/core";
import EChart from "../components/EChart.vue";
import { useLibraryStore } from "../stores/library";
import { useRecommendationStore } from "../stores/recommendation";
const library = useLibraryStore(); const recommendation = useRecommendationStore();
onMounted(() => void library.loadOverview());
const colors = ["#d7a94f", "#4e9d7a", "#70a8bd", "#a77f65", "#9988b6", "#b5c486"];
const category = computed<EChartsOption>(() => ({ tooltip: { trigger: "item" }, series: [{ type: "sunburst", radius: ["18%", "88%"], data: (library.overview?.categories ?? []).map((x, i) => ({ name: x.name, value: x.count, itemStyle: { color: colors[i % colors.length] } })), label: { color: "#eef5f1", rotate: "radial" } }] }));
const decades = computed<EChartsOption>(() => ({ tooltip: {}, grid: { left: 42, right: 18, top: 22, bottom: 34 }, xAxis: { type: "category", data: (library.overview?.publication_decades ?? []).map(x => `${x.year}s`), axisLabel: { color: "#98aea5" } }, yAxis: { type: "value", axisLabel: { color: "#98aea5" }, splitLine: { lineStyle: { color: "rgba(255,255,255,.07)" } } }, series: [{ type: "bar", data: (library.overview?.publication_decades ?? []).map(x => x.count), itemStyle: { color: "#d7a94f", borderRadius: [6,6,0,0] } }] }));
const availabilityNames: Record<string, string> = { AVAILABLE_BORROW: "可借阅", AVAILABLE_ONLINE: "在线可读", REFERENCE_ONLY: "馆内参考", TEMPORARILY_UNAVAILABLE: "暂不可用", REMOVED: "已下架" };
const availability = computed<EChartsOption>(() => ({ tooltip: { trigger: "item" }, series: [{ type: "pie", radius: ["50%", "78%"], data: (library.overview?.availability ?? []).map((x, i) => ({ name: availabilityNames[x.name] || x.name, value: x.count, itemStyle: { color: colors[i % colors.length] } })), label: { color: "#d5e4de" } }] }));
const topics = computed<EChartsOption>(() => ({ tooltip: {}, xAxis: { show: false }, yAxis: { show: false }, series: [{ type: "scatter", symbolSize: (value: number[]) => 24 + Math.sqrt(value[2] || 1) * 4, data: (library.overview?.popular_topics ?? []).map((x, i) => [i % 5, Math.floor(i / 5), x.count, x.name]), label: { show: true, formatter: (p: any) => p.value[3], color: "#fff" }, itemStyle: { color: (p: any) => colors[p.dataIndex % colors.length], opacity: .82 } }] }));
const channels = computed<EChartsOption>(() => { const sums: Record<string, number> = {}; recommendation.items.forEach(item => Object.entries(item.evidence?.channel_scores ?? {}).forEach(([k,v]) => sums[k] = (sums[k] ?? 0) + v)); const n = Math.max(1, recommendation.items.length); return { radar: { indicator: ["MYSQL","GRAPH","VECTOR"].map(name => ({ name, max: 1 })), axisName: { color: "#dce9e4" }, splitLine: { lineStyle: { color: "rgba(255,255,255,.14)" } } }, series: [{ type: "radar", data: [{ value: [sums.MYSQL/n || 0, sums.GRAPH/n || 0, sums.VECTOR/n || 0], areaStyle: { color: "rgba(215,169,79,.35)" }, lineStyle: { color: "#d7a94f" } }] }] }; });
</script>
<template>
  <div class="insights-view"><header class="view-header"><div><span class="eyebrow">COLLECTION INTELLIGENCE</span><h1>馆藏洞察</h1><p>全部图表来自 Exploration 只读接口；不使用预置统计。</p></div><span class="data-stamp">数据版本 {{ library.overview?.dataset_version || '读取中' }}</span></header>
    <div class="insight-grid">
      <section class="insight-card glass-panel is-wide"><div class="mini-panel-title"><span>分类知识版图</span><b>Top 10</b></div><EChart :option="category" /></section>
      <section class="insight-card glass-panel"><div class="mini-panel-title"><span>馆藏可用状态</span><b>{{ library.overview?.totals.resources.toLocaleString() || '—' }} 项</b></div><EChart :option="availability" /></section>
      <section class="insight-card glass-panel is-wide"><div class="mini-panel-title"><span>出版年代分布</span><b>时间序列</b></div><EChart :option="decades" /></section>
      <section class="insight-card glass-panel"><div class="mini-panel-title"><span>热门主题</span><b>馆藏标签</b></div><EChart :option="topics" /></section>
      <section class="insight-card glass-panel"><div class="mini-panel-title"><span>当前推荐通道贡献</span><b>{{ recommendation.items.length ? '实时结果' : '等待推荐' }}</b></div><EChart :option="channels" /></section>
    </div>
  </div>
</template>
