import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发环境把 /api 代理到 FastAPI（uvicorn 默认 8000）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
