# 功能規格書

> 版本: v1.2 | Sprint 3 | 最後更新: 2026-04-17

## 概述

AcctAssist 三個 Sprint 累積功能規格，涵蓋 LINE Bot 報帳流程（Onboarding + 批次 + Auto Split）、Dashboard 審核（含登入）、自動化測試。

---

## F1：LINE Bot 報帳流程（Sprint 2/3 架構）

> Sprint 1 原始 WAITING_PHOTO 單張流程已於 Sprint 2 全面重構為下述批次收集架構。

### 機制一：首次使用者 Onboarding（部門一次性設定）

**觸發條件**：`users.department IS NULL`（任何訊息類型均觸發）

```
使用者第一次傳送任何訊息
    → Bot 回覆 Quick Reply 部門選單（製片組/美術組/攝影組/燈光組/場務組/其他）
    → 使用者選部門 → 寫入 users.department（永久，不再詢問）
    → Bot 回覆「✅ 已設定為『攝影組』，請直接上傳憑證照片 📷」
```

部門清單由 `.env` 的 `DEPARTMENTS` 環境變數管理（逗號分隔），不寫死於程式碼。

選配進階 Onboarding（`enable_user_binding=True`）：先綁定真實姓名（step=`BINDING_REAL_NAME`），再選部門。

### 機制二：多張照片批次報帳

**觸發條件**：`users.department IS NOT NULL`

**圖片收集（ImageMessage）：**
- SELECT ... FOR UPDATE 防競態條件
- append `{path, timestamp, message_id}` 至 UserState.pending_images
- [Auto Split 開啟] 重設滑動視窗計時器

**文字備註累積（TextMessage，非指令）：**
- append 至 UserState.pending_description（靜默不回覆）

**確認送出（Postback `action=confirm_submit`）：**
- [Auto Split 開啟] 立即取消 Timer
- 空批次 → 回覆「尚未收到任何照片 📷」
- 非空批次 → 立即 reply「已送出報帳」（< 500ms）→ 清空 pending → BackgroundTask

**BackgroundTask 背景處理：**
1. 序列 OCR（`classify_and_extract()` × N 張，避免 Gemini 429）
2. `create_batch_expense(trigger_by="manual_button")` → 1 筆 Expense + N 筆 ExpenseImage

### 機制三：Auto Split 自動切割（Sprint 3，需 `ENABLE_AUTO_SPLIT=true`）

**觸發條件**：收到圖片後 N 秒（`AUTO_SPLIT_DEBOUNCE_SECONDS`，預設 60）內無新圖片

```
每張照片 → schedule(user_id, N秒, callback)  ← 每次重設滑動視窗
N 秒後 → _auto_split_callback → auto_split_process()
  ① 讀取並清空 pending buffer
  ② 依 timestamp 排序
  ③ 序列 OCR × N 張
  ④ multi_split_logic：以 is_voucher=True 作斷點切割多個群組
  ⑤ 每個群組呼叫 create_batch_expense(trigger_by="auto_split")
```

> ⚠️ **限制**：Auto Split 使用 `asyncio.create_task()`，**僅支援單 Worker**（`uvicorn --workers 1`）。

### LINE 查詢功能（文字指令）

| 指令 | 動作 |
|------|------|
| `查詢` / `查詢進度` | 回傳最近 3 筆 Expense 狀態 |
| `EXP-YYYYMM-NNNN` | 回傳指定流水號的詳情 |
| `補件` / `我要補件` | 進入補件流程（step=`REUPLOADING_{expense_id}`） |
| 部門名稱（如「攝影組」） | 更換部門 |

**狀態對應文字：**
- `PENDING` → 待審核
- `APPROVED` → 已核准
- `REJECTED` → 已作廢（管理員退回，流程結束）
- `NEEDS_MANUAL_REVIEW` → 未審核（需特別注意）
- `WAITING_RETURN` → 待退貨
- `REPLACED_VOID` → 已作廢（沖銷）（換單/折讓情境）

### 重複發票偵測

- OCR 成功且有 `invoice_number` → 查詢是否已有同發票號碼
- 重複時：仍建立新 Expense（status=NEEDS_MANUAL_REVIEW），LINE 回覆末尾附加 `⚠️ 重複提交警告（單號：EXP-…）`
- 無 `invoice_number` 時跳過（不影響正常流程）

---

## F1.5：Dashboard 管理員認證

### 登入流程

```
LoginView → POST /api/v1/auth/login（application/x-www-form-urlencoded）
         → 取得 access_token → localStorage + authStore
         → router 導向 /（ExpenseListView）
         → AppHeader 右上角顯示 authStore.displayName（工號括號）
```

**Token 過期（401）**：Axios interceptor 自動導向 `/login`。

### 帳號建立（admin register）

```
POST /api/v1/auth/register（JSON）
欄位：username, password, display_name, employee_id
回應：201 Created
```

> ⚠️ 此端點無 JWT 防護，正式環境應透過 `enable_register=False` config 關閉。

---

## F2：Dashboard 審核管理

### 頁面結構

| 路由 | 元件 | 功能 |
|------|------|------|
| `/login` | `LoginView` | 管理員登入 |
| `/` | `ExpenseListView` | 報帳清單 + 統計卡 + 篩選 + 分頁 |
| AuditModal（彈出） | `AuditModal` | 詳情、OCR 資料、圖片檢視、審核操作 |

> **Note**：詳情頁採用 Modal 形式（非獨立路由），因現有 UX 為 inline 審核。

### 報帳清單（ExpenseListView）

**支援篩選：**
| 篩選條件 | 說明 |
|---------|------|
| `status` | PENDING / APPROVED / REJECTED / NEEDS_MANUAL_REVIEW / WAITING_RETURN / REPLACED_VOID |
| `date_from` / `date_to` | 上傳日期範圍 |
| `dept` | 部門篩選（前端過濾） |
| `submitter` | 姓名模糊搜尋（前端過濾） |

**顯示欄位：**
- 案件流水號（`serial_number`）
- 上傳者姓名 / 部門
- OCR 申請人 / 金額 / 消費日期
- 審核狀態（Badge）
- 操作按鈕（詳情/審核）

**統計卡：**
- 待審核件數（PENDING + NEEDS_MANUAL_REVIEW）
- 上傳人數
- 總件數 / 有圖片件數

### AuditModal 審核操作

**核可（APPROVED）：**
1. 可選擇修正 OCR 欄位
2. 點擊「核可」→ `PATCH /api/v1/expenses/{id}` with `{status: "APPROVED", ...欄位}`
3. 關閉 Modal，重新拉取清單

**退件（REJECTED）：**
1. 必填退件原因
2. 點擊「退件」→ `PATCH /api/v1/expenses/{id}/reject` with `{reason: "..."}`
3. 後端觸發 LINE 推播通知（依 `ENABLE_LINE_PUSH_REJECT` 開關）
4. 關閉 Modal，重新拉取清單

**補件（圖片上傳）：**
- 憑證圖片：`POST /api/v1/expenses/{id}/images` with `image_type=expense`
- 品項圖片：`POST /api/v1/expenses/{id}/images` with `image_type=item`
- 替換：`POST /api/v1/expenses/{id}/images/replace` with index

---

## F3：後端測試套件

### 測試策略

```
tests/
├── conftest.py                    # SQLite in-memory fixtures
├── unit/
│   ├── test_expense_service.py    # CRUD + 狀態判定 + 流水號
│   ├── test_ocr_service.py        # OCR 結果解析（mock Gemini）
│   └── test_line_service.py       # 狀態機操作（mock LINE SDK）
└── integration/
    ├── test_webhook.py            # Webhook 流程（mock LINE + Gemini）
    └── test_expenses_api.py       # Dashboard API E2E
```

### 覆蓋率目標

| 模組 | 目標覆蓋率 | 說明 |
|------|----------|------|
| `services/expense_service.py` | ≥ 90% | 核心 CRUD 邏輯 |
| `services/ocr_service.py` | ≥ 80% | Mock Gemini API |
| `services/line_service.py` | ≥ 80% | Mock LINE SDK |
| `routers/webhook.py` | ≥ 80% | 含 BackgroundTasks |
| `routers/expenses.py` | ≥ 80% | CRUD 端點 |
| **整體** | **≥ 80%** | `pytest --cov` 量測 |

### 關鍵測試案例

**expense_service：**
- `test_create_expense_pending`：OCR 有 total_amount → status=PENDING
- `test_create_expense_needs_review`：total_amount=None → status=NEEDS_MANUAL_REVIEW
- `test_serial_number_uniqueness`：流水號不重複
- `test_get_or_create_user_idempotent`：同 line_user_id 只建一筆
- `test_reject_expense`：status 更新 + reject_reason 寫入

**webhook：**
- `test_webhook_image_returns_200_immediately`：圖片事件 500ms 內回應
- `test_webhook_invalid_signature_returns_400`
- `test_webhook_ocr_failure_creates_manual_review`

**Sprint 2 批次流程（tests/unit/test_batch_expense.py, tests/integration/test_batch_flow.py）：**
- `test_batch_expense_sum_amounts`：多憑證金額加總
- `test_credit_note_deduction`：CREDIT_NOTE 負數自動扣除
- `test_all_ocr_failed_status`：全部 OCR 失敗 → NEEDS_MANUAL_REVIEW
- `test_onboarding_e2e`：首次使用者觸發 Onboarding
- `test_empty_pending_protection`：空批次防護

**Sprint 3 Auto Split（tests/unit/test_auto_split.py, tests/integration/test_auto_split_flow.py）：**
- `test_multi_split_logic_various_scenarios`：7 種切割場景
- `test_parse_buffer_formats`：新舊 JSON 格式兼容
- `test_trigger_by_recorded`：trigger_by 欄位正確記錄
- `test_confirm_submit_cancels_timer`：手動送出取消計時器

---

## F4：LINE Webhook 超時修正

### 目標
Webhook 收到圖片後 500ms 內回應 HTTP 200，OCR 完成後透過 `push_message` 推送結果。

### 技術方案（BackgroundTasks）

```python
@router.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    # 1. 驗證簽章（< 10ms）
    # 2. 解析事件（< 5ms）
    # 3. 加入背景任務（不等待）
    background_tasks.add_task(handle_image_event, event, db)
    # 4. 立即回 200
    return Response(status_code=200)
```

### 環境變數需求

新增 `LINE_CHANNEL_ACCESS_TOKEN` 至 `.env`（用於 push_message）：
```
LINE_CHANNEL_ACCESS_TOKEN=your_channel_access_token
```

### 驗收標準
- Webhook 回應時間 < 500ms（可用 `time.time()` 量測）
- OCR 完成後 push 訊息正確到達使用者
- OCR 失敗時 push 錯誤提示（不靜默失敗）

---

## F5：技術文件

### 需建立的文件

| 文件 | 路徑 | 內容 |
|------|------|------|
| API 規格書 | `.knowledge/api-spec.md` | 完整 RESTful 端點文件（已有 `api-design.md`，需整合輸出） |
| 部署指南 | `.knowledge/deployment-guide.md` | 本地開發、Staging、Production 部署 SOP |

### 部署指南必含內容
1. 環境需求（Python 版本、Docker 版本、Node.js 版本）
2. 本地開發環境設定（`.env` 說明、Docker Compose、Alembic）
3. Staging 部署步驟（VM 設定、Nginx、SSL、LINE Webhook 設定）
4. 環境變數說明表
5. 常見問題排除（引用 postmortem-log）

---

## 邊界條件與驗收標準

### LINE Bot
- ✅ 同一 `line_user_id` 多次報帳：各自建立獨立 Expense，User 只有一筆
- ✅ 使用者未完成 Onboarding 直接傳圖：觸發 Quick Reply 部門選單，圖片暫不處理
- ✅ OCR API 超時：status=NEEDS_MANUAL_REVIEW，BackgroundTask 完成後 push 通知
- ✅ 圖片非發票（is_voucher=False）：歸入 item_image_url，不計入 total_amount
- ✅ 使用者連按兩次「確認送出」：第二次 pending 為空 → 提示，無重複 Expense
- ✅ Auto Split 與手動送出互斥：手動送出時 cancel Timer，Timer 到期時若 pending 已清空則靜默略過

### Dashboard
- ✅ 篩選條件組合使用（status + 日期 + 部門）
- ✅ 退件必填原因，空字串不允許
- ✅ 分頁邊界（最後一頁、只有一筆）
- ✅ 刪除後清單立即更新

### 測試環境
- ✅ SQLite in-memory 取代 PostgreSQL（`serial_number` 需 mock）
- ✅ Gemini / LINE API 全部 mock，不產生實際 API 呼叫
- ✅ CI 環境無外部依賴（無需 Docker、無需真實 API Key）
