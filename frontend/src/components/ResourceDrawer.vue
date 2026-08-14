<script setup lang="ts">
import { computed, onBeforeUnmount, watch } from "vue";
import type { FeedbackType } from "../domain/interaction";
import { useLibraryStore } from "../stores/library";
import { useInteractionStore } from "../stores/interaction";
import { useRecommendationStore } from "../stores/recommendation";
import { useSessionStore } from "../stores/session";
import BookCover from "./BookCover.vue";

const library = useLibraryStore();
const recommendation = useRecommendationStore();
const session = useSessionStore();
const interaction = useInteractionStore();

const item = computed(() => recommendation.items.find(
  (candidate) => candidate.resource.resource_id === library.selectedResource?.resource_id,
));
const canWrite = computed(() => interaction.canWrite && Boolean(item.value));
const feedbackAgent = computed(() => interaction.receipt?.agent_action);

watch(() => [library.detailOpen, library.selectedResource?.resource_id, session.mode] as const, () => {
  interaction.prepareExposure(library.detailOpen ? item.value : undefined);
}, { immediate: true });

onBeforeUnmount(interaction.clearExposure);

function close(): void { library.detailOpen = false; }

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
              </div>
            </div>
            <section class="drawer-section">
              <h3>内容简介</h3>
              <p>{{ library.selectedResource.abstract || '当前馆藏记录暂无摘要，可通过主题词和关联知识继续探索。' }}</p>
            </section>
            <section v-if="item" class="drawer-section evidence-panel">
              <h3>为什么推荐给你</h3>
              <p>{{ item.reason_summary }}</p>
              <div class="evidence-meters">
                <span v-for="(score, channel) in item.evidence?.channel_scores" :key="channel">
                  <i :style="{ width: `${Math.round(score * 100)}%` }" />
                  <b>{{ channel }}</b><em>{{ Math.round(score * 100) }}%</em>
                </span>
              </div>
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
              </dl>
            </section>
            <section class="drawer-section feedback-block">
              <div class="section-title-row"><h3>调整推荐</h3><span>{{ session.mode === 'guest' ? '仅本次会话' : '演示画像 · 真实反馈' }}</span></div>
              <div class="feedback-actions">
                <button type="button" @click="feedback('FAVORITE')">♡ 喜欢</button>
                <button type="button" @click="feedback('BORROW')">＋ 借阅意向</button>
                <button type="button" @click="feedback('NOT_INTERESTED')">－ 不感兴趣</button>
              </div>
              <p v-if="interaction.localFeedback.length" class="feedback-note">{{ interaction.localFeedback.join(' · ') }}（会话重置后清空）</p>
              <p v-if="interaction.state === 'sending'" class="feedback-note">FeedbackLearningAgent 正在更新演示画像…</p>
              <p v-if="interaction.state === 'error'" class="feedback-note is-error">反馈暂未写入，请稍后重试。</p>
              <div v-if="feedbackAgent" class="feedback-agent-result">
                <b>{{ feedbackAgent.agent_name }}</b>
                <span>{{ feedbackAgent.action }} · {{ feedbackAgent.reason_code }}</span>
                <small>画像版本 {{ interaction.receipt?.profile_version_before ?? '—' }} → {{ interaction.receipt?.profile_version_after ?? '—' }}</small>
              </div>
            </section>
          </template>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>
