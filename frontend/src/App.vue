<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from "vue";
import { useRoute } from "vue-router";
import ResourceDrawer from "./components/ResourceDrawer.vue";
import SystemStatus from "./components/SystemStatus.vue";
import { useLibraryStore } from "./stores/library";
import { useSessionStore } from "./stores/session";
import { useSystemStore } from "./stores/system";

const route = useRoute();
const session = useSessionStore();
const system = useSystemStore();
const library = useLibraryStore();
const nav = [
  ["/", "⌂", "探索首页"], ["/recommend", "✦", "智能推荐"], ["/graph", "⌘", "知识图谱"], ["/path", "↝", "阅读路径"], ["/insights", "◫", "馆藏洞察"],
] as const;
const pageTitle = computed(() => nav.find(([path]) => path === route.path)?.[2] ?? "系统状态");

onMounted(() => { session.start(); void Promise.all([system.refresh(), library.loadOverview()]); });
onBeforeUnmount(session.stop);
</script>

<template>
  <div class="kiosk-shell">
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
          <div class="mode-switch" role="group" aria-label="身份模式">
            <button type="button" :class="{ active: session.mode === 'guest' }" @click="session.setMode('guest')">访客模式</button>
            <button type="button" :class="{ active: session.mode === 'demo' }" @click="session.setMode('demo')">演示画像</button>
          </div>
          <button class="system-dot" type="button" :title="system.healthy ? '系统已连接' : '系统状态需检查'" @click="system.drawerOpen = true"><i :class="{ up: system.healthy }" />{{ system.healthy ? '馆藏在线' : '状态检查' }}</button>
        </div>
      </header>
      <main class="kiosk-content"><RouterView v-slot="{ Component }"><Transition name="page" mode="out-in"><component :is="Component" /></Transition></RouterView></main>
    </div>

    <ResourceDrawer />
    <Transition name="drawer">
      <div v-if="system.drawerOpen" class="drawer-layer" role="presentation" @click.self="system.drawerOpen = false">
        <aside class="system-drawer" role="dialog" aria-modal="true" aria-label="系统运行状态">
          <button class="icon-button drawer-close" type="button" aria-label="关闭" @click="system.drawerOpen = false">×</button>
          <span class="eyebrow">SYSTEM READINESS</span><h2>系统状态</h2>
          <p>技术信息仅在此处展示，不占用读者主界面。</p>
          <SystemStatus :liveness="system.liveness" :readiness="system.readiness" />
          <RouterLink class="secondary-action" to="/system" @click="system.drawerOpen = false">打开完整兼容页</RouterLink>
        </aside>
      </div>
    </Transition>
    <Transition name="countdown"><div v-if="session.showCountdown" class="session-countdown" role="status"><b>{{ session.secondsRemaining }}</b><span>秒后重置访客会话</span><button type="button" @click="session.touch">继续探索</button></div></Transition>
  </div>
</template>
