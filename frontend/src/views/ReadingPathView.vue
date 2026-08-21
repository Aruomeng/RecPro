<script setup lang="ts">
import { computed } from "vue";
import BookCover from "../components/BookCover.vue";
import { useLibraryStore } from "../stores/library";
import { useRecommendationStore } from "../stores/recommendation";
const recommendation = useRecommendationStore();
const library = useLibraryStore();
const stages = computed(() => (recommendation.result?.groups ?? []).sort((a, b) => a.order_no - b.order_no).map((group) => ({ ...group, items: recommendation.items.filter((item) => item.group_id === group.group_id) })));
const preview = [
  { index: "01", title: "入门", range: "难度 1–2", goal: "建立概念框架与基础术语" },
  { index: "02", title: "进阶", range: "难度 3", goal: "理解方法、系统结构与应用" },
  { index: "03", title: "深化", range: "难度 4", goal: "进入研究问题与专题实践" },
];
function stageStats(items: typeof recommendation.items): { average: string; available: number } {
  const difficulties = items.map((item) => item.resource.difficulty_level).filter((value): value is number => typeof value === "number");
  return { average: difficulties.length ? (difficulties.reduce((sum, value) => sum + value, 0) / difficulties.length).toFixed(1) : "稳定排名", available: items.filter((item) => !item.unavailable_now).length };
}
function start(): void { void recommendation.start("READING_PATH"); }
</script>
<template>
  <div class="path-view">
    <header class="view-header"><div><span class="eyebrow">PERSONAL LEARNING JOURNEY</span><h1>阅读路径</h1><p>由真实资源难度和稳定排序构建入门、进阶、深化三阶段。</p></div>
      <form class="path-create" @submit.prevent="start"><input v-model="recommendation.query" aria-label="阅读路径主题" placeholder="输入学习主题" /><button type="submit" :disabled="recommendation.phase === 'streaming'">生成路径 →</button></form>
    </header>
    <section v-if="stages.length" class="learning-path">
      <article v-for="(stage, stageIndex) in stages" :key="stage.group_id" class="path-stage glass-panel">
        <div class="stage-label"><span>STAGE 0{{ stageIndex + 1 }}</span><h2>{{ stage.title }}</h2><p>{{ stage.goal || '沿着知识关系逐步深入' }}</p><dl><div><dt>书目</dt><dd>{{ stage.items.length }}</dd></div><div><dt>平均难度</dt><dd>{{ stageStats(stage.items).average }}</dd></div><div><dt>当前可用</dt><dd>{{ stageStats(stage.items).available }}</dd></div></dl></div>
        <div class="stage-line" />
        <div class="stage-books">
          <button v-for="item in stage.items" :key="item.item_id" type="button" class="path-book" @click="library.openResource(item.resource.resource_id)">
            <BookCover :title="item.resource.title" :category="stage.title" size="small" /><span><b>{{ item.resource.title }}</b><small>阅读顺序 {{ item.rank_no }} · 难度 {{ item.resource.difficulty_level || '按稳定排名分组' }} · 置信度 {{ Math.round(item.evidence_confidence * 100) }}%</small><em>{{ item.reason_summary }}</em><strong>{{ item.unavailable_now ? '当前暂不可用' : '可继续查看馆藏' }}</strong></span>
          </button>
        </div>
      </article>
    </section>
    <section v-else class="path-empty glass-panel">
      <div><span class="eyebrow">THREE-STAGE PREVIEW</span><h2>把一个主题组织成连续的学习路线</h2><p>系统不会随机分组：有真实难度时按 1–2、3、4 组织；缺少难度时按稳定推荐排名三等分，并在结果中明确标注依据。</p></div>
      <div class="path-preview"><article v-for="stage in preview" :key="stage.index"><span>{{ stage.index }}</span><i /><h3>{{ stage.title }}</h3><b>{{ stage.range }}</b><p>{{ stage.goal }}</p></article></div>
      <div class="path-empty-action"><span>当前主题</span><strong>{{ recommendation.query || '尚未输入' }}</strong><button type="button" :disabled="recommendation.phase === 'streaming'" @click="start">{{ recommendation.phase === 'streaming' ? '真实 Agent 正在生成…' : `生成“${recommendation.query}”路径` }}</button></div>
    </section>
  </div>
</template>
