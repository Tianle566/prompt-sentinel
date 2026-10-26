import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.SENTINEL_BACKEND_URL || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (/node_modules\/(echarts|zrender)\//.test(id)) return 'charts'
          if (/node_modules\/(element-plus|@element-plus)\//.test(id)) return 'ui'
          if (/node_modules\/(vue|@vue|vue-router|axios)\//.test(id)) return 'framework'
        },
      },
    },
  },
})
