<script setup lang="ts">
import type { Tone } from "../presentation/healthPresentation";

defineProps<{
  label: string;
  tone: Tone;
}>();
</script>

<template>
  <span class="status-badge" :class="`status-badge--${tone}`">
    <span class="status-badge__dot" aria-hidden="true"></span>
    {{ label }}
  </span>
</template>
