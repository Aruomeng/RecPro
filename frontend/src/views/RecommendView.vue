<script setup lang="ts">
import { computed } from "vue";
import AgentStage from "../components/AgentStage.vue";
import BookCover from "../components/BookCover.vue";
import { useLibraryStore } from "../stores/library";
import { useRecommendationStore } from "../stores/recommendation";

const recommendation = useRecommendationStore();
const library = useLibraryStore();
const outputs = [
  ["TOPIC_RESOURCES", "主题书单"], ["PERSONALIZED_FEED", "个性推荐"], ["READING_PATH", "阅读路径"],
] as const;
const phaseText = computed(() => ({ idle: "等待探索", starting: "正在建立任务", streaming: "Agent 协同运行中", clarification: "需要你的选择", success: "推荐已完成", error: "任务需要重试" }[recommendation.phase]));
</script>

<template>
  <div class="recommend-view view-grid">
    <section class="recommend-command glass-panel">
      <div class="panel-heading"><div><span class="kicker">INTELLIGENT RECOMMENDATION</span><h1>智能推荐</h1></div><span class="phase-chip">{{ phaseText }}</span></div>
      <label class="query-box"><span>告诉智能体你想了解什么</span><textarea v-model="recommendation.query" rows="3" placeholder="输入一个主题、问题或阅读目标…" /></label>
      <div class="output-modes"><button v-for="([value, label]) in outputs" :key="value" type="button" :class="{ active: recommendation.outputType === value }" @click="recommendation.outputType = value">{{ label }}</button></div>
      <button class="primary-action" type="button" :disabled="recommendation.phase === 'streaming' || recommendation.phase === 'starting'" @click="recommendation.start()">
        <span>{{ recommendation.phase === 'streaming' ? '协作进行中' : '启动多智能体推荐' }}</span><b>→</b>
      </button>
      <p v-if="recommendation.error" class="inline-error">{{ recommendation.error }}</p>
      <div class="channel-strip">
        <span><i class="mysql" />MySQL<small>结构化馆藏</small></span>
        <span><i class="neo4j" />Neo4j<small>知识关联</small></span>
        <span><i class="chroma" />Chroma<small>语义相似</small></span>
      </div>
    </section>
    <AgentStage />

    <section v-if="recommendation.phase === 'clarification'" class="clarification-stage glass-panel full-span">
      <span class="eyebrow">CLARIFICATION</span><h2>再告诉我们一点</h2>
      <div v-for="question in recommendation.result?.questions" :key="question.slot" class="question-block">
        <h3>{{ question.question }}</h3>
        <div class="option-cards"><button v-for="option in question.options" :key="option" type="button" :class="{ active: recommendation.answers[question.slot] === option }" @click="recommendation.answers[question.slot] = option">{{ option }}</button></div>
      </div>
      <button class="primary-action compact" type="button" @click="recommendation.clarify()">继续同一任务 →</button>
    </section>

    <section v-if="recommendation.items.length" class="result-shelf full-span">
      <div class="panel-heading"><div><span class="kicker">CURATED FOR THIS SESSION</span><h2>为你找到 {{ recommendation.items.length }} 本书</h2></div><span class="trace-label">Trace {{ recommendation.result?.trace_id.slice(0, 8) }}</span></div>
      <div class="book-shelf">
        <article v-for="item in recommendation.items" :key="item.item_id" class="book-card" tabindex="0" @click="library.openResource(item.resource.resource_id)" @keydown.enter="library.openResource(item.resource.resource_id)">
          <BookCover :title="item.resource.title" :category="item.evidence?.primary_channel" />
          <div class="book-card__info">
            <span class="rank-mark">#{{ String(item.rank_no).padStart(2, '0') }} · {{ item.evidence?.primary_channel || 'HYBRID' }}</span>
            <h3>{{ item.resource.title }}</h3><p>{{ item.resource.authors.join(' · ') || '作者信息待补充' }}</p>
            <div class="confidence"><i :style="{ width: `${Math.round(item.evidence_confidence * 100)}%` }" /><span>{{ Math.round(item.evidence_confidence * 100) }}% 匹配</span></div>
            <small>{{ item.reason_summary }}</small>
          </div>
        </article>
      </div>
    </section>
    <section v-else class="recommend-empty full-span"><span>⌁</span><p>输入主题启动任务，真实 Agent 事件和推荐结果将在这里展开。</p></section>
  </div>
</template>
