/**
 * k6 壓力測試 — Dashboard 混合讀寫負載
 *
 * 測試情境：模擬管理員在 Dashboard 進行日常操作的混合請求比例
 * - 60% GET /api/v1/expenses（列表查詢）
 * - 25% GET /api/v1/expenses/{id}（單筆詳情）
 * - 10% GET /api/v1/expenses/export（CSV 匯出）
 * - 5%  PATCH /api/v1/expenses/{id}（審核通過）
 *
 * 執行方式：
 *   k6 run k6/dashboard_load.js -e BASE_URL=https://your-staging-domain.com
 *   k6 run k6/dashboard_load.js -e BASE_URL=http://localhost:8000
 *
 * SLA 門檻（threshold 未達時 k6 回傳非零 exit code，可擋住 CI/CD）：
 * - p95 回應時間 < 500ms（列表查詢）
 * - p99 回應時間 < 2000ms（含 CSV 匯出）
 * - 錯誤率 < 1%
 */

import { check, sleep, group } from 'k6';
import http from 'k6/http';
import { Trend, Rate, Counter } from 'k6/metrics';

// ── 自訂 metrics ──────────────────────────────────────────────────────────
const listLatency    = new Trend('expense_list_duration', true);
const detailLatency  = new Trend('expense_detail_duration', true);
const exportLatency  = new Trend('expense_export_duration', true);
const approveLatency = new Trend('expense_approve_duration', true);
const errorRate      = new Rate('error_rate');
const totalRequests  = new Counter('total_requests');

// ── 負載設定 ──────────────────────────────────────────────────────────────
export const options = {
  stages: [
    { duration: '1m', target: 10 },  // 暖機：爬升至 10 VU
    { duration: '3m', target: 50 },  // 穩態：50 VU（預估峰值 2 倍）
    { duration: '1m', target: 0  },  // 冷卻
  ],
  thresholds: {
    http_req_duration:        ['p(95)<500', 'p(99)<2000'],
    http_req_failed:          ['rate<0.01'],
    'expense_list_duration':  ['p(95)<500'],
    'expense_export_duration':['p(99)<3000'],
    error_rate:               ['rate<0.01'],
  },
};

const BASE_URL     = __ENV.BASE_URL    || 'http://localhost:8000';
const ADMIN_USER   = __ENV.ADMIN_USER  || 'admin';
const ADMIN_PASS   = __ENV.ADMIN_PASS  || 'changeme';

// ── 登入取 token（setup 函式每次 VU 初始化時執行一次）────────────────────
export function setup() {
  const loginRes = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({ username: ADMIN_USER, password: ADMIN_PASS }),
    { headers: { 'Content-Type': 'application/json' } },
  );

  check(loginRes, {
    '登入 HTTP 200': (r) => r.status === 200,
    '取得 access_token': (r) => r.json('data.access_token') !== null,
  });

  const token = loginRes.json('data.access_token');
  if (!token) {
    console.error('登入失敗，無法取得 token，請確認 ADMIN_USER / ADMIN_PASS 環境變數');
  }

  // 取一筆 expense_id 供後續測試用
  const listRes = http.get(
    `${BASE_URL}/api/v1/expenses?page=1&page_size=1`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const items = listRes.json('data.items') || [];
  const sampleId = items.length > 0 ? items[0].id : null;

  return { token, sampleId };
}

// ── 主要測試邏輯 ───────────────────────────────────────────────────────────
export default function (data) {
  const { token, sampleId } = data;
  const headers = { Authorization: `Bearer ${token}` };

  // 隨機決定本次 VU 執行哪種操作（依比例分配）
  const roll = Math.random();

  if (roll < 0.60) {
    // ── 60%：報帳列表查詢 ────────────────────────────────────────────
    group('列表查詢', () => {
      const params = [
        '?page=1&page_size=20',
        '?page=1&page_size=20&status=PENDING',
        '?page=1&page_size=20&q=EXP-',
      ];
      const url = `${BASE_URL}/api/v1/expenses${params[Math.floor(Math.random() * params.length)]}`;
      const res = http.get(url, { headers });

      listLatency.add(res.timings.duration);
      totalRequests.add(1);
      const ok = check(res, {
        '列表查詢 200': (r) => r.status === 200,
        '列表有 data 欄位': (r) => r.json('data') !== null,
      });
      if (!ok) errorRate.add(1);
      else errorRate.add(0);
    });

  } else if (roll < 0.85) {
    // ── 25%：單筆詳情查詢 ────────────────────────────────────────────
    group('單筆詳情', () => {
      if (!sampleId) { errorRate.add(0); return; }
      const res = http.get(`${BASE_URL}/api/v1/expenses/${sampleId}`, { headers });

      detailLatency.add(res.timings.duration);
      totalRequests.add(1);
      const ok = check(res, {
        '詳情查詢 200': (r) => r.status === 200,
        '回傳 serial_number': (r) => r.json('data.serial_number') !== undefined,
      });
      if (!ok) errorRate.add(1);
      else errorRate.add(0);
    });

  } else if (roll < 0.95) {
    // ── 10%：CSV 匯出 ─────────────────────────────────────────────────
    group('CSV 匯出', () => {
      const res = http.get(`${BASE_URL}/api/v1/expenses/export`, { headers });

      exportLatency.add(res.timings.duration);
      totalRequests.add(1);
      const ok = check(res, {
        'CSV 匯出 200': (r) => r.status === 200,
        'Content-Type text/csv': (r) => (r.headers['Content-Type'] || '').includes('text/csv'),
      });
      if (!ok) errorRate.add(1);
      else errorRate.add(0);
    });

  } else {
    // ── 5%：審核通過 ──────────────────────────────────────────────────
    group('審核通過', () => {
      if (!sampleId) { errorRate.add(0); return; }
      const res = http.patch(
        `${BASE_URL}/api/v1/expenses/${sampleId}`,
        JSON.stringify({ status: 'APPROVED' }),
        { headers: { ...headers, 'Content-Type': 'application/json' } },
      );

      approveLatency.add(res.timings.duration);
      totalRequests.add(1);
      const ok = check(res, {
        '審核更新 200': (r) => r.status === 200,
      });
      if (!ok) errorRate.add(1);
      else errorRate.add(0);
    });
  }

  sleep(1);
}

export function handleSummary(data) {
  return {
    'k6-results/dashboard_load_summary.json': JSON.stringify(data),
  };
}
