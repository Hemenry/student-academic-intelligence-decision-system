import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // 用 5174，避免与本机已有的 5173 服务冲突
    port: 5174,
    host: '127.0.0.1',
    proxy: {
      // 前后端分离下的跨域处理：开发环境走 Vite 代理，生产由 Nginx 反向代理
      '/api': {
        target: 'http://127.0.0.1:8008',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500,
  },
})
