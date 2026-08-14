<script setup lang="ts">
import SystemStatus from "../components/SystemStatus.vue";
import { useSystemStore } from "../stores/system";
const system = useSystemStore();
</script>
<template>
  <div class="system-view"><header class="view-header"><div><span class="eyebrow">OPERATIONS & COMPATIBILITY</span><h1>系统状态与旧版入口</h1><p>技术验收信息已从读者界面移到这里，旧组件和同步 API 均保留。</p></div><button class="secondary-action" type="button" @click="system.refresh">重新检查</button></header>
    <SystemStatus :liveness="system.liveness" :readiness="system.readiness" />
    <aside class="compatibility-note glass-panel"><h2>兼容边界</h2><p>默认组合根仍然 fail-closed；只有显式研究运行时挂载真实 MySQL、Neo4j、Chroma、DeepSeek、异步推荐与交互管线。此页面只展示状态，不主动写入业务数据库。</p></aside>
  </div>
</template>
