/**
 * k6 壓力測試 — LINE Webhook 並發負載
 *
 * 測試情境：模擬多個 LINE 用戶同時傳送圖片的高並發場景
 * - 模擬 20 個並發 VU 同時發送 Webhook 事件
 * - 包含 HMAC 簽章（使用測試 channel secret）
 * - 驗證背景任務架構下 Webhook 在 5 秒內回應
 *
 * 注意：此測試需對 staging 環境執行，不可對 production 執行
 *
 * 執行方式：
 *   k6 run k6/webhook_concurrent.js -e BASE_URL=https://staging.domain.com \
 *     -e LINE_SECRET=your_test_channel_secret
 *
 * SLA 門檻：
 * - p95 回應時間 < 2000ms（Webhook 含背景任務啟動時間）
 * - 錯誤率 < 1%（HTTP 5xx）
 */

import { check, sleep } from 'k6';
import http from 'k6/http';
import { Trend, Rate } from 'k6/metrics';
import crypto from 'k6/crypto';

const webhookLatency = new Trend('webhook_duration', true);
const errorRate      = new Rate('webhook_error_rate');

export const options = {
  scenarios: {
    webhook_burst: {
      executor: 'constant-vus',
      vus: 20,
      duration: '2m',
    },
  },
  thresholds: {
    http_req_duration:   ['p(95)<2000'],
    http_req_failed:     ['rate<0.01'],
    webhook_error_rate:  ['rate<0.01'],
  },
};

const BASE_URL    = __ENV.BASE_URL    || 'http://localhost:8000';
const LINE_SECRET = __ENV.LINE_SECRET || 'test-channel-secret';

/**
 * 產生符合 LINE 簽章驗證的 X-Line-Signature。
 * 使用 k6 內建 crypto 模組（與 Python hmac.new 等效）。
 */
function makeSignature(body, secret) {
  const sig = crypto.hmac('sha256', secret, body, 'base64');
  return sig;
}

/** 建立模擬的 LINE ImageMessage Webhook payload。 */
function makeImageWebhook(userId) {
  return JSON.stringify({
    destination: 'Udeadbeefdeadbeef',
    events: [{
      type: 'message',
      mode: 'active',
      timestamp: Date.now(),
      source: { type: 'user', userId },
      replyToken: `reply-${userId}-${Date.now()}`,
      message: {
        type: 'image',
        id: `msg-${Math.floor(Math.random() * 1000000)}`,
        contentProvider: { type: 'line' },
      },
    }],
  });
}

export default function () {
  const userId = `U${Math.floor(Math.random() * 1000000).toString().padStart(10, '0')}`;
  const body = makeImageWebhook(userId);
  const sig  = makeSignature(body, LINE_SECRET);

  const res = http.post(
    `${BASE_URL}/webhook`,
    body,
    {
      headers: {
        'Content-Type': 'application/json',
        'X-Line-Signature': sig,
      },
      timeout: '10s',
    },
  );

  webhookLatency.add(res.timings.duration);

  const ok = check(res, {
    'Webhook HTTP 200': (r) => r.status === 200,
    '5 秒內回應': (r) => r.timings.duration < 5000,
  });

  if (!ok) errorRate.add(1);
  else errorRate.add(0);

  sleep(0.5);
}

export function handleSummary(data) {
  return {
    'k6-results/webhook_concurrent_summary.json': JSON.stringify(data),
  };
}
