<script setup lang="ts">
import { computed, onBeforeUnmount, watch } from "vue";
import { useRouter } from "vue-router";
import type { FeedbackType } from "../domain/interaction";
import { useLibraryStore } from "../stores/library";
import { useInteractionStore } from "../stores/interaction";
import { useRecommendationStore } from "../stores/recommendation";
import { useSessionStore } from "../stores/session";
import { useAuthStore } from "../stores/auth";
import BookCover from "./BookCover.vue";

const library = useLibraryStore();
const recommendation = useRecommendationStore();
const session = useSessionStore();
const auth = useAuthStore();
const interaction = useInteractionStore();
const router = useRouter();

const item = computed(() => recommendation.items.find(
  (candidate) => candidate.resource.resource_id === library.selectedResource?.resource_id,
));
const canWrite = computed(() => interaction.canWrite && Boolean(item.value));
const feedbackAgent = computed(() => interaction.receipt?.agent_action);
const feedbackModeLabel = computed(() => {
  if (session.mode === "guest") return "仅本次会话";
  if (session.mode === "demo") return "研究演示画像 · 真实反馈";
  return auth.canPersistBehavior ? "正式账号 · 已授权学习" : "正式账号 · 需授权行为学习";
});
const feedbackProgressLabel = computed(() => (
  session.mode === "demo" ? "FeedbackLearningAgent 正在更新研究演示画像…" : "FeedbackLearningAgent 正在处理你的反馈…"
));

watch(() => [library.detailOpen, library.selectedResource?.resource_id, session.mode] as const, () => {
  interaction.prepareExposure(library.detailOpen ? item.value : undefined);
}, { immediate: true });

onBeforeUnmount(interaction.clearExposure);

function close(): void { library.detailOpen = false; }
function openGraph(): void {
  if (!library.selectedResource) return;
  library.graphQuery = library.selectedResource.title;
  close();
  void router.push("/graph");
}

async function feedback(type: FeedbackType): Promise<void> {
  await interaction.submit(item.value, type);
}
</script>

<template>
  <Teleport to="body">
    <Transition name="drawer">
      <div v-if="library.detailOpen" class="drawer-layer" role="presentation" @click.self="close">
        <aside class="resource-drawer" role="dialog" aria-modal="true" aria-label="图书详情">
          <button class="icon-button drawer-close" type="button" aria-label="关闭详情" @click="close">×</button>
          <div v-if="!library.selectedResource" class="drawer-loading"><i /> 正在读取真实馆藏详情…</div>
          <template v-else>
            <div class="drawer-book-head">
              <BookCover :title="library.selectedResource.title" :category="library.selectedResource.category_code" size="large" />
              <div>
                <span class="eyebrow">LIBRARY COLLECTION</span>
                <h2>{{ library.selectedResource.title }}</h2>
                <p>{{ library.selectedResource.authors.join(' · ') || '作者信息待补充' }}</p>
                <div class="tag-row">
                  <span>{{ library.selectedResource.publication_year || '年份未知' }}</span>
                  <span>{{ library.selectedResource.publisher || '出版社未知' }}</span>
                  <span>{{ library.selectedResource.borrowable_copies > 0 ? `可借 ${library.selectedResource.borrowable_copies} 册` : '馆内/在线阅览' }}</span>
                </div>
                <button class="drawer-graph-link" type="button" @click="openGraph">在知识图谱中查看关联 →</button>
              </div>
            </div>
            <section class="drawer-section">
              <h3>内容简介</h3>
              <p>{{ library.selectedResource.abstract || '当前馆藏记录暂无摘要，可通过主题词和关联知识继续探索。' }}</p>
            </section>
            <section v-if="item" class="drawer-section evidence-panel">
              <h3>为什么推荐给你</h3>
              <p>{{ item.reason_summary }}</p>
              <div v-if="item.evidence" class="evidence-meters">
                <span v-for="(score, channel) in item.evidence?.channel_scores" :key="channel">
                  <i :style="{ width: `${Math.round(score * 100)}%` }" />
                  <b>{{ channel }}</b><em>{{ Math.round(score * 100) }}%</em>
                </span>
              </div>
              <div v-else class="evidence-empty"><b>历史结果未保存增强通道分数</b><span>上方解释与置信度来自已持久化公开结果；页面不会补造缺失证据。</span></div>
            </section>
            <section class="drawer-section">
              <h3>主题与馆藏信息</h3>
              <div class="topic-cloud">
                <span v-for="tag in [...library.selectedResource.keywords, ...library.selectedResource.tags].slice(0, 12)" :key="tag">{{ tag }}</span>
              </div>
              <dl class="book-facts">
                <div><dt>ISBN</dt><dd>{{ library.selectedResource.isbn || '—' }}</dd></div>
                <div><dt>索书号</dt><dd>{{ library.selectedResource.call_number || '—' }}</dd></div>
                <div><dt>馆藏位置</dt><dd>{{ library.selectedResource.location || '馆藏位置待确认' }}</dd></div>
                <div><dt>难度</dt><dd>{{ library.selectedResource.difficulty_level ? `${library.selectedResource.difficulty_level} / 4` : '未标注' }}</dd></div>
                <div><dt>资源状态</dt><dd>{{ library.selectedResource.availability_status }}</dd></div>
                <div><dt>资源类型</dt><dd>{{ library.selectedResource.resource_type }}</dd></div>
              </dl>
            </section>
            <section class="drawer-section feedback-block">
              <div class="section-title-row"><h3>调整推荐</h3><span>{{ feedbackModeLabel }}</span></div>
              <div class="feedback-actions">
                <button type="button" @click="feedback('FAVORITE')">♡ 喜欢</button>
                <button type="button" @click="feedback('BORROW')">＋ 借阅意向</button>
                <button type="button" @click="feedback('NOT_INTERESTED')">－ 不感兴趣</button>
              </div>
              <p v-if="interaction.localFeedback.length" class="feedback-note">{{ interaction.localFeedback.join(' · ') }}（会话重置后清空）</p>
              <p v-if="interaction.state === 'sending'" class="feedback-note">{{ feedbackProgressLabel }}</p>
              <p v-if="interaction.state === 'error'" class="feedback-note is-error">反馈暂未写入，请稍后重试。</p>
              <div v-if="feedbackAgent" class="feedback-agent-result">
                <b>{{ feedbackAgent.agent_name }}</b>
                <span>{{ feedbackAgent.action }} · {{ feedbackAgent.reason_code }}</span>
                <small>画像版本 {{ interaction.receipt?.profile_version_before ?? '—' }} → {{ interaction.receipt?.profile_version_after ?? '—' }}</small>
              </div>
              <div v-if="interaction.receipt?.resource_state" class="feedback-resource-state"><b>资源抑制状态</b><span>{{ interaction.receipt.resource_state.state_type }}</span><small v-if="interaction.receipt.resource_state.suppress_until">有效至 {{ new Date(interaction.receipt.resource_state.suppress_until).toLocaleString('zh-CN') }}</small></div>
            </section>
          </template>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>
