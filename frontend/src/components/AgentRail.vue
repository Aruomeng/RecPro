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
  AGENT_COMPLETED: "完成局部任务", AGENT_FAILED: "局部任务失败", AGENT_TOOL_CALL: "调用只读工具",
  RECOMMENDATION_EVENT: "推荐链事件", RECOMMENDATION_COMPLETED: "推荐任务结束",
  RECOMMENDATION_HISTORY_REPLAY: "历史真实动作回放", OBSERVATION_COMPLETED: "情境处理完成",
  OBSERVATION_FAILED: "情境处理失败", OBSERVATION_SUPERSEDED: "情境已由新版本接替",
  DIRECTIVE_PROPOSED: "提出交互建议", DIRECTIVE_ACTIONED: "用户处理建议", DIRECTIVE_EXPIRED: "交互建议已过期",
  BACKGROUND_PLAN_SKIPPED: "后台规划按预算跳过",
};
const selected = computed(() => workspace.selectedAgent);
const stateDistribution = computed(() => Object.entries(workspace.agents.reduce<Record<string, number>>((acc, agent) => { acc[agent.state] = (acc[agent.state] ?? 0) + 1; return acc; }, {})).sort((a,b) => b[1]-a[1]));
const handoffs = computed(() => workspace.events.filter((event) => event.agent_name && event.target).slice(-6).reverse());
const currentDirective = computed(() => [...workspace.directives].reverse().find((directive) => ["AUTO_APPLIED","ACCEPTED","PROPOSED"].includes(directive.status)));
const replayCount = computed(() => workspace.events.filter((event) => event.replayed).length);

function shortName(agent: WorkspaceAgent): string {
  return agent.name.replace("Agent", "").replace("Recommendation", "Policy").slice(0, 2).toUpperCase();
}
function time(event: WorkspaceEvent): string {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(event.occurred_at));
}
async function accept(directive: InteractionDirective): Promise<void> {
  try {
    await workspace.action(directive, "ACCEPT");
  } catch {
    return;
  }
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
          <small class="workspace-context">上下文 v{{ workspace.contextVersion }} · {{ workspace.currentObservation?.event_type || '等待新观察' }}</small>
        </div>
        <section class="workspace-overview-grid">
          <div><span>状态分布</span><p><b v-for="([state,count]) in stateDistribution" :key="state">{{ stateText[state] || state }} {{ count }}</b></p></div>
          <div><span>历史回放</span><strong>{{ replayCount }} 条</strong><small>明确区别于实时 dispatch</small></div>
        </section>
        <section v-if="currentDirective" class="current-policy-card">
          <span>当前策略 · {{ currentDirective.status }}</span><h3>{{ currentDirective.type }}</h3><p>{{ currentDirective.reason_codes.join(' · ') }}</p><small>置信度 {{ Math.round(currentDirective.confidence * 100) }}% · 证据 {{ currentDirective.evidence_refs.join(' / ') || '公开会话上下文' }}</small>
        </section>

        <section v-if="workspace.backgroundPlanning" class="agent-panel-section background-planning-card">
          <div class="section-caption"><b>低频后台规划</b><span>{{ workspace.backgroundPlanning.status }}</span></div>
          <p>{{ workspace.backgroundPlanning.reason_code }} · v{{ workspace.backgroundPlanning.context_version }}</p>
          <small>Provider {{ workspace.backgroundPlanning.provider }} · 请求 {{ workspace.backgroundPlanning.model_requests }} 次 · 指令 {{ workspace.backgroundPlanning.directive_count }} 条</small>
          <small v-if="workspace.backgroundPlanning.budget">会话 {{ workspace.backgroundPlanning.budget.session_calls }}/{{ workspace.backgroundPlanning.budget.session_limit }} · 设备今日 {{ workspace.backgroundPlanning.budget.device_calls_today }}/{{ workspace.backgroundPlanning.budget.device_limit_today }}</small>
        </section>

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

        <section v-if="handoffs.length" class="agent-panel-section handoff-list">
          <div class="section-caption"><b>最近任务转交</b><span>真实事件目标</span></div>
          <ol><li v-for="event in handoffs" :key="event.sequence"><span>{{ event.agent_name }}</span><i>→</i><b>{{ event.target }}</b><small>{{ event.action || event.reason_code }}</small></li></ol>
        </section>

        <section class="agent-panel-section data-sources">
          <div class="section-caption"><b>情境数据源</b><span>5 分钟有效期</span></div>
          <div><span v-for="source in workspace.sources" :key="source.source_id" :class="[source.kind.toLowerCase(), `status-${source.status.toLowerCase()}`]"><i /><b>{{ source.label }}</b><em>{{ source.status }}</em><small>{{ source.kind === 'EXTERNAL_DEMO' ? '演示外部情境' : '内部数据' }} · {{ new Date(source.observed_at).toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'}) }}</small></span></div>
        </section>

        <section class="agent-panel-section agent-timeline">
          <div class="section-caption"><b>真实事件时间线</b><span>最近 {{ workspace.events.length }} 条</span></div>
          <ol>
            <li v-for="event in [...workspace.events].reverse().slice(0, 24)" :key="event.sequence">
              <time>{{ time(event) }}</time><i :class="{ replayed: event.replayed, directive: event.event_type.startsWith('DIRECTIVE'), readiness: event.observation_type === 'READINESS_CHANGED' }" /><span><b>{{ event.agent_name || eventText[event.event_type] || event.event_type }}</b><em>{{ event.replayed ? '历史真实动作回放' : event.event_type.startsWith('DIRECTIVE') ? '交互策略' : event.observation_type === 'READINESS_CHANGED' ? '运行状态' : '实时/会话事件' }}</em><small>{{ event.reason_code || event.action || event.observation_type || '已记录公开协作事实' }}</small></span>
            </li>
          </ol>
        </section>
        <p v-if="workspace.error" class="agent-panel-error">{{ workspace.error }}</p>
      </section>
    </Transition>
  </aside>
</template>
