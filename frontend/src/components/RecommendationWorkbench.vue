<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";

import type {
  RecommendationClient,
  RecommendationExecution,
  RecommendationItem,
  RecommendationOutputType,
  ResourceType,
} from "../domain/recommendation";
import type { InteractionClient } from "../domain/interaction";
import {
  createRequestId,
  isRecommendationFailure,
  isUuid,
} from "../domain/recommendation";
import InteractionPanel from "./InteractionPanel.vue";

const props = withDefaults(defineProps<{
  pipelineEnabled?: boolean;
  client: RecommendationClient;
  interactionEnabled?: boolean;
  interactionClient?: InteractionClient;
}>(), {
  pipelineEnabled: false,
  interactionEnabled: false,
});

const query = ref("多智能体系统与智慧图书馆");
const selectedTypes = ref<ResourceType[]>(["BOOK"]);
const selectedOutputType = ref<RecommendationOutputType>("TOPIC_RESOURCES");
const limit = ref(8);
const phase = ref<"idle" | "demo" | "loading" | "success" | "clarification" | "error">("idle");
const result = ref<RecommendationExecution | null>(null);
const errorMessage = ref("");
const notice = ref("");
const selectedAnswers = ref<Record<string, string>>({});
const configuredSessionId = (import.meta.env.VITE_G4_DEMO_SESSION_ID ?? "").trim();
const configuredRequestId = (import.meta.env.VITE_G4_DEMO_REQUEST_ID ?? "").trim();
const sessionId = isUuid(configuredSessionId) ? configuredSessionId : createRequestId();
let configuredRequestIdConsumed = false;
let activeController: AbortController | undefined;
onBeforeUnmount(() => activeController?.abort());

const client = computed(() => props.client);
const items = computed<RecommendationItem[]>(() => result.value?.items ?? []);
const isBusy = computed(() => phase.value === "loading");
const modeLabel = computed(() => {
  if (phase.value === "demo") return "本地演示";
  if (phase.value === "success" || phase.value === "clarification") return "真实接口";
  return props.pipelineEnabled ? "真实接口已就绪" : "接口待启用";
});

const demoItems: RecommendationItem[] = [
  {
    item_id: 9001,
    rank_no: 1,
    reason_summary: "主题与“多智能体、智慧图书馆”高度匹配，适合作为研究入口。",
    evidence_confidence: 0.91,
    unavailable_now: false,
    resource: {
      resource_id: 6452,
      resource_type: "BOOK",
      title: "多智能体系统：协作、博弈与应用",
      authors: ["研究型演示数据"],
      publication_year: 2024,
      availability_status: "AVAILABLE_BORROW",
    },
  },
  {
    item_id: 9002,
    rank_no: 2,
    reason_summary: "覆盖智慧图书馆的知识组织与服务流程，可用于搭建领域背景。",
    evidence_confidence: 0.87,
    unavailable_now: false,
    resource: {
      resource_id: 6322,
      resource_type: "BOOK",
      title: "智慧图书馆建设与智能服务",
      authors: ["研究型演示数据"],
      publication_year: 2023,
      availability_status: "AVAILABLE_ONLINE",
    },
  },
  {
    item_id: 9003,
    rank_no: 3,
    reason_summary: "提供知识图谱与推荐系统的连接视角，便于设计可解释召回。",
    evidence_confidence: 0.84,
    unavailable_now: false,
    resource: {
      resource_id: 6850,
      resource_type: "BOOK",
      title: "知识图谱驱动的推荐方法",
      authors: ["研究型演示数据"],
      publication_year: 2022,
      availability_status: "REFERENCE_ONLY",
    },
  },
];

function nextRequestId(): string {
  if (!configuredRequestIdConsumed && isUuid(configuredRequestId)) {
    configuredRequestIdConsumed = true;
    return configuredRequestId;
  }
  return createRequestId();
}

function createDemoExecution(): RecommendationExecution {
  return {
    task_id: "00000000-0000-4000-8000-000000000001",
    trace_id: "00000000-0000-4000-8000-000000000002",
    status: "COMPLETED",
    context_version: 1,
    decision: {
      output_type: "TOPIC_RESOURCES",
      delivery_strategy: "DIRECT",
      explanation_level: "EVIDENCE",
      adaptation_state: "NORMAL",
      decision_reason_codes: ["DEMO_ONLY"],
      decision_reason: "这是明确标注的本地演示，不会访问后端或写入数据库。",
      policy_version: "demo-ui-v1",
    },
    items: demoItems,
    warnings: ["DEMO_DATA_NOT_RECOMMENDATION"],
    versions: {
      config_bundle: "demo-ui-v1",
      policy: "demo-ui-v1",
      ranking: "demo-ui-v1",
      behavior_formula: "not-applied",
      embedding: "not-connected",
      graph: "not-connected",
      prompt: "not-applied",
      dataset: "local-static-demo",
    },
  };
}

function loadDemo(): void {
  activeController?.abort();
  phase.value = "demo";
  result.value = createDemoExecution();
  errorMessage.value = "";
  notice.value = "已加载本地演示数据：不访问 API，不写入 MySQL、Neo4j 或 Chroma。";
}

function toggleType(type: ResourceType): void {
  if (selectedTypes.value.includes(type)) {
    if (selectedTypes.value.length === 1) return;
    selectedTypes.value = selectedTypes.value.filter((item) => item !== type);
  } else {
    selectedTypes.value = [...selectedTypes.value, type];
  }
}

async function submit(): Promise<void> {
  if (!props.pipelineEnabled) {
    notice.value = "当前默认运行时未启用真实推荐接口；请先通过后端推荐能力 Gate。";
    return;
  }
  const input = query.value.trim();
  if (!input) {
    errorMessage.value = "请输入一个研究主题或问题。";
    phase.value = "error";
    return;
  }
  activeController?.abort();
  const controller = new AbortController();
  activeController = controller;
  phase.value = "loading";
  result.value = null;
  selectedAnswers.value = {};
  errorMessage.value = "";
  notice.value = "正在通过显式推荐 API 请求结果。";
  const requestIdValue = nextRequestId();
  try {
    const response = await client.value.createTask({
      request_id: requestIdValue,
      session_id: sessionId,
      scene: "SEARCH_AFTER",
      input_text: input,
      requested_resource_types: [...selectedTypes.value],
      requested_output_type: selectedOutputType.value,
      limit: limit.value,
    }, { signal: controller.signal });
    if (controller.signal.aborted) return;
    result.value = response;
    phase.value = response.status === "WAITING_CLARIFICATION" ? "clarification" : "success";
    notice.value = response.status === "WAITING_CLARIFICATION"
      ? "请补充一个澄清选项，再继续同一个任务。"
      : "推荐结果已通过接口契约校验。";
  } catch (error) {
    if (controller.signal.aborted) return;
    phase.value = "error";
    errorMessage.value = presentError(error);
    notice.value = "请求未改变前端或后端事实层。";
  } finally {
    if (activeController === controller) activeController = undefined;
  }
}

async function submitClarification(): Promise<void> {
  if (!result.value?.task_id || !props.pipelineEnabled) return;
  const questions = result.value.questions ?? [];
  const missing = questions.some((question) => question.required && !selectedAnswers.value[question.slot]);
  if (missing) {
    errorMessage.value = "请先回答所有必答澄清问题。";
    return;
  }
  activeController?.abort();
  const controller = new AbortController();
  activeController = controller;
  phase.value = "loading";
  errorMessage.value = "";
  try {
    const response = await client.value.submitClarification(
      result.value.task_id,
      result.value.context_version,
      selectedAnswers.value,
      createRequestId(),
      { signal: controller.signal },
    );
    if (controller.signal.aborted) return;
    result.value = response;
    phase.value = response.status === "WAITING_CLARIFICATION" ? "clarification" : "success";
  } catch (error) {
    if (controller.signal.aborted) return;
    phase.value = "error";
    errorMessage.value = presentError(error);
  } finally {
    if (activeController === controller) activeController = undefined;
  }
}

function presentError(error: unknown): string {
  if (isRecommendationFailure(error)) {
    const messages: Record<string, string> = {
      CORE_STORAGE_UNAVAILABLE: "推荐能力当前未就绪。",
      AUTHENTICATION_REQUIRED: "演示身份未通过认证。",
      REQUEST_DEADLINE_EXCEEDED: "推荐请求超时，请稍后重试。",
      RECOMMENDATION_REQUEST_TIMEOUT: "推荐请求未在浏览器等待时间内完成，请稍后重试。",
      INVALID_RECOMMENDATION_RESPONSE: "推荐响应未通过契约校验。",
    };
    return messages[error.code] ?? `推荐请求失败（${error.code}）。`;
  }
  return "推荐请求暂时失败，请稍后重试。";
}

function availabilityLabel(status: RecommendationItem["resource"]["availability_status"]): string {
  return {
    AVAILABLE_BORROW: "可借阅",
    AVAILABLE_ONLINE: "可在线访问",
    REFERENCE_ONLY: "馆藏参考",
    TEMPORARILY_UNAVAILABLE: "暂不可用",
    REMOVED: "已下架",
  }[status];
}

function typeLabel(type: ResourceType): string {
  return type === "BOOK" ? "图书" : "论文";
}
</script>

<template>
  <section class="recommendation-workbench" aria-labelledby="recommendation-title">
    <div class="workbench__header">
      <div>
        <p class="eyebrow">G4 / RECOMMENDATION WORKBENCH</p>
        <h2 id="recommendation-title">把研究问题交给推荐协作链</h2>
        <p class="workbench__lede">
          先用一个主题描述你的研究目标。真实请求只会在 G4 后端能力明确启用后发出；当前可安全查看本地演示路径。
        </p>
      </div>
      <span class="workbench__mode" :class="{ 'workbench__mode--ready': pipelineEnabled }">
        <span aria-hidden="true" />{{ modeLabel }}
      </span>
    </div>

    <form class="recommendation-form" @submit.prevent="submit">
      <label class="field-label" for="research-query">研究主题或问题</label>
      <textarea
        id="research-query"
        v-model="query"
        rows="2"
        maxlength="2000"
        placeholder="例如：我想研究多智能体如何提升智慧图书馆的个性化服务"
        :disabled="isBusy"
      />
      <div class="form-options">
        <fieldset>
          <legend>资源类型</legend>
          <button
            v-for="type in (['BOOK', 'PAPER'] as ResourceType[])"
            :key="type"
            class="choice-chip"
            :class="{ 'choice-chip--selected': selectedTypes.includes(type) }"
            type="button"
            :aria-pressed="selectedTypes.includes(type)"
            :disabled="isBusy"
            @click="toggleType(type)"
          >
            {{ typeLabel(type) }}
          </button>
        </fieldset>
        <label class="limit-field" for="result-limit">结果数
          <select id="result-limit" v-model.number="limit" :disabled="isBusy">
            <option :value="3">3</option>
            <option :value="6">6</option>
            <option :value="8">8</option>
            <option :value="10">10</option>
          </select>
        </label>
        <label class="limit-field" for="output-type">输出形式
          <select id="output-type" v-model="selectedOutputType" :disabled="isBusy">
            <option value="TOPIC_RESOURCES">主题资源</option>
            <option value="PERSONALIZED_FEED">个性化推荐</option>
            <option value="READING_PATH">学习路径</option>
          </select>
        </label>
        <div class="form-actions">
          <button class="primary-action" type="submit" :disabled="isBusy">
            {{ isBusy ? "协作链处理中…" : "请求真实推荐" }}
          </button>
          <button class="secondary-action" type="button" :disabled="isBusy" @click="loadDemo">
            查看本地演示
          </button>
        </div>
      </div>
    </form>

    <p v-if="notice" class="workbench-note" :class="{ 'workbench-note--warning': !pipelineEnabled }" role="status">
      <span aria-hidden="true">{{ pipelineEnabled ? "↗" : "i" }}</span>{{ notice }}
    </p>
    <p v-if="errorMessage" class="workbench-error" role="alert">{{ errorMessage }}</p>

    <div v-if="phase === 'clarification' && result?.questions?.length" class="clarification-panel">
      <div>
        <p class="eyebrow">需要补充上下文</p>
        <h3>让召回范围更准确</h3>
      </div>
      <label v-for="question in result.questions" :key="question.slot" class="clarification-question">
        <span>{{ question.question }}<em v-if="question.required">必答</em></span>
        <select v-model="selectedAnswers[question.slot]">
          <option value="">请选择</option>
          <option v-for="option in question.options" :key="option" :value="option">{{ option }}</option>
        </select>
      </label>
      <button class="primary-action" type="button" :disabled="isBusy" @click="submitClarification">继续同一任务</button>
    </div>

    <div v-if="items.length" class="recommendation-results" aria-live="polite">
      <div class="results-heading">
        <div>
          <p class="eyebrow">结果与证据</p>
          <h3>{{ phase === "demo" ? "本地演示推荐" : "协作链返回的资源" }}</h3>
        </div>
        <div v-if="result" class="results-meta">
          <span>{{ result.status }}</span>
          <span>上下文 v{{ result.context_version }}</span>
          <code>trace {{ result.trace_id.slice(0, 8) }}</code>
        </div>
      </div>
      <div class="recommendation-grid">
        <article v-for="item in items" :key="item.item_id" class="recommendation-card">
          <div class="recommendation-card__rank">{{ String(item.rank_no).padStart(2, "0") }}</div>
          <div class="recommendation-card__body">
            <div class="recommendation-card__meta">
              <span>{{ typeLabel(item.resource.resource_type) }}</span>
              <span>{{ availabilityLabel(item.resource.availability_status) }}</span>
              <span>证据 {{ Math.round(item.evidence_confidence * 100) }}%</span>
            </div>
            <h4>{{ item.resource.title }}</h4>
            <p class="recommendation-card__authors">{{ item.resource.authors.join("、") }}<template v-if="item.resource.publication_year"> · {{ item.resource.publication_year }}</template></p>
            <p class="recommendation-card__reason">{{ item.reason_summary }}</p>
          </div>
        </article>
      </div>
      <p v-if="result?.warnings?.length" class="result-warning">{{ result.warnings.join(" · ") }}</p>
    </div>

    <InteractionPanel
      v-if="interactionClient"
      :items="items"
      :task-id="result?.task_id"
      :session-id="sessionId"
      :enabled="interactionEnabled"
      :client="interactionClient"
    />
  </section>
</template>
