/**
 * k6 Spike Test — 突發流量測試
 *
 * 測試情境：模擬月底結帳、年節前後的突發流量
 * - 10 秒內從 0 衝到 100 VU
 * - 維持 1 分鐘高壓
 * - 快速降回 0
 *
 * 目的：驗證系統在突發流量下不會崩潰（不要求低延遲，要求不 500）
 *
 * 執行方式：
 *   k6 run k6/spike_test.js -e BASE_URL=https://staging.domain.com
 *
 * SLA 門檻（比標準壓測寬鬆）：
 * - 錯誤率 < 5%（容許少量超時，但不能崩潰）
 * - p99 回應時間 < 10s（允許排隊，但終究要回應）
 */

import { check, sleep } from 'k6';
import http from 'k6/http';
import { Rate, Trend } from 'k6/metrics';

const spikeErrorRate = new Rate('spike_error_rate');
const spikeLatency   = new Trend('spike_duration', true);

export const options = {
  stages: [
    { duration: '10s', target: 100 }, // 突發：10 秒衝到 100 VU
    { duration: '1m',  target: 100 }, // 高壓維持
    { duration: '10s', target: 0   }, // 急降
  ],
  thresholds: {
    http_req_failed:   ['rate<0.05'],  // 容許最多 5% 錯誤（突發場景較寬鬆）
    http_req_duration: ['p(99)<10000'],
    spike_error_rate:  ['rate<0.05'],
  },
};

const BASE_URL   = __ENV.BASE_URL   || 'http://localhost:8000';
const TOKEN      = __ENV.ADMIN_TOKEN || '';

export function setup() {
  // 若未提供 TOKEN，嘗試自動登入
  if (TOKEN) return { token: TOKEN };

  const loginRes = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({ username: __ENV.ADMIN_USER || 'admin', password: __ENV.ADMIN_PASS || 'changeme' }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  return { token: loginRes.json('data.access_token') || '' };
}

export default function (data) {
  const headers = data.token ? { Authorization: `Bearer ${data.token}` } : {};

  // Spike 測試只打最重要的一個端點（避免太多邏輯遮蓋瓶頸）
  const res = http.get(
    `${BASE_URL}/api/v1/expenses?page=1&page_size=20`,
    { headers, timeout: '15s' },
  );

  spikeLatency.add(res.timings.duration);

  const ok = check(res, {
    'Spike 非 5xx': (r) => r.status < 500,
    'Spike 有回應': (r) => r.body && r.body.length > 0,
  });

  if (!ok) spikeErrorRate.add(1);
  else spikeErrorRate.add(0);

  sleep(0.2); // 減少 sleep 讓衝擊更明顯
}

export function handleSummary(data) {
  const p99 = data.metrics.http_req_duration?.values?.['p(99)'] || 0;
  const errRate = data.metrics.http_req_failed?.values?.rate || 0;

  console.log(`Spike Test 結果：p99=${p99.toFixed(0)}ms  錯誤率=${(errRate * 100).toFixed(2)}%`);

  return {
    'k6-results/spike_test_summary.json': JSON.stringify(data),
  };
}
