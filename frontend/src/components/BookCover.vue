<script setup lang="ts">
import { computed } from "vue";
const props = defineProps<{ title: string; category?: string; rank?: number; size?: "small" | "large" }>();
const palette = ["#164d3a", "#7b4d2a", "#2f526d", "#69517a", "#8b6a22", "#315d59"];
const color = computed(() => palette[[...props.title].reduce((sum, char) => sum + char.charCodeAt(0), 0) % palette.length]);
</script>
<template>
  <div class="book-cover" :class="size ? `book-cover--${size}` : undefined" :style="{ background: `linear-gradient(145deg, ${color}, #102a24)` }">
    <span class="book-cover__mark">LIBRA</span>
    <strong>{{ title }}</strong>
    <small>{{ category || "智慧馆藏" }}</small>
    <b v-if="rank">{{ String(rank).padStart(2, "0") }}</b>
  </div>
</template>
