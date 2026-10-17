import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000', '/health': 'http://127.0.0.1:8000', '/docs': 'http://127.0.0.1:8000' } },
  // Цели сборки: Safari/iOS 14+, Firefox 78+, Chromium 87+ (Яндекс Браузер, Edge, Chrome)
  build: { outDir: 'dist', assetsDir: 'assets', chunkSizeWarningLimit: 900, target: ['es2020', 'safari14', 'ios14', 'firefox78', 'chrome87', 'edge88'], cssTarget: ['safari14', 'firefox78', 'chrome87'] },
})
