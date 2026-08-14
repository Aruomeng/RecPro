<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useRouter } from "vue-router";
import type { EChartsCoreOption as EChartsOption } from "echarts/core";

import EChart from "../components/EChart.vue";
import GraphCanvas from "../components/GraphCanvas.vue";
import { useLibraryStore } from "../stores/library";
import { useRecommendationStore } from "../stores/recommendation";

const library = useLibraryStore();
const recommendation = useRecommendationStore();
const router = useRouter();
const topics = ["多智能体", "人工智能", "知识图谱", "图书馆学"];
const stats = computed(() => [
  ["馆藏资源", library.overview?.totals.resources ?? null, "册/项"],
  ["图书", library.overview?.totals.books ?? null, "册"],
  ["图节点", library.overview?.graph.nodes ?? null, "个"],
  ["知识关系", library.overview?.graph.relationships ?? null, "条"],
]);
const categoryOption = computed<EChartsOption>(() => ({
  tooltip: { trigger: "item" },
  series: [{
    type: "pie", radius: ["58%", "82%"], center: ["50%", "52%"], padAngle: 3,
    itemStyle: { borderRadius: 8, borderColor: "#102c24", borderWidth: 2 },
    label: { show: false },
    data: (library.overview?.categories ?? []).slice(0, 6).map((item) => ({ name: item.name, value: item.count })),
  }],
}));

onMounted(async () => {
  await library.loadOverview();
  const topic = topics[1];
  if (!library.graph) await library.searchGraph(topic);
});

function explore(topic: string, route = "/recommend"): void {
  recommendation.query = topic;
  void router.push(route);
}
</script>

<template>
  <div class="home-view">
    <section class="home-hero">
      <div class="hero-orbit" aria-hidden="true"><i /><i /><i /></div>
      <div class="home-hero__copy">
        <span class="eyebrow">LIBRAMAS SMART LIBRARY</span>
        <h1>今天，想探索什么？</h1>
        <p>八位智能体将从真实馆藏、知识图谱与语义空间中，为你编织一条专属阅读线索。</p>
        <form class="hero-search" @submit.prevent="explore(recommendation.query)">
          <span aria-hidden="true">⌕</span>
          <input v-model="recommendation.query" aria-label="输入想探索的主题" placeholder="试试：多智能体如何改变智慧图书馆？" />
          <button type="submit">开始探索 <b>→</b></button>
        </form>
        <div class="topic-shortcuts" aria-label="热门主题">
          <button v-for="topic in topics" :key="topic" type="button" @click="explore(topic)"><i />{{ topic }}</button>
        </div>
      </div>
      <div class="hero-knowledge glass-panel">
        <div class="mini-panel-title"><span>LIVE KNOWLEDGE MAP</span><b>{{ library.graph?.nodes.length ?? 0 }} 个局部节点</b></div>
        <GraphCanvas :graph="library.graph" compact @node-click="(node) => node.resource_id && library.openResource(node.resource_id)" />
        <button class="panel-link" type="button" @click="router.push('/graph')">进入知识宇宙 →</button>
      </div>
    </section>

    <section class="home-dashboard">
      <div class="live-stats glass-panel">
        <div v-for="([label, value, unit], index) in stats" :key="String(label)" class="stat-block">
          <span>0{{ index + 1 }} / {{ label }}</span>
          <strong>{{ value === null ? '—' : Number(value).toLocaleString('zh-CN') }}</strong><em>{{ unit }}</em>
        </div>
      </div>
      <div class="category-mini glass-panel">
        <div class="mini-panel-title"><span>馆藏分类分布</span><b>真实只读数据</b></div>
        <EChart :option="categoryOption" aria-label="馆藏分类分布图" />
      </div>
      <div class="quick-actions">
        <button type="button" class="quick-card is-primary" @click="explore(recommendation.query, '/recommend')"><span>01</span><b>为我推荐</b><small>多源召回 · 动态排序</small><i>↗</i></button>
        <button type="button" class="quick-card" @click="explore(recommendation.query, '/graph')"><span>02</span><b>探索知识图谱</b><small>主题 · 作者 · 书籍关系</small><i>↗</i></button>
        <button type="button" class="quick-card" @click="explore(recommendation.query, '/path')"><span>03</span><b>生成阅读路径</b><small>入门 · 进阶 · 深化</small><i>↗</i></button>
      </div>
    </section>
  </div>
</template>
