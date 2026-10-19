import { defineConfig, devices } from '@playwright/test'

/**
 * Headless browser tests against the production build (`vite preview`).
 * Data is served by each test through page.route, so no test touches a real
 * data bucket or any state site.
 *
 * Uses the installed Google Chrome by default (no browser download). In CI, run
 * `npx playwright install chromium` and set PLAYWRIGHT_CHANNEL=chromium.
 */
const PORT = 4173

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://localhost:${PORT}`,
    channel: process.env.PLAYWRIGHT_CHANNEL ?? 'chrome',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'desktop', use: { ...devices['Desktop Chrome'], channel: process.env.PLAYWRIGHT_CHANNEL ?? 'chrome' } }],
  webServer: {
    command: `npm run build && npx vite preview --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
