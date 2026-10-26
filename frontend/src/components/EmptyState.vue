<script setup>
import Icon from './Icon.vue'
defineProps({
  title: { type: String, default: '暂无数据' },
  text: { type: String, default: '' },
  icon: { type: String, default: 'empty' },
})
</script>
<template>
  <div class="empty-state">
    <div class="empty-icon"><Icon :name="icon" :size="27" /></div>
    <h3>{{ title }}</h3>
    <p v-if="text">{{ text }}</p>
    <slot />
  </div>
</template>
