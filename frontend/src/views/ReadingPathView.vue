<script setup lang="ts">
import { computed } from "vue";
import BookCover from "../components/BookCover.vue";
import { useLibraryStore } from "../stores/library";
import { useRecommendationStore } from "../stores/recommendation";
const recommendation = useRecommendationStore();
const library = useLibraryStore();
const stages = computed(() => (recommendation.result?.groups ?? []).sort((a, b) => a.order_no - b.order_no).map((group) => ({ ...group, items: recommendation.items.filter((item) => item.group_id === group.group_id) })));
function start(): void { void recommendation.start("READING_PATH"); }
</script>
<template>
  <div class="path-view">
    <header class="view-header"><div><span class="eyebrow">PERSONAL LEARNING JOURNEY</span><h1>阅读路径</h1><p>由真实资源难度和稳定排序构建入门、进阶、深化三阶段。</p></div>
      <form class="path-create" @submit.prevent="start"><input v-model="recommendation.query" aria-label="阅读路径主题" placeholder="输入学习主题" /><button type="submit" :disabled="recommendation.phase === 'streaming'">生成路径 →</button></form>
    </header>
    <section v-if="stages.length" class="learning-path">
      <article v-for="(stage, stageIndex) in stages" :key="stage.group_id" class="path-stage glass-panel">
        <div class="stage-label"><span>STAGE 0{{ stageIndex + 1 }}</span><h2>{{ stage.title }}</h2><p>{{ stage.goal || '沿着知识关系逐步深入' }}</p></div>
        <div class="stage-line" />
        <div class="stage-books">
          <button v-for="item in stage.items" :key="item.item_id" type="button" class="path-book" @click="library.openResource(item.resource.resource_id)">
            <BookCover :title="item.resource.title" :category="stage.title" size="small" /><span><b>{{ item.resource.title }}</b><small>阅读顺序 {{ item.rank_no }} · 难度 {{ item.resource.difficulty_level || '待评估' }}</small><em>{{ item.reason_summary }}</em></span>
          </button>
        </div>
      </article>
    </section>
    <section v-else class="path-empty glass-panel"><div class="path-curve" aria-hidden="true"><i /><i /><i /></div><h2>一条适合你的知识路径，正在等待主题</h2><p>系统不会随机分组；有难度标注时按真实难度组织，缺失时按稳定排名三等分。</p><button type="button" @click="start">生成“{{ recommendation.query }}”路径</button></section>
  </div>
</template>
