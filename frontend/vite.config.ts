import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 端口集中来源见 backend/port_config.py。开发时如需覆盖，设置
// AI_SERIAL_PORT / AI_SERIAL_FRONTEND_PORT 环境变量即可，避免前端代理
// 与后端监听端口各写一份而失配。
const apiPort = process.env.AI_SERIAL_PORT || '8000'
const frontendPort = Number(process.env.AI_SERIAL_FRONTEND_PORT || 5173)
const apiHost = process.env.AI_SERIAL_HOST || 'localhost'
const apiTarget = `http://${apiHost}:${apiPort}`
const wsTarget = `ws://${apiHost}:${apiPort}`

export default defineConfig({
  plugins: [vue()],
  base: './', // 使用相对路径，支持桌面应用模式
  server: {
    port: frontendPort,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/ws': {
        target: wsTarget,
        ws: true,
      },
    },
  },
})
