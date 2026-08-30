<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from "vue";
import { useRoute } from "vue-router";
import ResourceDrawer from "./components/ResourceDrawer.vue";
import SystemStatus from "./components/SystemStatus.vue";
import AgentRail from "./components/AgentRail.vue";
import LoginDialog from "./components/LoginDialog.vue";
import { useAgentWorkspaceStore } from "./stores/agentWorkspace";
import { useLibraryStore } from "./stores/library";
import { useSessionStore } from "./stores/session";
import { useSystemStore } from "./stores/system";
import { useAuthStore } from "./stores/auth";

const route = useRoute();
const session = useSessionStore();
const system = useSystemStore();
const library = useLibraryStore();
const agentWorkspace = useAgentWorkspaceStore();
const auth = useAuthStore();
const baseNav = [
  ["/", "⌂", "探索首页"], ["/recommend", "✦", "智能推荐"], ["/graph", "⌘", "知识图谱"], ["/path", "↝", "阅读路径"], ["/insights", "◫", "馆藏洞察"],
] as const;
const nav = computed(() => auth.permissions.includes("catalog.knowledge.review")
  ? [...baseNav, ["/knowledge-reviews", "✓", "知识审核"] as const]
  : [...baseNav]);
const pageTitle = computed(() => nav.value.find(([path]) => path === route.path)?.[2] ?? "系统状态");

onMounted(async () => {
  session.start();
  await auth.restore();
  await Promise.all([system.refresh(), library.loadOverview(), agentWorkspace.initialize()]);
  await agentWorkspace.observe("ROUTE_CHANGED", { route: route.path, page_title: pageTitle.value });
});
watch(() => route.path, (path) => { void agentWorkspace.observe("ROUTE_CHANGED", { route: path, page_title: pageTitle.value }); });
watch(() => system.readiness, (readiness) => {
  if (readiness.phase !== "success") return;
  const degraded = Object.entries(readiness.value.components).filter(([, component]) => component.status !== "UP").map(([name]) => name);
  void agentWorkspace.observe("READINESS_CHANGED", { degraded, can_recommend: readiness.value.can_recommend });
});
watch(() => [auth.authenticated, auth.permissions.includes("research.audit.read")] as const, ([authenticated, canRead]) => {
  if (!authenticated || !canRead) system.clearRuntimeDiagnostics();
  else void system.refreshRuntime();
});
watch(() => session.inactivityEpoch, () => { if (auth.authenticated) void auth.logout(); });
onBeforeUnmount(() => { session.stop(); agentWorkspace.stop(); });
</script>

<template>
  <div class="kiosk-shell" :class="{ 'agent-panel-open': agentWorkspace.expanded }">
    <aside class="nav-rail" aria-label="主导航">
      <RouterLink class="brand-mark" to="/" aria-label="LibraMAS 首页"><span>LM</span><i /></RouterLink>
      <nav>
        <RouterLink v-for="([path, icon, label]) in nav" :key="path" :to="path" :aria-label="label"><b>{{ icon }}</b><span>{{ label }}</span></RouterLink>
      </nav>
      <button class="rail-status" type="button" aria-label="打开系统状态" @click="system.drawerOpen = true"><i :class="{ up: system.healthy }" /><span>状态</span></button>
    </aside>

    <div class="kiosk-frame">
      <header class="top-bar">
        <div class="breadcrumb"><span>智慧图书馆</span><i>/</i><b>{{ pageTitle }}</b></div>
        <div class="top-actions">
          <span class="session-label">会话 {{ session.sessionId.slice(0, 8).toUpperCase() }}</span>
          <div v-if="auth.authenticated && auth.account" class="account-chip">
            <span><b>{{ auth.account.display_name }}</b><small>{{ auth.account.roles.join(' · ') }}</small><small>{{ auth.canUsePersonalization ? '个性化已授权' : '个性化未授权' }}</small></span>
            <button type="button" @click="auth.onboardingOpen = true">画像与授权</button>
            <button type="button" @click="auth.logout">安全退出</button>
          </div>
          <button v-else class="login-entry" type="button" @click="auth.dialogOpen = true"><span>访客探索</span><b>登录</b></button>
          <button class="system-dot" type="button" :title="system.healthy ? '系统已连接' : '系统状态需检查'" @click="system.drawerOpen = true"><i :class="{ up: system.healthy }" />{{ system.healthy ? '馆藏在线' : '状态检查' }}</button>
        </div>
      </header>
      <main class="kiosk-content"><RouterView v-slot="{ Component }"><Transition name="page" mode="out-in"><component :is="Component" /></Transition></RouterView></main>
    </div>
    <AgentRail />

    <ResourceDrawer />
    <Transition name="drawer">
      <div v-if="system.drawerOpen" class="drawer-layer" role="presentation" @click.self="system.drawerOpen = false">
        <aside class="system-drawer" role="dialog" aria-modal="true" aria-label="系统运行状态">
          <button class="icon-button drawer-close" type="button" aria-label="关闭" @click="system.drawerOpen = false">×</button>
          <span class="eyebrow">SYSTEM READINESS</span><h2>系统状态</h2>
          <p>技术信息仅在此处展示，不占用读者主界面。</p>
          <SystemStatus
            :liveness="system.liveness"
            :readiness="system.readiness"
            :runtime="system.runtimeDiagnostics"
            :runtime-access="system.canReadRuntimeDiagnostics"
            @refresh-runtime="system.refreshRuntime"
          />
          <button v-if="auth.researchDemoEnabled" class="secondary-action" type="button" @click="auth.useResearchDemo(); system.drawerOpen = false">进入研究演示画像（1001）</button>
          <RouterLink class="secondary-action" to="/system" @click="system.drawerOpen = false">打开完整兼容页</RouterLink>
        </aside>
      </div>
    </Transition>
    <LoginDialog />
    <Transition name="countdown"><div v-if="session.showCountdown" class="session-countdown" role="status"><b>{{ session.secondsRemaining }}</b><span>秒后{{ auth.authenticated ? '安全退出' : '重置访客会话' }}</span><button type="button" @click="session.touch">继续探索</button></div></Transition>
  </div>
</template>
