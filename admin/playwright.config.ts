import { defineConfig, devices } from '@playwright/test'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const port = Number(process.env.E2E_PORT || 18110)
const gatewayToken = process.env.E2E_GATEWAY_TOKEN || 'shenyu-e2e-smoke'
const baseURL = process.env.E2E_BASE_URL || `http://127.0.0.1:${port}`

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  reporter: process.env.CI
    ? [['line'], ['html', { open: 'never' }]]
    : [['line']],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: 'python gateway.py',
        cwd: '..',
        url: `${baseURL}/health`,
        timeout: 120_000,
        reuseExistingServer: false,
        env: {
          PYTHON_DOTENV_DISABLED: '1',
          PORT: String(port),
          GATEWAY_API_KEY: gatewayToken,
          GATEWAY_DB_PATH: join(tmpdir(), `shenyu-gateway-e2e-${process.pid}.db`),
          SUPABASE_URL: '',
          SUPABASE_SERVICE_KEY: '',
          ANTHROPIC_API_KEY: '',
          ENABLE_CHAT_ARCHIVE: 'false',
          ENABLE_HEARTBEAT_ARCHIVE: 'false',
          ENABLE_RECALL_SYNC_WORKER: 'false',
          ENABLE_RECALL_EMBEDDING_WORKER: 'false',
        },
      },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
