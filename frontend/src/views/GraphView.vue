<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import GraphCanvas from "../components/GraphCanvas.vue";
import type { GraphNode } from "../domain/exploration";
import { useLibraryStore } from "../stores/library";
import { useRecommendationStore } from "../stores/recommendation";
import { useAgentWorkspaceStore } from "../stores/agentWorkspace";

const library = useLibraryStore();
const recommendation = useRecommendationStore();
const router = useRouter();
const route = useRoute();
const workspace = useAgentWorkspaceStore();
const selected = ref<GraphNode | null>(null);
const pathStart = ref<GraphNode | null>(null);
const enabledTypes = ref<string[]>([]);
const typeCounts = computed(() => Object.entries((library.graph?.nodes ?? []).reduce<Record<string, number>>((acc, node) => { acc[node.type] = (acc[node.type] ?? 0) + 1; return acc; }, {})));
const entityTypeCount = computed(() => typeCounts.value.length);
const neighbors = computed(() => {
  if (!selected.value || !library.graph) return [];
  const ids = new Set(library.graph.edges.filter((edge) => edge.source === selected.value?.id || edge.target === selected.value?.id).map((edge) => edge.source === selected.value?.id ? edge.target : edge.source));
  return library.graph.nodes.filter((node) => ids.has(node.id)).slice(0, 12);
});
const relationCounts = computed(() => Object.entries((library.graph?.edges ?? []).filter((edge) => !selected.value || edge.source === selected.value.id || edge.target === selected.value.id).reduce<Record<string, number>>((acc, edge) => { acc[edge.label || edge.type] = (acc[edge.label || edge.type] ?? 0) + 1; return acc; }, {})).sort((a,b) => b[1]-a[1]).slice(0,6));
const activePath = computed(() => library.graphPaths?.paths.find((path) => path.path_id === library.highlightedPathId) ?? library.graphPaths?.paths[0]);
onMounted(() => {
  const routedQuery = typeof route.query.q === "string" ? route.query.q.trim() : "";
  if (routedQuery) void library.searchGraph(routedQuery);
  else if (!library.graph) void library.searchGraph();
});
function select(node: GraphNode): void {
  selected.value = node;
  if (pathStart.value && pathStart.value.id !== node.id) void library.loadGraphPaths(pathStart.value.id, node.id);
  void Promise.all([
    library.expandNode(node.id),
    workspace.observe("GRAPH_NODE_SELECTED", { entity_id: node.id, entity_type: node.type, label: node.label }),
  ]);
}
function setPathStart(): void { if (selected.value) { pathStart.value = selected.value; library.graphPaths = null; library.highlightedPathId = null; } }
function recommend(): void { if (!selected.value) return; recommendation.query = selected.value.label; void router.push("/recommend"); }
function toggleType(type: string): void { enabledTypes.value = enabledTypes.value.includes(type) ? enabledTypes.value.filter((item) => item !== type) : [...enabledTypes.value, type]; }
</script>
<template>
  <div class="graph-view">
    <header class="view-header"><div><span class="eyebrow">KNOWLEDGE GRAPH</span><h1>馆藏知识宇宙</h1><p>搜索真实实体，点击节点按需展开一跳关系。</p></div>
      <form class="graph-search" @submit.prevent="library.searchGraph()"><input v-model="library.graphQuery" aria-label="搜索知识图谱" placeholder="搜索书名、主题、作者、出版社…" /><button type="submit">搜索</button></form>
    </header>
    <div class="graph-metrics metric-grid">
      <div class="metric-card"><span>当前节点</span><strong>{{ library.graph?.nodes.length ?? 0 }}</strong><small>有界局部子图</small></div><div class="metric-card"><span>当前关系</span><strong>{{ library.graph?.edges.length ?? 0 }}</strong><small>白名单公开关系</small></div><div class="metric-card"><span>实体类型</span><strong>{{ entityTypeCount }}</strong><small>Book / Work 分层可筛选</small></div><div class="metric-card"><span>证据路径</span><strong class="is-text">{{ library.graphPaths?.paths.length ?? 0 }} 条</strong><small>最多 3 跳 / 10 条</small></div>
    </div>
    <section class="graph-lab glass-panel">
      <aside class="graph-filter-panel">
        <div class="section-caption"><b>实体类型</b><span>点击筛选</span></div>
        <button v-for="([type, count]) in typeCounts" :key="type" type="button" :class="{ active: enabledTypes.includes(type) }" @click="toggleType(type)"><i :class="`type-${type}`" /><span>{{ type }}</span><b>{{ count }}</b></button>
        <p>未选择时显示全部类型。筛选仅改变当前视图，不修改图数据库。</p>
      </aside>
      <div class="graph-main-panel">
        <div class="graph-toolbar"><span>查询：{{ library.graph?.query || library.graphQuery }}</span><em v-if="library.graph?.truncated">已展示局部子图</em></div>
        <div v-if="typeof route.query.evidence_ref === 'string'" class="graph-evidence-context"><b>来自推荐结果的路径证据核验</b><span>{{ route.query.evidence_ref }}</span><small>当前展示与该书相关的真实局部子图；精确多跳高亮仅在对应 v2 图版本可用时呈现。</small></div>
        <div v-if="pathStart" class="graph-path-notice"><span>路径起点：<b>{{ pathStart.label }}</b></span><span v-if="activePath">当前高亮 {{ activePath.hop_count }} 跳 · 证据分 {{ Math.round(activePath.score * 100) }}%</span><span v-else>再选择一个节点，查询 3 跳以内证据</span><button type="button" @click="pathStart = null; library.graphPaths = null; library.highlightedPathId = null">结束路径模式</button></div>
        <GraphCanvas v-if="library.graph?.nodes.length" :graph="library.graph" :allowed-types="enabledTypes" :selected-id="selected?.id" :highlighted-edge-ids="activePath?.edge_ids" @node-click="select" />
        <div v-else-if="library.loadingGraph" class="loading-state"><h3>正在读取有界子图…</h3><p>查询只允许白名单实体与一跳关系。</p></div>
        <div v-else class="empty-state"><h3>当前没有图谱结果</h3><p>{{ library.error || `Neo4j 未返回与“${library.graphQuery}”匹配的公开节点。` }}</p><button class="state-action" type="button" @click="library.searchGraph()">重新读取</button></div>
        <div class="graph-safety">最多 60 节点 · 120 关系 · 3 秒边界 · 只读查询</div>
      </div>
      <aside class="graph-detail-panel">
        <template v-if="selected">
          <span class="status-label">{{ selected.type }}</span><h2>{{ selected.label }}</h2><p>{{ selected.subtitle || '已读取该实体的一跳公开关系。' }}</p>
          <div class="relation-bars"><h3>关系类型</h3><span v-for="([label,count]) in relationCounts" :key="label"><b>{{ label }}</b><i><em :style="{ width: `${Math.round(count / Math.max(1, relationCounts[0]?.[1] ?? 1) * 100)}%` }" /></i><strong>{{ count }}</strong></span></div>
          <div class="neighbor-list"><h3>一跳邻居 · {{ neighbors.length }}</h3><button v-for="node in neighbors" :key="node.id" type="button" @click="select(node)"><span>{{ node.type }}</span><b>{{ node.label }}</b></button></div>
          <div class="graph-detail-actions"><button type="button" @click="setPathStart">设为证据路径起点</button><button v-if="selected.resource_id" type="button" @click="library.openResource(selected.resource_id)">查看馆藏</button><button v-if="selected.type === 'Topic' || selected.type === 'Category'" type="button" @click="recommend">围绕它推荐</button></div>
        </template>
        <div v-else class="detail-placeholder"><span>选择一个节点</span><h2>查看实体详情与多跳证据</h2><p>点击图中的作品、图书、主题、作者、出版社或分类节点。</p></div>
      </aside>
    </section>
  </div>
</template>
