<script setup lang="ts">
import { computed } from "vue";
const props = defineProps<{ title: string; category?: string; rank?: number; size?: "small" | "large" }>();
const palette = ["#245fc1", "#0e7490", "#4338ca", "#1d4e89", "#0f766e", "#475569"];
const color = computed(() => palette[[...props.title].reduce((sum, char) => sum + char.charCodeAt(0), 0) % palette.length]);
</script>
<template>
  <div class="book-cover" :class="size ? `book-cover--${size}` : undefined" :style="{ background: `linear-gradient(145deg, ${color}, #163457)` }">
    <span class="book-cover__mark">LIBRA</span>
    <strong>{{ title }}</strong>
    <small>{{ category || "智慧馆藏" }}</small>
    <b v-if="rank">{{ String(rank).padStart(2, "0") }}</b>
  </div>
</template>
