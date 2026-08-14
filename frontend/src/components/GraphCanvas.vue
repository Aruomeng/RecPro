<script setup lang="ts">
import { computed } from "vue";
import type { EChartsCoreOption as EChartsOption } from "echarts/core";
import type { GraphNode, GraphView } from "../domain/exploration";
import EChart from "./EChart.vue";

const props = defineProps<{ graph: GraphView | null; compact?: boolean }>();
const emit = defineEmits<{ nodeClick: [node: GraphNode] }>();
const types = ["Book", "Topic", "Author", "Publisher", "Category", "Keyword", "SubjectCode"];
const colors = ["#d9a441", "#3f9f78", "#67a7c8", "#c27f61", "#9b8bc4", "#d1bd6a", "#7fa58e"];
const option = computed<EChartsOption>(() => ({
  backgroundColor: "transparent",
  animationDuration: 700,
  tooltip: { trigger: "item", backgroundColor: "#102c24", borderColor: "#42685c", textStyle: { color: "#fff" } },
  legend: props.compact ? undefined : [{ data: types.map((name) => ({ name })), bottom: 0, textStyle: { color: "#9eb3aa" } }],
  series: [{
    type: "graph", layout: "force", roam: true, draggable: true, focusNodeAdjacency: true,
    force: { repulsion: props.compact ? 85 : 160, edgeLength: props.compact ? 55 : 100, gravity: 0.08 },
    categories: types.map((name, index) => ({ name, itemStyle: { color: colors[index] } })),
    label: { show: !props.compact, color: "#eef5f1", fontSize: 11, formatter: "{b}" },
    edgeSymbol: ["none", "arrow"], edgeSymbolSize: 6,
    lineStyle: { color: "source", opacity: 0.34, width: 1.2, curveness: 0.08 },
    emphasis: { focus: "adjacency", lineStyle: { opacity: 0.9, width: 2 } },
    data: (props.graph?.nodes ?? []).map((node) => ({
      id: node.id, name: node.label, value: node.label, category: Math.max(0, types.indexOf(node.type)),
      symbolSize: node.type === "Book" ? (props.compact ? 20 : 34) : (props.compact ? 13 : 23),
    })),
    links: (props.graph?.edges ?? []).map((edge) => ({ source: edge.source, target: edge.target, value: 1, name: edge.label })),
  }],
}));
function clicked(params: unknown): void {
  const candidate = params as { dataType?: string; data?: { id?: string } };
  const node = props.graph?.nodes.find((item) => item.id === candidate.data?.id);
  if (candidate.dataType === "node" && node) emit("nodeClick", node);
}
</script>
<template><EChart class="graph-canvas" :option="option" aria-label="馆藏知识图谱" @chart-click="clicked" /></template>
