import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Production build: GitHub Pages at https://mchavez31.github.io/SysBound-Cx/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '')
  const apiTarget = (env.VITE_DEV_PROXY_API || 'http://127.0.0.1:8020').trim()

  return {
    base: mode === 'production' ? '/SysBound-Cx/' : '/',
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          // Long compares + progress polls + tag reports must not hit Node proxy default limits
          timeout: 900000,  // 15 minutes
          proxyTimeout: 900000,  // 15 minutes
        },
      },
    },
  }
})
