<script setup lang="ts">
import { computed, onMounted, watch } from "vue";
import { useKnowledgeReviewStore } from "../stores/knowledgeReview";

const reviews = useKnowledgeReviewStore();
const filters = [["PENDING", "待审核"], ["EVIDENCE_REQUESTED", "待补证"], ["APPROVED", "已接受"], ["REJECTED", "已拒绝"], ["ALL", "全部"]] as const;
const pendingCount = computed(() => reviews.items.filter((item) => item.status === "PENDING").length);
onMounted(() => { void reviews.load(); });
watch(() => reviews.filter, () => { void reviews.load(); });
</script>

<template>
  <div class="knowledge-review-view">
    <header class="view-header"><div><span class="eyebrow">LIBRARIAN KNOWLEDGE GOVERNANCE</span><h1>知识审核</h1><p>Agent 只提出证据化建议；馆员动作仅追加审核事实，不会直接修改 Neo4j。</p></div><span class="status-label">待审核 {{ pendingCount }}</span></header>
    <section v-if="!reviews.canReview" class="run-state-card is-error-state"><span>权限受限</span><h2>需要馆员知识审核权限</h2><p>读者、访客和 Agent 均不能执行审核动作。请使用已获授权的馆员或研究管理员账号登录。</p></section>
    <template v-else>
      <div class="review-filters segmented"><button v-for="([value,label]) in filters" :key="value" type="button" :class="{ active: reviews.filter === value }" @click="reviews.filter = value">{{ label }}</button></div>
      <section class="knowledge-review-grid glass-panel">
        <aside class="review-list">
          <button v-for="item in reviews.items" :key="item.proposal_uuid" type="button" :class="{ active: reviews.selected?.proposal_uuid === item.proposal_uuid }" @click="reviews.selectedId = item.proposal_uuid">
            <span>{{ item.status }} · {{ Math.round(item.confidence * 100) }}%</span><b>{{ item.reason_codes.join(' · ') }}</b><small>{{ item.subject_id }}</small>
          </button>
          <div v-if="!reviews.items.length && !reviews.loading" class="empty-state"><h3>当前筛选没有提案</h3><p>{{ reviews.error || '没有需要馆员处理的知识冲突。' }}</p></div>
        </aside>
        <article v-if="reviews.selected" class="review-detail">
          <div class="panel-heading"><div><span class="kicker">{{ reviews.selected.proposal_type }}</span><h2>{{ reviews.selected.reason_codes.join(' · ') }}</h2></div><span class="status-label">{{ reviews.selected.status }}</span></div>
          <dl class="review-triple"><div><dt>主体</dt><dd>{{ reviews.selected.subject_id }}</dd></div><div><dt>关系</dt><dd>{{ reviews.selected.relation_type }}</dd></div><div><dt>客体</dt><dd>{{ reviews.selected.object_id }}</dd></div></dl>
          <div class="review-evidence"><h3>Agent 与证据</h3><p><b>{{ reviews.selected.agent_name }}</b> · 置信度 {{ Math.round(reviews.selected.confidence * 100) }}% · {{ reviews.selected.graph_version }}</p><code v-for="ref in reviews.selected.source_refs" :key="ref">{{ ref }}</code></div>
          <div class="review-history"><h3>追加式处理历史</h3><p v-if="!reviews.selected.actions.length">尚无处理事实。批准、拒绝或要求补证后只会新增一条事实。</p><ol><li v-for="fact in reviews.selected.actions" :key="fact.fact_uuid"><b>v{{ fact.version }} · {{ fact.action }}</b><span>{{ fact.reason_code }}</span><small>馆员 {{ fact.librarian_user_id }} · {{ new Date(fact.occurred_at).toLocaleString() }}</small></li></ol></div>
          <div class="review-actions"><button type="button" :disabled="reviews.loading" @click="reviews.act('APPROVE')">接受证据</button><button type="button" :disabled="reviews.loading" @click="reviews.act('REQUEST_EVIDENCE')">要求补证</button><button type="button" :disabled="reviews.loading" @click="reviews.act('REJECT')">拒绝提案</button></div>
          <p class="review-safety">本操作 Neo4j 写入恒为 0；已批准提案仅可进入下一图版本的独立 ChangePlan。</p>
          <p v-if="reviews.error" class="inline-error">{{ reviews.error }}</p>
        </article>
      </section>
    </template>
  </div>
</template>
