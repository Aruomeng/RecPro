<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useRouter } from "vue-router";
import type { EChartsCoreOption as EChartsOption } from "echarts/core";

import EChart from "../components/EChart.vue";
import "../charts/registerPie";
import GraphCanvas from "../components/GraphCanvas.vue";
import { useLibraryStore } from "../stores/library";
import { useRecommendationStore } from "../stores/recommendation";
import { useAgentWorkspaceStore } from "../stores/agentWorkspace";

const library = useLibraryStore();
const recommendation = useRecommendationStore();
const router = useRouter();
const workspace = useAgentWorkspaceStore();
const topics = computed(() => workspace.suggestedTopics.length ? workspace.suggestedTopics : ["多智能体", "人工智能", "知识图谱", "图书馆学"]);
const stats = computed(() => [
  ["馆藏资源", library.overview?.totals.resources ?? null, "册/项", "可检索的真实馆藏总量"],
  ["图书", library.overview?.totals.books ?? null, "册", "已完成书目结构化"],
  ["图节点", library.overview?.graph.nodes ?? null, "个", "书籍、主题与作者实体"],
  ["知识关系", library.overview?.graph.relationships ?? null, "条", "可交互的一跳关联"],
]);
const topCategories = computed(() => (library.overview?.categories ?? []).slice(0, 4));
const availableCount = computed(() => (library.overview?.availability ?? [])
  .filter((item) => item.name === "AVAILABLE_BORROW" || item.name === "AVAILABLE_ONLINE")
  .reduce((total, item) => total + item.count, 0));
const categoryOption = computed<EChartsOption>(() => ({
  tooltip: { trigger: "item" },
  color: ["#2563eb", "#0891b2", "#4f46e5", "#0d9488", "#60a5fa", "#818cf8"],
  series: [{
    type: "pie", radius: ["58%", "82%"], center: ["50%", "52%"], padAngle: 3,
    itemStyle: { borderRadius: 8, borderColor: "#ffffff", borderWidth: 2 },
    label: { show: false },
    data: (library.overview?.categories ?? []).slice(0, 6).map((item) => ({ name: item.name, value: item.count })),
  }],
}));

onMounted(async () => {
  await library.loadOverview();
  const topic = topics.value[1] ?? "人工智能";
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
        <div class="hero-proof" aria-label="推荐工作流">
          <span><b>01</b><strong>理解问题</strong><small>识别主题与阅读目标</small></span>
          <span><b>02</b><strong>连接知识</strong><small>三通道检索真实馆藏</small></span>
          <span><b>03</b><strong>给出依据</strong><small>每本书都有推荐证据</small></span>
        </div>
        <button class="adaptive-summary" type="button" @click="workspace.expanded = true">
          <span><i :class="workspace.state" />全局 Agent Workspace</span>
          <b>{{ workspace.activeCount ? `${workspace.activeCount} 位 Agent 正在协作` : '已感知当前会话与馆藏状态' }}</b>
          <small>{{ workspace.guidanceMessage }} →</small>
        </button>
      </div>
      <div class="hero-knowledge glass-panel">
        <div class="mini-panel-title"><span>LIVE KNOWLEDGE MAP</span><b>{{ library.graph?.nodes.length ?? 0 }} 个局部节点</b></div>
        <GraphCanvas :graph="library.graph" compact @node-click="(node) => node.resource_id && library.openResource(node.resource_id)" />
        <button class="panel-link" type="button" @click="router.push('/graph')">进入知识宇宙 →</button>
      </div>
    </section>

    <section class="home-dashboard">
      <div class="live-stats glass-panel">
        <div v-for="([label, value, unit, note], index) in stats" :key="String(label)" class="stat-block">
          <span>0{{ index + 1 }} / {{ label }}</span>
          <strong>{{ value === null ? '—' : Number(value).toLocaleString('zh-CN') }}</strong><em>{{ unit }}</em>
          <small>{{ note }}</small>
        </div>
      </div>
      <div class="category-mini glass-panel">
        <div class="mini-panel-title"><span>馆藏分类分布</span><b>真实只读数据</b></div>
        <EChart :option="categoryOption" aria-label="馆藏分类分布图" />
        <div class="category-legend">
          <span v-for="(item, index) in topCategories" :key="item.name"><i :class="`tone-${index + 1}`" /><b>{{ item.name }}</b><em>{{ item.count.toLocaleString('zh-CN') }}</em></span>
        </div>
      </div>
      <div class="quick-actions">
        <button type="button" class="quick-card is-primary" @click="explore(recommendation.query, workspace.primaryEntry.route)"><span>01 · REAL AGENTS</span><strong>8 位</strong><b>{{ workspace.primaryEntry.label }}</b><p>看见智能体如何理解问题、召回馆藏并解释每一本书。</p><small>MySQL · Neo4j · Chroma</small><i>↗</i></button>
        <button type="button" class="quick-card" @click="explore(recommendation.query, '/graph')"><span>02 · LIVE GRAPH</span><strong>{{ (library.overview?.graph.nodes ?? 0).toLocaleString('zh-CN') }}</strong><b>探索知识图谱</b><p>搜索真实实体，点击节点展开作者、主题、分类和出版关系。</p><small>最多显示 60 个局部节点</small><i>↗</i></button>
        <button type="button" class="quick-card" @click="explore(recommendation.query, '/path')"><span>03 · READING PATH</span><strong>3 阶段</strong><b>生成阅读路径</b><p>从入门到深化，把推荐书目组织成可继续探索的学习路线。</p><small>{{ availableCount.toLocaleString('zh-CN') }} 项当前可借或在线</small><i>↗</i></button>
      </div>
    </section>
    <section class="home-agent-guidance">
      <div><span>动态交互策略</span><h2>系统会理解你正在做什么，但决定权始终在你手中。</h2><p>Agent 会结合当前页面、真实馆藏、知识图谱、系统健康和已标注的演示外部情境给出建议；不会自动跳转、不会擅自发起推荐，也不会在后台持续调用大模型。</p></div>
      <button type="button" @click="workspace.expanded = true">查看当前策略与依据</button>
    </section>
  </div>
</template>
