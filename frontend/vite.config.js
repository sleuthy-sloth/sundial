import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Build straight into the backend's static dir: one process serves both.
  build: { outDir: '../backend/static', emptyOutDir: true },
  server: { proxy: { '/api': 'http://127.0.0.1:6770' } },
})
