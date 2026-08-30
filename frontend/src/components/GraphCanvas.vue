<script setup lang="ts">
import { computed } from "vue";
import type { EChartsCoreOption as EChartsOption } from "echarts/core";
import type { GraphNode, GraphView } from "../domain/exploration";
import EChart from "./EChart.vue";
import "../charts/registerGraph";

const props = defineProps<{ graph: GraphView | null; compact?: boolean; allowedTypes?: string[]; selectedId?: string; highlightedEdgeIds?: string[] }>();
const emit = defineEmits<{ nodeClick: [node: GraphNode] }>();
const types = ["Book", "Work", "Topic", "Author", "Publisher", "Category", "Keyword", "SubjectCode"];
const colors = ["#2563eb", "#1d4ed8", "#0891b2", "#4f46e5", "#0284c7", "#7c3aed", "#0d9488", "#64748b"];
const visibleNodes = computed(() => (props.graph?.nodes ?? []).filter((node) => !props.allowedTypes?.length || props.allowedTypes.includes(node.type)));
const visibleIds = computed(() => new Set(visibleNodes.value.map((node) => node.id)));
const option = computed<EChartsOption>(() => ({
  backgroundColor: "transparent",
  animationDuration: 700,
  tooltip: { trigger: "item", backgroundColor: "#ffffff", borderColor: "#dbe4f0", textStyle: { color: "#0f172a" } },
  legend: props.compact ? undefined : [{ data: types.map((name) => ({ name })), bottom: 0, textStyle: { color: "#64748b" } }],
  series: [{
    type: "graph", layout: "force", roam: true, draggable: true, focusNodeAdjacency: true, scaleLimit: { min: 0.45, max: 4 },
    force: { repulsion: props.compact ? 85 : 160, edgeLength: props.compact ? 55 : 100, gravity: 0.08 },
    categories: types.map((name, index) => ({ name, itemStyle: { color: colors[index] } })),
    label: { show: !props.compact, color: "#334155", fontSize: 12, formatter: "{b}", width: 120, overflow: "truncate" },
    labelLayout: { hideOverlap: true, moveOverlap: "shiftY" },
    edgeSymbol: ["none", "arrow"], edgeSymbolSize: 6,
    lineStyle: { color: "source", opacity: 0.34, width: 1.2, curveness: 0.08 },
    emphasis: { focus: "adjacency", label: { show: true, fontWeight: "bold", overflow: "break", width: 180 }, lineStyle: { opacity: 0.9, width: 2 } },
    select: { itemStyle: { borderColor: "#0f172a", borderWidth: 3 } }, selectedMode: "single",
    data: visibleNodes.value.map((node) => ({
      id: node.id,
      name: node.label,
      // Keep the graph metric numeric.  Using the display label as ECharts'
      // value makes its aria summary attempt to calculate `NaN` for labels
      // that are not numbers, even though the graph itself renders correctly.
      value: 1,
      category: Math.max(0, types.indexOf(node.type)),
      symbolSize: node.type === "Book" ? (props.compact ? 20 : 34) : (props.compact ? 13 : 23),
      selected: node.id === props.selectedId,
    })),
    links: (props.graph?.edges ?? []).filter((edge) => visibleIds.value.has(edge.source) && visibleIds.value.has(edge.target)).map((edge) => ({
      id: edge.id, source: edge.source, target: edge.target, value: 1, name: edge.label,
      lineStyle: props.highlightedEdgeIds?.includes(edge.id) ? { color: "#2563eb", opacity: 1, width: 4 } : undefined,
    })),
  }],
}));
function clicked(params: unknown): void {
  const candidate = params as { dataType?: string; data?: { id?: string } };
  const node = props.graph?.nodes.find((item) => item.id === candidate.data?.id);
  if (candidate.dataType === "node" && node) emit("nodeClick", node);
}
</script>
<template><EChart class="graph-canvas" :option="option" :empty="!graph?.nodes.length" empty-text="当前查询没有可展示的图谱节点" aria-label="馆藏知识图谱，可拖拽缩放并点击节点展开" @chart-click="clicked" /></template>
