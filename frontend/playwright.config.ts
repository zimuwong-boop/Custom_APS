import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: 'http://127.0.0.1:15173', trace: 'retain-on-failure' },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1366, height: 768 } },
    },
  ],
  webServer: [
    {
      command: '../.venv/bin/python ../scripts/e2e_server.py',
      url: 'http://127.0.0.1:18081/api/v1/health/ready',
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: 'npm run dev -- --port 15173',
      env: { APS_API_PROXY_TARGET: 'http://127.0.0.1:18081' },
      url: 'http://127.0.0.1:15173',
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
})
