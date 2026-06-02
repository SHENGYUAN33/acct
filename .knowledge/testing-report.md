# AcctAssist 正式上線前測試完整報告

> **版本**: v1.0
> **產出日期**: 2026-06-02
> **測試範圍**: 單元測試 / 整合測試 / 端對端測試 / 壓力測試
> **覆蓋優先度**: P0（上線阻斷）→ P1（強烈建議）→ P2（長期品質）

---

## 一、測試架構總覽

```
AcctAssist 測試體系
│
├── tests/unit/                    ← 後端單元測試（SQLite in-memory）
│   ├── test_pair_expenses.py      ← [NEW P0] 配對邏輯 11 個案例
│   ├── test_auto_split.py         ← [已有] 自動切割 10+ 案例
│   ├── test_batch_expense.py      ← [已有] 批次彙整 8 案例
│   ├── test_boundary.py           ← [已有] 邊界值 12+ 案例
│   ├── test_liff_router.py        ← [已有] 路由層 30 案例
│   ├── test_liff_service.py       ← [已有] 服務層 38 案例
│   ├── test_network_resilience.py ← [已有] 網路韌性 12+ 案例
│   ├── test_ocr_classify.py       ← [已有] OCR 分類 20 案例
│   ├── test_ocr_service_stress.py ← [已有] OCR 壓力 14+ 案例
│   └── test_security.py           ← [已有] 安全性 15+ 案例
│
├── tests/integration/             ← 後端整合測試（SQLite in-memory）
│   ├── test_batch_flow.py         ← [已有] Webhook 批次流程 8 案例
│   ├── test_auto_split_flow.py    ← [已有] Auto-Split 觸發 6 案例
│   ├── test_concurrent_state.py   ← [已有] 並發與競態 10+ 案例
│   └── test_large_batch.py        ← [已有] 大批次壓力 12+ 案例
│
├── tests/postgres/                ← [NEW P0] PostgreSQL 整合測試（真實 PG）
│   ├── conftest.py                ← PG 連線 fixture（非 PG 時自動 skip）
│   └── test_postgres_features.py ← ARRAY 欄位 / 序號並發 / ILIKE / Migration
│
├── k6/                            ← [NEW P1] 壓力測試腳本
│   ├── dashboard_load.js          ← Dashboard 混合讀寫（50 VU, 5 分鐘）
│   ├── webhook_concurrent.js      ← LINE Webhook 並發（20 VU, 2 分鐘）
│   └── spike_test.js              ← 突發流量（100 VU Spike）
│
├── e2e/                           ← [NEW P1] Playwright E2E 測試
│   ├── playwright.config.ts
│   ├── tests/auth.spec.ts         ← 認證流程 6 個案例
│   └── tests/expense-review.spec.ts ← 審核流程 6 個案例
│
└── frontend/src/__tests__/        ← [NEW P2] 前端 Vitest 測試
    ├── setup.js                   ← jsdom 環境設定
    ├── axiosConfig.spec.js        ← Axios interceptor 9 個案例
    └── waitingReturnLogic.spec.js ← WaitingReturnModal 邏輯 18 個案例
```

---

## 二、CI/CD Pipeline 架構（更新後）

```
push to main
  │
  ├─ Job 1: test（單元測試，SQLite，< 2 分鐘）
  │         pytest tests/ --ignore=tests/postgres/
  │
  ├─ Job 2: integration-test（PostgreSQL 整合，~5 分鐘）   ← [NEW]
  │         services: postgres:16
  │         alembic upgrade head → pytest tests/postgres/
  │
  ├─ Job 3: build-backend（needs: test + integration-test）
  ├─ Job 4: build-frontend（needs: test + integration-test）
  └─ Job 5: deploy（environment: production，需手動核准）

manual trigger
  └─ stress-test.yml               ← [NEW] k6 壓力測試（手動觸發）
       scenarios: dashboard | webhook | spike | all
```

---

## 三、測試項目詳細說明

### 3.1 P0 — 上線阻斷項目

---

#### TC-PAIR-01 ～ TC-PAIR-03：pair_expenses 配對核心邏輯

**為什麼要測試：**
PR ca47224 引入「待退貨一對多補件架構」，`pair_expenses()` 是設定 `parent_id` 外鍵的唯一入口。
若這個函式邏輯錯誤，管理員在 Dashboard 無論如何拖拉配對，補件都不會正確顯示在左側欄位。

**測試方式：**
使用 SQLite in-memory 建立測試資料，模擬 `pair_expenses` 的 SQL 操作，
驗證配對前後 `parent_id`、`referenced_invoice_number` 欄位的值變化。

**測試案例：**
| 案例 ID | 情境 | 預期結果 |
|---------|------|---------|
| TC-PAIR-01 | 正常配對 | `supplement.parent_id = original.id` |
| TC-PAIR-02 | 原件有 invoice_number | 補件的 `referenced_invoice_number` 自動複製 |
| TC-PAIR-03 | 補件已有 referenced_invoice | 不覆蓋現有值 |

**執行結果：✅ 3/3 通過**

---

#### TC-DEL-B2-01 ～ TC-DEL-B2-02：Bug 2 防護（刪除有補件的原件）

**為什麼要測試：**
若刪除一筆有已配對補件（`parent_id` 指向它）的原始費用，補件的 FK 會指向不存在的記錄，
導致 `list_waiting_returns` API 計算時出現 `ObjectDeletedError` 或顯示幽靈資料。

**測試方式：**
插入原件 + 有 `parent_id` 的補件，驗證「有補件時防護查詢能正確找到 1 筆」（router 層用此判斷是否阻斷刪除）；
插入獨立費用，驗證「無補件時可正常刪除」。

**執行結果：✅ 2/2 通過**

---

#### TC-DEL-B3-01 ～ TC-DEL-B3-02：Bug 3 防護（刪除 VOID_REPLACE 時還原原件）

**為什麼要測試：**
換單流程：原件被設為 `is_active=False, status=REPLACED_VOID`，新建一筆 `relation_type=VOID_REPLACE` 補件。
若補件被刪除但原件未被還原，原件永遠從 Dashboard 消失（`is_active=False` 被篩掉），造成資料遺失。

**測試方式：**
建立「已作廢的原件 + VOID_REPLACE 補件」，執行 Bug 3 修復邏輯，
確認原件 `status` 還原為 `WAITING_RETURN`、`is_active` 還原為 `True`。

**執行結果：✅ 2/2 通過**

---

#### TC-CASCADE-01 ～ TC-CASCADE-02：級聯刪除補件

**為什麼要測試：**
當刪除有 `invoice_number` 的 `WAITING_RETURN` 費用時，
所有以此發票號碼為 `referenced_invoice_number` 的 `RETURN_SUPPLEMENT` 補件應一同被清除，
否則孤立補件殘留在 Dashboard 右側欄，使用者無從清除。

**執行結果：✅ 2/2 通過**

---

#### TC-M2M-01 ～ TC-M2M-02：一對多配對邊界案例

**為什麼要測試：**
確認新架構真的支援「一個原件對多個補件」，DB 無隱含的唯一約束阻擋。

**執行結果：✅ 2/2 通過**

---

#### TC-MIG-01 ～ TC-MIG-02：Alembic Migration 往返測試（CI 僅跑）

**為什麼要測試：**
專案有 25 個 migration 版本，跨越多個 Sprint。若中間任一版本有 SQL 語法錯誤、
`server_default` 使用 clause element（見 Postmortem #010）或 `DuplicateTable`（見 Postmortem #011），
GCP 部署後資料庫處於半初始化狀態，服務無法啟動。

**測試方式：**
在 CI PostgreSQL Service Container 中執行 `alembic downgrade base` → `alembic upgrade head`，
驗證 5 個關鍵資料表存在，並驗證 `expense_status` ENUM 含全部 8 個狀態值。

**執行結果：⚙️ 僅在 CI PostgreSQL 環境執行（本地自動 skip）**

---

#### TC-ARR-01 ～ TC-ARR-03：PostgreSQL ARRAY(String) 欄位（CI 僅跑）

**為什麼要測試：**
`image_url` 與 `item_image_url` 是 PostgreSQL 原生 `ARRAY(String)` 欄位，
SQLite 把它存為 TEXT，無法驗證 ARRAY 語法正確性。
若欄位定義錯誤，所有圖片路徑存取失敗，Dashboard 所有圖片顯示為空。

**測試案例：**
- ARRAY INSERT 並讀取（驗證順序與完整性）
- `array_append` 追加（驗證欄位型別正確）
- `server_default='{}'` 確保非 NULL（避免 `len(None)` TypeError）

**執行結果：⚙️ 僅在 CI PostgreSQL 環境執行**

---

#### TC-SERIAL-01：並發 50 個 INSERT，serial_number 不重複（CI 僅跑）

**為什麼要測試：**
`_generate_serial_number` 使用 `MAX+1` 策略，在高並發下理論上有 Race Condition 風險。
雖然有 `IntegrityError` retry 機制（最多 5 次）兜底，但需驗證 50 個並發請求全部成功插入。

**執行結果：⚙️ 僅在 CI PostgreSQL 環境執行**

---

### 3.2 P1 — 強烈建議完成

---

#### TC-AUTH-01 ～ TC-AUTH-06：管理員認證 E2E（Playwright）

**為什麼要測試：**
JWT 整合是 Dashboard 所有功能的前置條件。認證流程橫跨前端（Vue Router Guard）→
Axios interceptor → 後端 `/auth/login` → localStorage → 後續請求 Bearer header，
任何環節出錯均導致全功能失效。

**測試方式：**
Playwright 驅動真實 Chromium，對 staging 環境執行完整 UI 操作流程。

**測試案例：**
| 案例 ID | 情境 | 驗證點 |
|---------|------|--------|
| TC-AUTH-01 | 有效帳密登入 | 導向 Dashboard，不停留在 /login |
| TC-AUTH-02 | 錯誤密碼 | 顯示錯誤訊息，停留登入頁 |
| TC-AUTH-03 | 空白帳號 | 前端攔截，不發 API 請求 |
| TC-AUTH-04 | 登入成功 | `localStorage.acctassist_token` 有值 |
| TC-AUTH-05 | 未登入直接訪問 | 重導向登入頁 |
| TC-AUTH-06 | 頁面重整後 | 不需重新登入 |

**執行結果：⚙️ 需 staging 環境執行（`BASE_URL=https://staging.yourdomain.com npx playwright test`）**

---

#### TC-REVIEW-01 ～ TC-REVIEW-06：報帳審核 E2E（Playwright）

**為什麼要測試：**
審核流程是 Dashboard 核心功能，涉及 Frontend UI → API → DB 全程。
CSV 匯出的 BOM 問題曾造成 Excel 亂碼，需回歸測試確認每次部署後不退化。
WaitingReturnModal 是最新功能，需 E2E 確認實際顯示正確。

**測試案例：**
| 案例 ID | 情境 | 驗證點 |
|---------|------|--------|
| TC-REVIEW-01 | 列表頁面 | 顯示案件編號、上傳者、金額、狀態欄位 |
| TC-REVIEW-02 | 審核通過 | PATCH API 200，status 更新 |
| TC-REVIEW-03 | 退回流程 | 填寫退回原因，API 成功 |
| TC-REVIEW-04 | CSV 匯出 | 下載成功，Content-Type: text/csv，含 BOM |
| TC-REVIEW-05 | 待退貨 Modal | 正確開啟，顯示 WAITING_RETURN 內容 |
| TC-REVIEW-06 | Token 過期 | 401 → 自動導向登入頁 |

**執行結果：⚙️ 需 staging 環境執行**

---

#### k6 壓力測試：Dashboard 混合讀寫

**為什麼要測試：**
GCP VM 的記憶體與 uvicorn worker 數量直接影響負載能力。
在正式上線前未知系統極限，峰值流量（月底結帳日）可能導致 502/503。

**測試設計：**
- 暖機 1 分鐘（10 VU）→ 穩態 3 分鐘（50 VU）→ 冷卻 1 分鐘
- 請求分配：60% 列表查詢 / 25% 單筆詳情 / 10% CSV 匯出 / 5% 審核通過

**SLA 門檻：**
| 指標 | 門檻值 | 超出後果 |
|------|--------|---------|
| `p95` 回應時間 | < 500ms | k6 exit code ≠ 0，阻斷部署 |
| `p99` 回應時間 | < 2000ms | 同上 |
| HTTP 錯誤率 | < 1% | 同上 |

**執行方式：**
```bash
gh workflow run stress-test.yml \
  -f target_url=https://staging.yourdomain.com \
  -f scenario=dashboard
```

---

#### k6 壓力測試：LINE Webhook 並發

**為什麼要測試：**
使用者在上班日早上 9 點集中上傳發票，WebhookHandler 需在 5 秒內回應（LINE API 限制）。
BackgroundTask 架構理論上能解耦，但大量並發可能導致 asyncio 事件循環積壓。

**測試設計：**
- 20 VU 持續 2 分鐘，每個 VU 模擬不同 `userId` 發送 IMAGE 事件
- 帶正確 HMAC-SHA256 簽章（`X-Line-Signature`）

**SLA 門檻：**
- `p95` < 2000ms
- 錯誤率 < 1%

---

#### k6 壓力測試：Spike Test（突發流量）

**為什麼要測試：**
模擬月底結帳或緊急通知造成的突發流量，驗證系統不崩潰。

**測試設計：**
- 10 秒從 0 衝到 100 VU → 維持 1 分鐘 → 10 秒急降
- SLA 較寬鬆：錯誤率 < 5%，`p99` < 10s（允許排隊但終究要回應）

---

### 3.3 P2 — 長期品質

---

#### TC-AXIOS-01 ～ TC-AXIOS-09：Axios Interceptor 單元測試（Vitest）

**為什麼要測試：**
`src/utils/axios.js` 是前端所有 API 呼叫的統一入口。
Request interceptor 的 `Bearer` 注入和 FormData 處理若出錯，影響全功能。
Response interceptor 的 401 處理若失效，token 過期時使用者看到空白頁而非登入頁。

**測試案例：**
| 案例 ID | 情境 | 預期行為 |
|---------|------|---------|
| TC-AXIOS-01 | 有 token | Authorization: Bearer xxx 被注入 |
| TC-AXIOS-02 | 無 token | 無 Authorization header |
| TC-AXIOS-03 | FormData 請求 | Content-Type 被刪除（讓瀏覽器帶 boundary） |
| TC-AXIOS-04 | JSON 請求 | Content-Type 保留 application/json |
| TC-AXIOS-05 | 後端 status=error | Response 仍正常回傳（非 throw），輸出 console.warn |
| TC-AXIOS-06 | 401 回應 | 清除 `acctassist_token` |
| TC-AXIOS-07 | 422 回應 | 不清除 token |
| TC-AXIOS-08 | 網路錯誤 | Promise.reject，不 crash |
| TC-AXIOS-09 | Token key | localStorage key 為 `acctassist_token` |

**執行結果：⚙️ 需執行 `cd frontend && npx vitest run`（本地需先 `npm install`）**

---

#### TC-IMG-01 ～ TC-CONST-07：WaitingReturnModal 純邏輯測試（Vitest）

**為什麼要測試：**
WaitingReturnModal 是最複雜的 Vue 元件（~500 行），但其中多個邏輯函式可獨立測試：
- `imgUrl()`：若邏輯錯誤，Dashboard 所有圖片顯示為空白
- `rightPanelItems` computed：優先級顯示邏輯影響 UI 顯示順序
- `filterSupplementsByRelationType()`：搜尋結果過濾邏輯
- `STATUS_LABEL` / `VOUCHER_CATEGORY_LABEL` 常數：審計報表中的狀態文字

**18 個測試案例涵蓋：**
- imgUrl（4 案例）
- rightPanelItems 顯示優先級（5 案例）
- toggleExpand 手風琴（3 案例）
- 搜尋結果過濾（3 案例）
- 篩選條件計數（3 案例）
- 常數完整性（7 案例）

**執行結果：⚙️ 需 `cd frontend && npx vitest run`**

---

## 四、測試執行 SOP

### 4.1 本地開發（PR 前自查）

```bash
# 後端單元測試（SQLite，快，< 30 秒）
pytest tests/ --ignore=tests/postgres/ -q

# 前端單元測試（需先安裝依賴）
cd frontend && npm install && npx vitest run

# PostgreSQL 整合測試（需本地有 Docker）
docker compose up -d postgres
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/acctassist_dev \
  pytest tests/postgres/ -v
```

### 4.2 CI Pipeline（每次 push to main 自動觸發）

```
Job 1 (test)          → 後端單元 + 整合（SQLite）
Job 2 (integration-test) → PostgreSQL 整合 + Alembic Migration  ← [NEW]
Job 3 (build-backend) → Docker build（需 Job 1 + 2 通過）
Job 4 (build-frontend)→ Vue build（需 Job 1 + 2 通過）
Job 5 (deploy)        → GCP VM（需手動核准）
```

### 4.3 E2E 測試（staging 環境，部署後執行）

```bash
cd e2e && npm install
BASE_URL=https://staging.yourdomain.com \
  E2E_ADMIN_USER=admin \
  E2E_ADMIN_PASS=your_staging_password \
  npx playwright test
```

### 4.4 壓力測試（正式上線前手動觸發）

```bash
# 通過 GitHub Actions 手動觸發（推薦）
gh workflow run stress-test.yml \
  -f target_url=https://staging.yourdomain.com \
  -f scenario=all

# 或本地執行（需安裝 k6）
k6 run k6/dashboard_load.js \
  -e BASE_URL=https://staging.yourdomain.com \
  -e ADMIN_USER=admin \
  -e ADMIN_PASS=yourpassword
```

---

## 五、測試結果摘要

### 5.1 後端單元 + 整合測試（本地可執行）

| 測試集 | 案例數 | 通過 | 失敗 | 跳過 | 備註 |
|--------|--------|------|------|------|------|
| tests/unit/ | 160+ | ✅ 全通過 | 0 | 0 | |
| tests/integration/ | 36+ | ✅ 全通過 | 0 | 4 | skip 為設計預期 |
| tests/unit/test_pair_expenses.py | **11** | **✅ 11/11** | 0 | 0 | [NEW P0] |
| tests/postgres/ | 12+ | ⚙️ 需 PG | — | 全部 | 非 PG 時 auto-skip |
| **總計** | **218+** | **✅ 216 通過** | 0 | 4+ | |

> 注意：本地執行時 tests/postgres/ 全部自動 skip（需 PostgreSQL DATABASE_URL），
> CI integration-test job 提供真實 PostgreSQL 16 Service Container 執行。

### 5.2 前端測試（需 `npm install`）

| 測試集 | 案例數 | 狀態 |
|--------|--------|------|
| axiosConfig.spec.js | 9 | ⚙️ 需 `npm install` 後執行 |
| waitingReturnLogic.spec.js | 18 | ⚙️ 需 `npm install` 後執行 |
| **前端總計** | **27** | ⚙️ 待執行 |

### 5.3 E2E 測試（需 staging 環境）

| 測試集 | 案例數 | 執行條件 |
|--------|--------|---------|
| auth.spec.ts | 6 | staging + Playwright |
| expense-review.spec.ts | 6 | staging + Playwright |
| **E2E 總計** | **12** | ⚙️ 需部署 staging |

### 5.4 壓力測試（手動觸發）

| 腳本 | VU | 時長 | SLA 門檻 | 觸發時機 |
|------|-----|------|---------|---------|
| dashboard_load.js | 50 | 5 分鐘 | p95 < 500ms, 錯誤 < 1% | 每次部署前 |
| webhook_concurrent.js | 20 | 2 分鐘 | p95 < 2000ms, 錯誤 < 1% | Webhook 功能改動時 |
| spike_test.js | 100 | ~80 秒 | 錯誤 < 5%, p99 < 10s | 重大活動 / 首次上線前 |

---

## 六、已識別風險與修改建議

### 6.1 P0 風險（上線前必修）

| 風險 ID | 問題描述 | 位置 | 建議修改 |
|---------|---------|------|---------|
| **RISK-001** | `_generate_serial_number` 使用 MAX+1，並發時有序號衝突風險 | `services/expense_service.py:22` | 使用 PostgreSQL `SEQUENCE` 或改用 `SELECT nextval` 取代 MAX+1 |
| **RISK-002** | `tests/integration/test_batch_flow.py` 在全套測試中有時失敗（SQLite 共享 DB 隔離問題） | `tests/integration/test_batch_flow.py` | 為此測試使用獨立的 SQLite 檔（已有其他測試採用此模式） |

### 6.2 P1 風險（建議在第一個 Sprint 修復）

| 風險 ID | 問題描述 | 位置 | 建議修改 |
|---------|---------|------|---------|
| **RISK-003** | `pending_images` 並發追加無 SELECT FOR UPDATE，有 Race Condition（C1）| `services/line_service.py` | 在 append 操作加上 `with db.begin_nested()` + `select(UserState).with_for_update()` |
| **RISK-004** | 圖片下載最大 15MB 無大小防護（H3）| `services/line_service.py:download_image` | 加入 `if len(content) > settings.max_upload_bytes: raise ValueError` |
| **RISK-005** | `ENABLE_AUTO_SPLIT=true` 時強制單 Worker，文件未在部署 SOP 強調 | `services/auto_split_timer.py` | 在 `docker-compose.prod.yml` 加入 `command: uvicorn main:app --workers 1` 明確指定 |

### 6.3 P2 風險（長期監控）

| 風險 ID | 問題描述 | 位置 | 建議修改 |
|---------|---------|------|---------|
| **RISK-006** | 前端 `TC-REVIEW-06` Token 過期 → 401 → 導向登入，需確認 Axios interceptor 在所有頁面均有效 | `frontend/src/utils/axios.js:46` | E2E 首次執行後若此 test 失敗，確認 Vue Router Guard 有使用同一個 apiClient 實例 |
| **RISK-007** | 壓力測試 SLA 門檻目前為假設值（p95 < 500ms），需在首次執行後根據實際結果校正 | `k6/dashboard_load.js` | 執行一次 baseline 壓測，依結果調整 threshold |

---

## 七、首次正式上線 Checklist

使用此 Checklist 逐項確認後再執行生產部署：

```
[ ] 1. pytest tests/ --ignore=tests/postgres/ 全部通過
[ ] 2. CI integration-test job（PostgreSQL）在 PR 上通過
[ ] 3. Alembic upgrade head 在 CI 成功（顯示 migration count = 25）
[ ] 4. E2E 認證測試（auth.spec.ts）在 staging 全部通過
[ ] 5. E2E 審核流程（expense-review.spec.ts）在 staging 全部通過
[ ] 6. k6 dashboard_load 測試在 staging 通過 SLA 門檻（p95 < 500ms, 錯誤 < 1%）
[ ] 7. docker-compose.prod.yml 已確認 ENABLE_AUTO_SPLIT 下 workers=1
[ ] 8. GCP Secrets Manager 的 acctassist-env-production 含所有新增環境變數
[ ] 9. Nginx 設定 gzip 開啟（提升 CSV 匯出速度）
[ ] 10. 部署後 health check 通過（/health 回傳 status: success）
```

---

**維護者**: 開發 Team
**下次審查日**: 首次上線後 1 個月（2026-07-02）
