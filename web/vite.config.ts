import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// In development the API runs separately (`eb serve`, port 8000); Vite forwards /api to it.
// In production the API serves the built files itself, so there is one origin.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Identifies a build, so a browser's saved cache from an older deploy isn't reused.
  define: { __BUILD_ID__: JSON.stringify(Date.now().toString(36)) },
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
