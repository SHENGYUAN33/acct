import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E 設定
 *
 * 目標環境：透過 BASE_URL 環境變數指定（staging 或 local dev server）
 * 預設：http://localhost （Nginx 前端入口）
 *
 * 執行方式：
 *   npx playwright test                              # headless
 *   npx playwright test --headed                    # 有頭瀏覽器
 *   BASE_URL=https://staging.yourdomain.com npx playwright test
 */
export default defineConfig({
  testDir: './tests',
  timeout: 30_000,       // 每個 test 最多 30 秒
  retries: 1,            // CI 中失敗自動重試一次
  workers: 2,            // 2 個 worker 並行（避免對後端過大壓力）
  reporter: [
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
    ['list'],
  ],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost',
    headless: true,
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
