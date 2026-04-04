import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Production build is served at https://<user>.github.io/Systemize/
export default defineConfig(({ mode }) => ({
  base: mode === 'production' ? '/Systemize/' : '/',
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
}))
