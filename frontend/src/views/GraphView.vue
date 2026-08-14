<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import GraphCanvas from "../components/GraphCanvas.vue";
import type { GraphNode } from "../domain/exploration";
import { useLibraryStore } from "../stores/library";
import { useRecommendationStore } from "../stores/recommendation";

const library = useLibraryStore();
const recommendation = useRecommendationStore();
const router = useRouter();
const selected = ref<GraphNode | null>(null);
const typeCounts = computed(() => Object.entries((library.graph?.nodes ?? []).reduce<Record<string, number>>((acc, node) => { acc[node.type] = (acc[node.type] ?? 0) + 1; return acc; }, {})));
onMounted(() => { if (!library.graph) void library.searchGraph(); });
function select(node: GraphNode): void { selected.value = node; void library.expandNode(node.id); }
function recommend(): void { if (!selected.value) return; recommendation.query = selected.value.label; void router.push("/recommend"); }
</script>
<template>
  <div class="graph-view">
    <header class="view-header"><div><span class="eyebrow">KNOWLEDGE GRAPH</span><h1>馆藏知识宇宙</h1><p>搜索真实实体，点击节点按需展开一跳关系。</p></div>
      <form class="graph-search" @submit.prevent="library.searchGraph()"><input v-model="library.graphQuery" aria-label="搜索知识图谱" placeholder="搜索书名、主题、作者、出版社…" /><button type="submit">搜索</button></form>
    </header>
    <section class="graph-workspace glass-panel">
      <div class="graph-toolbar"><span v-for="([type, count]) in typeCounts" :key="type"><i :class="`type-${type}`" />{{ type }} <b>{{ count }}</b></span><em v-if="library.graph?.truncated">已展示局部子图</em></div>
      <GraphCanvas :graph="library.graph" @node-click="select" />
      <div v-if="library.loadingGraph" class="graph-loader">正在读取有界子图…</div>
      <aside v-if="selected" class="graph-node-card">
        <span>{{ selected.type }}</span><h2>{{ selected.label }}</h2><p>{{ selected.subtitle || '点击已加载该实体的一跳关系。' }}</p>
        <button v-if="selected.resource_id" type="button" @click="library.openResource(selected.resource_id)">查看馆藏详情</button>
        <button v-if="selected.type === 'Topic' || selected.type === 'Category'" type="button" @click="recommend">围绕它推荐</button>
      </aside>
      <div class="graph-safety">最多 60 节点 · 120 关系 · 只读查询</div>
    </section>
  </div>
</template>
