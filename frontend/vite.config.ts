import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', 'VITE_')
  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      // 개발 시 백엔드로 프록시 — VITE_API_BASE를 비워두면 동일 오리진으로 호출된다
      proxy: {
        '/api': { target: env.VITE_API_BASE || 'http://localhost:8000', changeOrigin: true },
      },
    },
  }
})
