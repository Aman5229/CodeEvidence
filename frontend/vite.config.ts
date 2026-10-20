import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  build: {
    // Mermaid's parser chunk is ~660 kB, but it is loaded only when a review's diagram is shown
    // (a dynamic import); the pages themselves stay well below 500 kB.
    chunkSizeWarningLimit: 700,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
