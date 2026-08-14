<script setup lang="ts">
import { computed } from "vue";
import { AGENT_ROLES, useRecommendationStore } from "../stores/recommendation";
const recommendation = useRecommendationStore();
const latestEvents = computed(() => recommendation.events.slice(-8).reverse());
const actionNames: Record<string, string> = {
  RETURN_RESULT: "返回结果", READ_PROFILE: "读取画像", PROBE_RESOURCES: "探测资源", PLAN_RECALL: "规划召回",
  SELECT_CHANNELS: "选择通道", REQUEST_REPLAN: "请求重规划", RENDER_EVIDENCE: "生成解释", PROPOSE_PROFILE_DELTA: "学习反馈",
};
</script>
<template>
  <section class="agent-stage glass-panel" aria-label="多智能体实时协作">
    <header class="panel-heading">
      <div><span class="kicker">LIVE AGENT ORCHESTRATION</span><h2>智能体协作中枢</h2></div>
      <span class="live-pill" :class="{ active: recommendation.phase === 'streaming' }"><i />{{ recommendation.phase === 'streaming' ? '实时运行' : '等待任务' }}</span>
    </header>
    <div class="agent-network">
      <article v-for="([name, role], index) in AGENT_ROLES" :key="name" class="agent-node" :class="`is-${recommendation.agentStates[name]?.state ?? 'waiting'}`">
        <span class="agent-node__index">0{{ index + 1 }}</span>
        <i class="agent-node__pulse" />
        <strong>{{ role }}</strong>
        <small>{{ name.replace('Agent', '') }}</small>
        <em>{{ recommendation.agentStates[name]?.state === 'working' ? '正在处理' : recommendation.agentStates[name]?.state === 'complete' ? '已完成' : recommendation.agentStates[name]?.state === 'degraded' ? '安全降级' : '待命' }}</em>
      </article>
      <div class="orchestrator-core"><i /><strong>ORCHESTRATOR</strong><small>动态编排</small></div>
    </div>
    <div class="agent-feed">
      <div class="agent-feed__heading"><span>实时协作记录</span><b>{{ recommendation.events.length }} 条真实事件</b></div>
      <div v-if="!latestEvents.length" class="agent-feed__empty">提交问题后，这里将展示真实 Agent 事件。</div>
      <div v-for="event in latestEvents" :key="event.sequence" class="agent-feed__row">
        <span>#{{ String(event.sequence).padStart(2, '0') }}</span>
        <strong>{{ event.agent_name?.replace('Agent', '') || event.event_type }}</strong>
        <em :title="event.reason_code || event.status || event.action">{{ actionNames[event.action || ''] || event.reason_code || event.status || '处理中' }}</em>
      </div>
    </div>
  </section>
</template>
