import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Production build is served at https://<user>.github.io/Systemize/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '')
  const apiTarget = (env.VITE_DEV_PROXY_API || 'http://127.0.0.1:8020').trim()

  return {
    base: mode === 'production' ? '/Systemize/' : '/',
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          // Long compares + progress polls must not hit Node proxy default limits
          timeout: 180000,
          proxyTimeout: 180000,
        },
      },
    },
  }
})
