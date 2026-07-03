import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // 프로젝트 루트의 .env (GOOGLE_API_KEY 등과 함께 관리)를 그대로 사용
  envDir: '../',
  server: {
    port: 3000,
    cors: true,
  },
})
