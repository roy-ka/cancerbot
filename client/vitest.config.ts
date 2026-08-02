import { defineConfig } from 'vitest/config'

// Standalone config so the test run doesn't pull in the app's vite plugins.
// The schema-monitor unit tests exercise pure logic and need no DOM.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
