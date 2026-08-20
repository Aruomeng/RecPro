<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import type { InteractionDirective, WorkspaceAgent, WorkspaceEvent } from "../domain/agentWorkspace";
import { useAgentWorkspaceStore } from "../stores/agentWorkspace";
import { useRecommendationStore } from "../stores/recommendation";

const workspace = useAgentWorkspaceStore();
const recommendation = useRecommendationStore();
const router = useRouter();

const stateText: Record<string, string> = {
  IDLE: "空闲", OBSERVING: "观察中", PLANNING: "规划中", WORKING: "工作中", WAITING_USER: "等待选择",
  COMPLETED: "已完成", DEGRADED: "已降级", FAILED: "失败",
};
const eventText: Record<string, string> = {
  WORKSPACE_CREATED: "协作空间已建立", OBSERVATION_ACCEPTED: "接收新情境", AGENT_STARTED: "开始执行",
  AGENT_COMPLETED: "完成局部任务", RECOMMENDATION_EVENT: "推荐链事件", RECOMMENDATION_COMPLETED: "推荐任务结束",
  DIRECTIVE_PROPOSED: "提出交互建议", DIRECTIVE_ACTIONED: "用户处理建议",
};
const selected = computed(() => workspace.selectedAgent);

function shortName(agent: WorkspaceAgent): string {
  return agent.name.replace("Agent", "").replace("Recommendation", "Policy").slice(0, 2).toUpperCase();
}
function time(event: WorkspaceEvent): string {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(event.occurred_at));
}
async function accept(directive: InteractionDirective): Promise<void> {
  await workspace.action(directive, "ACCEPT");
  const action = directive.payload.action;
  const query = directive.payload.query;
  if (typeof query === "string" && query.trim()) recommendation.query = query;
  if (action === "OPEN_RECOMMEND" || action === "RECOMMEND_AGAIN") await router.push("/recommend");
  if (action === "OPEN_GRAPH") await router.push("/graph");
}
</script>

<template>
  <aside class="agent-rail" :class="{ 'is-expanded': workspace.expanded }" aria-label="全局多智能体工作栏">
    <div class="agent-rail__collapsed">
      <button class="agent-rail__toggle" type="button" :aria-expanded="workspace.expanded" aria-label="展开智能体工作栏" @click="workspace.expanded = !workspace.expanded">
        <span class="orchestrator-symbol">AI</span><i :class="workspace.state" />
      </button>
      <div class="rail-agent-list" aria-label="八个智能体状态">
        <button v-for="agent in workspace.agents" :key="agent.name" type="button" :title="`${agent.role}：${stateText[agent.state]}`" :class="[`state-${agent.state.toLowerCase()}`, { active: workspace.selectedAgentName === agent.name }]" @click="workspace.selectAgent(agent.name)">
          <span>{{ shortName(agent) }}</span><i />
        </button>
      </div>
      <div class="rail-summary"><b>{{ workspace.activeCount }}</b><span>活跃</span><em v-if="workspace.suggestions.length">{{ workspace.suggestions.length }}</em></div>
    </div>

    <Transition name="agent-panel">
      <section v-if="workspace.expanded" class="agent-workspace-panel">
        <header class="agent-panel__header">
          <div><span>AGENT WORKSPACE</span><h2>全局协作现场</h2></div>
          <button type="button" aria-label="收起智能体工作栏" @click="workspace.expanded = false">→</button>
        </header>
        <div class="workspace-status">
          <span><i :class="workspace.state" />{{ workspace.state === 'online' ? '事件流已连接' : workspace.state === 'connecting' ? '正在连接' : '协作流降级' }}</span>
          <b>{{ workspace.activeCount }} 位工作中</b><em v-if="workspace.degradedCount">{{ workspace.degradedCount }} 位需关注</em>
        </div>

        <section class="agent-panel-section agent-roster">
          <div class="section-caption"><b>协作角色</b><span>8 个真实业务 Agent</span></div>
          <button v-for="agent in workspace.agents" :key="agent.name" type="button" :class="{ active: workspace.selectedAgentName === agent.name }" @click="workspace.selectedAgentName = agent.name">
            <i :class="`state-${agent.state.toLowerCase()}`" /><span><b>{{ agent.role }}</b><small>{{ agent.name }}</small></span><em>{{ stateText[agent.state] }}</em>
          </button>
        </section>

        <section v-if="selected" class="agent-panel-section agent-detail">
          <div class="section-caption"><b>当前 Agent 详情</b><span>{{ stateText[selected.state] }}</span></div>
          <h3>{{ selected.role }}</h3><p>{{ selected.goal }}</p>
          <dl>
            <div><dt>当前/最近动作</dt><dd>{{ selected.last_action || '等待新的真实事件' }}</dd></div>
            <div><dt>协作目标</dt><dd>{{ selected.target || '—' }}</dd></div>
            <div><dt>决策原因</dt><dd>{{ selected.reason_code || '尚未产生决策' }}</dd></div>
            <div><dt>置信度</dt><dd>{{ selected.confidence === null ? '—' : `${Math.round(selected.confidence * 100)}%` }}</dd></div>
            <div><dt>耗时</dt><dd>{{ selected.duration_ms === null ? '—' : `${selected.duration_ms} ms` }}</dd></div>
          </dl>
          <div class="agent-tools"><span v-for="tool in selected.tools" :key="tool">{{ tool }}</span></div>
          <div v-if="selected.evidence_refs.length" class="agent-evidence"><b>证据来源</b><span v-for="ref in selected.evidence_refs" :key="ref">{{ ref }}</span></div>
        </section>

        <section v-if="workspace.suggestions.length" class="agent-panel-section suggestion-list">
          <div class="section-caption"><b>非打断式建议</b><span>需要你确认</span></div>
          <article v-for="directive in workspace.suggestions" :key="directive.directive_id">
            <span>{{ directive.type }}</span><h3>{{ String(directive.payload.label || '调整当前探索策略') }}</h3>
            <p>{{ directive.reason_codes.join(' · ') }} · 置信度 {{ Math.round(directive.confidence * 100) }}%</p>
            <div><button type="button" @click="accept(directive)">采用建议</button><button type="button" @click="workspace.action(directive, 'DISMISS')">暂不采用</button></div>
          </article>
        </section>

        <section class="agent-panel-section data-sources">
          <div class="section-caption"><b>情境数据源</b><span>5 分钟有效期</span></div>
          <div><span v-for="source in workspace.sources" :key="source.source_id" :class="source.kind.toLowerCase()"><i />{{ source.label }}<small>{{ source.kind === 'EXTERNAL_DEMO' ? '演示外部情境' : '内部数据' }}</small></span></div>
        </section>

        <section class="agent-panel-section agent-timeline">
          <div class="section-caption"><b>真实事件时间线</b><span>最近 {{ workspace.events.length }} 条</span></div>
          <ol>
            <li v-for="event in [...workspace.events].reverse().slice(0, 24)" :key="event.sequence">
              <time>{{ time(event) }}</time><i /><span><b>{{ event.agent_name || eventText[event.event_type] || event.event_type }}</b><small>{{ event.reason_code || event.action || event.observation_type || '已记录公开协作事实' }}</small></span>
            </li>
          </ol>
        </section>
        <p v-if="workspace.error" class="agent-panel-error">{{ workspace.error }}</p>
      </section>
    </Transition>
  </aside>
</template>
