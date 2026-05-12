# 功能規格書

> 版本: v1.0 | Sprint 1 | 最後更新: 2026-04-08

## 概述

AcctAssist Sprint 1 功能規格，涵蓋 LINE Bot 報帳流程、Dashboard 審核、自動化測試與部署。

---

## F1：LINE Bot 報帳流程

### 觸發條件
使用者傳送文字訊息（含「報帳」、「我要報帳」等關鍵字），或傳送圖片（當 step=WAITING_PHOTO）。

### 對話狀態機

```
初始（無狀態）
    → 收到「報帳」類文字 → 回覆部門 QuickReply
    → 使用者選擇部門 → 寫入 user_states(step=WAITING_PHOTO, dept=選擇部門)
    → 收到圖片（step=WAITING_PHOTO）→ 執行 OCR 流程
    → 清除 user_states，回覆結果
```

### 部門選項
`製片組` / `美術組` / `攝影組` / `燈光組` / `其他`

### OCR 流程（Webhook 圖片事件）

| 步驟 | 動作 | 失敗處理 |
|------|------|---------|
| 1 | 驗證 `X-Line-Signature` | 回 400 |
| 2 | **立即回 200**（BackgroundTasks） | — |
| 3 | 下載圖片至 `uploads/{uuid}.jpg` | push 錯誤訊息 |
| 4 | `get_or_create_user(line_user_id)` | push 錯誤訊息 |
| 5 | `update_user_department(dept)` | — |
| 6 | 呼叫 Gemini OCR | OCR 失敗 → status=NEEDS_MANUAL_REVIEW |
| 7 | `create_expense()` 寫入 DB | push 錯誤訊息 |
| 8 | 清除 user_states | — |
| 9 | `push_message()` 推送結果 | log 但不拋錯 |

### 推送訊息格式

**OCR 成功（PENDING）：**
```
✅ 發票辨識成功！
案件編號：EXP-202604-0001
總金額：$1,200
消費日期：2026-04-08
發票號碼：AB-12345678
已建立報帳記錄，等待審核
```

**OCR 失敗（NEEDS_MANUAL_REVIEW）：**
```
⚠️ 發票辨識需人工確認
案件編號：EXP-202604-0002
系統無法自動辨識發票資訊，已建立記錄，請財務人員手動審核。
```

### 實名制規則
- 同一 `line_user_id` 不可重複建立 User（`get_or_create_user` 保證 idempotent）
- `real_name` 需另外透過綁定流程設定（Sprint 1 不涉及）

### 重複發票偵測規則（Sprint 2）
- OCR 辨識後、建立 Expense 前，若 `invoice_number` 有值，呼叫 `find_expense_by_invoice_number()` 查重
- 重複時：仍建立新 Expense，但強制 `needs_manual_review=True`
- LINE 回覆訊息追加警告文字，標示先前已提交的 `serial_number`
- 無 `invoice_number`（OCR 未辨識到）時跳過查重

### LINE 報帳進度查詢（Sprint 2）
觸發方式（在文字訊息處理區塊判斷）：
1. 輸入 `查詢進度` / `查詢` → 呼叫 `get_recent_expenses_by_user(db, user.id, limit=3)` 回傳最近 3 筆
2. 輸入符合 `EXP-\d{6}-\d{4}` 格式 → 呼叫 `get_expense_by_serial_number(db, text)` 回傳單筆詳情

狀態對應文字：`PENDING`→審核中、`APPROVED`→已核准、`REJECTED`→已退回、`NEEDS_MANUAL_REVIEW`→人工審核中

---

## F2：Dashboard 審核管理

### 頁面結構

| 路由 | 元件 | 功能 |
|------|------|------|
| `/` | `ExpenseListView` | 報帳清單 + 統計卡 + 篩選 + 分頁 |
| AuditModal（彈出） | `AuditModal` | 詳情、OCR 資料、圖片檢視、審核操作 |

> **Note**：詳情頁採用 Modal 形式（非獨立路由），因現有 UX 為 inline 審核。

### 報帳清單（ExpenseListView）

**支援篩選：**
| 篩選條件 | 說明 |
|---------|------|
| `status` | PENDING / APPROVED / REJECTED / NEEDS_MANUAL_REVIEW |
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
- ✅ 使用者未選部門直接傳圖：忽略，回覆「請先選擇部門」
- ✅ OCR API 超時（5秒）：status=NEEDS_MANUAL_REVIEW，push 通知
- ✅ 圖片非發票（無法辨識金額）：status=NEEDS_MANUAL_REVIEW

### Dashboard
- ✅ 篩選條件組合使用（status + 日期 + 部門）
- ✅ 退件必填原因，空字串不允許
- ✅ 分頁邊界（最後一頁、只有一筆）
- ✅ 刪除後清單立即更新

### 測試環境
- ✅ SQLite in-memory 取代 PostgreSQL（`serial_number` 需 mock）
- ✅ Gemini / LINE API 全部 mock，不產生實際 API 呼叫
- ✅ CI 環境無外部依賴（無需 Docker、無需真實 API Key）
