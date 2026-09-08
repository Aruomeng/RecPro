<script setup lang="ts">
// Presentation-only: shared outline geometry, no application state or events.
defineProps<{ name: string }>();
const paths: Record<string, string> = {
  '/': 'M3 10 12 3l9 7M5 9v12h5v-7h4v7h5V9',
  '/recommend': 'M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-2H4ZM13 7a3 3 0 0 1 3-3h4v15h-3a4 4 0 0 0-4 2',
  '/graph': 'M10 5h4v4h-4ZM3 16h4v4H3ZM17 16h4v4h-4ZM12 9v3M5 16v-4h14v4',
  '/path': 'M5 5h10a4 4 0 0 1 0 8H9a4 4 0 0 0 0 8h10M3 3h4v4H3M17 19l2 2-2 2',
  '/insights': 'M4 3v17h17M8 15v-4M13 15V7M18 15V4',
  '/knowledge-reviews': 'M5 3h14v18H5ZM8 9l2 2 5-5M8 15h8',
  search: 'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14ZM15 15l6 6',
  close: 'M6 6l12 12M18 6 6 18',
  arrow: 'M4 12h16M14 6l6 6-6 6',
  external: 'M7 17 17 7M9 7h8v8M5 5h6M5 5v14h14v-6',
  handoff: 'M4 8h12M12 4l4 4-4 4M20 16H8m4-4-4 4 4 4',
  book: 'M4 5.5A2.5 2.5 0 0 1 6.5 3H11a3 3 0 0 1 3 3v15a4 4 0 0 0-4-2H4ZM14 6a3 3 0 0 1 3-3h3v16h-2a4 4 0 0 0-4 2',
  heart: 'M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8Z',
  plus: 'M12 5v14M5 12h14',
  minus: 'M5 12h14',
};
</script>
<template>
  <svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path :d="paths[name] || paths['/recommend']" /></svg>
</template>
