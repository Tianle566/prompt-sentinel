<script setup>
defineProps({
  name: { type: String, default: 'shield' },
  size: { type: [Number, String], default: 20 },
})
const paths = {
  shield: 'M12 3 20 6v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z M8.5 12l2.5 2.5 4.5-5',
  dashboard: 'M3 3h7v7H3z M14 3h7v10h-7z M3 14h7v7H3z M14 17h7v4h-7z',
  chat: 'M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2V11.5A8.5 8.5 0 0 1 10.5 3h2a8.5 8.5 0 0 1 8.5 8.5Z M7 9h9 M7 13h6',
  attack:
    'M12 3v4 M12 17v4 M3 12h4 M17 12h4 M8 8l8 8 M16 8l-8 8 M19 5l-2 2 M5 19l2-2 M5 5l2 2 M19 19l-2-2',
  document:
    'M14 2H5a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9l-7-7Z M14 2v7h7 M7 13h10 M7 17h7',
  logs: 'M8 5h12 M8 12h12 M8 19h12 M3 5h.01 M3 12h.01 M3 19h.01',
  settings:
    'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2',
  chart: 'M4 3v18h17 M8 16v-5 M13 16V6 M18 16V9',
  arrow: 'M4 12h16 M14 6l6 6-6 6',
  refresh: 'M20 7V3l-4 4 M20 7a8 8 0 1 0 0 10',
  chevron: 'm9 5 7 7-7 7',
  chevrondown: 'm6 9 6 6 6-6',
  close: 'm6 6 12 12 M6 18 18 6',
  copy: 'M9 9h12v12H9z M15 9V3H3v12h6',
  arrows: 'M3 8h18 M7 4 3 8l4 4 M21 16H3 M17 12l4 4-4 4',
  check: 'm5 12 4 4L19 6',
  warning: 'm12 3 10 18H2L12 3Z M12 9v5 M12 17h.01',
  clock: 'M12 3a9 9 0 1 0 .01 0Z M12 7v5l3 2',
  user: 'M12 3a4 4 0 1 0 .01 0Z M4 21v-3a8 8 0 0 1 16 0v3',
  logout: 'M9 4H4v16h5 M13 12h9 M18 8l4 4-4 4',
  send: 'm22 2-7 20-4-9-9-4 20-7Z M22 2 11 13',
  lock: 'M5 10h14v11H5z M8 10V6a4 4 0 0 1 8 0v4 M12 14v3',
  menu: 'M3 6h18 M3 12h18 M3 18h18',
  upload: 'M12 16V3 M7 8l5-5 5 5 M3 16v5h18v-5',
  download: 'M12 3v13 M7 11l5 5 5-5 M3 17v4h18v-4',
  empty: 'M3 8l4-5h10l4 5v12H3V8Z M3 10h5l2 3h4l2-3h5',
  info: 'M12 3a9 9 0 1 0 .01 0Z M12 11v6 M12 7h.01',
  bolt: 'm13 2-9 12h7l-1 8 10-12h-7l1-8Z',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z M12 9a3 3 0 1 0 .01 0Z',
}
</script>
<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path :d="paths[name] || paths.shield" />
  </svg>
</template>
