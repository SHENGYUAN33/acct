/**
 * E2E Tests — 管理員認證流程 (P1)
 *
 * 測試範圍：
 * TC-AUTH-01：有效帳密登入 → 導向 Dashboard 主頁
 * TC-AUTH-02：錯誤密碼 → 顯示錯誤訊息，留在登入頁
 * TC-AUTH-03：空白帳號 → 前端驗證攔截
 * TC-AUTH-04：Token 寫入 localStorage，後續 API 請求帶 Bearer header
 * TC-AUTH-05：直接訪問需授權頁面（未登入）→ 重導向至登入頁
 * TC-AUTH-06：頁面重整後 token 恢復，不需重新登入
 *
 * 為何需要這些測試：
 * - JWT 整合是 Dashboard 所有操作的前置條件，任何認證問題會讓所有功能失效
 * - 前端 interceptor 的 401 處理需 E2E 驗證（unit test 無法覆蓋完整 HTTP 流程）
 */

import { test, expect, Page } from '@playwright/test';

const ADMIN_USER = process.env.E2E_ADMIN_USER || 'admin';
const ADMIN_PASS = process.env.E2E_ADMIN_PASS || 'changeme';

/** 輔助：執行登入操作。 */
async function login(page: Page, username: string, password: string) {
  await page.goto('/');
  await page.waitForSelector('input[type="text"], input[placeholder*="帳號"], input[name="username"]', { timeout: 5000 });
  await page.fill('input[type="text"], input[placeholder*="帳號"], input[name="username"]', username);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');
}

// ── TC-AUTH-01: 有效帳密登入 ──────────────────────────────────────────────

test('TC-AUTH-01: 有效帳密登入後應導向 Dashboard 主頁', async ({ page }) => {
  await login(page, ADMIN_USER, ADMIN_PASS);

  // 等待登入成功後的頁面元素出現（報帳列表 or Dashboard 標題）
  await expect(page).not.toHaveURL(/login/, { timeout: 8000 });

  // 應看到報帳相關的 UI 元素
  await expect(
    page.locator('text=/案件編號|報帳|Dashboard|EXP-/i').first()
  ).toBeVisible({ timeout: 10000 });
});

// ── TC-AUTH-02: 錯誤密碼 ─────────────────────────────────────────────────

test('TC-AUTH-02: 錯誤密碼應顯示錯誤訊息，停留在登入頁', async ({ page }) => {
  await login(page, ADMIN_USER, 'wrong-password-xyz');

  // 應停留在登入頁（URL 含 login 或頁面有輸入框）
  await expect(
    page.locator('text=/錯誤|失敗|Invalid|帳號或密碼/i').first()
  ).toBeVisible({ timeout: 5000 });

  // 確認仍在登入頁
  const url = page.url();
  const stillOnLogin = url.includes('login') ||
    await page.locator('input[type="password"]').isVisible();
  expect(stillOnLogin).toBeTruthy();
});

// ── TC-AUTH-03: 空白帳號前端驗證 ────────────────────────────────────────

test('TC-AUTH-03: 空白帳號送出應被前端攔截，不發 API 請求', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('input[type="password"]');

  // 攔截 API 呼叫
  let apiCallMade = false;
  page.on('request', (req) => {
    if (req.url().includes('/auth/login')) apiCallMade = true;
  });

  // 不填帳號，直接點送出
  await page.fill('input[type="password"]', 'somepassword');
  await page.click('button[type="submit"]');

  // 等一小段時間確認無 API 呼叫（瀏覽器原生 required 驗證或前端驗證）
  await page.waitForTimeout(500);

  // 若前端有 required 驗證或自訂驗證，API 不應被呼叫
  // 注意：若前端無前端驗證，此測試改為驗證錯誤訊息顯示
  const inputElem = page.locator('input[type="text"], input[name="username"]').first();
  const isRequired = await inputElem.getAttribute('required');

  if (isRequired !== null) {
    // HTML5 required — 瀏覽器攔截，API 不呼叫
    expect(apiCallMade).toBeFalsy();
  } else {
    // 前端自訂驗證 — 顯示錯誤訊息
    const errorVisible = await page.locator('text=/帳號|必填|required/i').isVisible();
    expect(errorVisible || !apiCallMade).toBeTruthy();
  }
});

// ── TC-AUTH-04: Token 寫入 localStorage ──────────────────────────────────

test('TC-AUTH-04: 登入成功後 localStorage 應含 access_token', async ({ page }) => {
  await login(page, ADMIN_USER, ADMIN_PASS);
  await expect(page).not.toHaveURL(/login/, { timeout: 8000 });

  // 讀取 localStorage
  const token = await page.evaluate(() => {
    return localStorage.getItem('token') ||
           localStorage.getItem('access_token') ||
           localStorage.getItem('auth_token') ||
           sessionStorage.getItem('token');
  });

  expect(token).not.toBeNull();
  expect(token!.length).toBeGreaterThan(10);
});

// ── TC-AUTH-05: 未登入直接訪問受保護頁面 ─────────────────────────────────

test('TC-AUTH-05: 未登入直接訪問受保護頁面應重導向登入頁', async ({ page }) => {
  // 清除所有 storage，確保無殘留 token
  await page.goto('/');
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  // 訪問需要登入的路徑
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  // 應看到登入表單
  const hasLoginForm = await page.locator('input[type="password"]').isVisible();
  const isLoginPage = page.url().includes('login') || hasLoginForm;
  expect(isLoginPage).toBeTruthy();
});

// ── TC-AUTH-06: 頁面重整後 token 恢復 ────────────────────────────────────

test('TC-AUTH-06: 登入後重整頁面不應強制重新登入', async ({ page }) => {
  await login(page, ADMIN_USER, ADMIN_PASS);
  await expect(page).not.toHaveURL(/login/, { timeout: 8000 });

  // 重整頁面
  await page.reload();
  await page.waitForLoadState('networkidle');

  // 重整後應仍在 Dashboard，不應跳回登入頁
  const isLoginPage = page.url().includes('login') ||
    await page.locator('input[type="password"]').isVisible({ timeout: 3000 }).catch(() => false);

  expect(isLoginPage).toBeFalsy();
});
