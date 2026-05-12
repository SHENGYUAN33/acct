# AcctAssist 系統架構

> 版本: v1.0 | Sprint 3 | 最後更新: 2026-04-17
> 參考層級：🔵（輔助理解，非強制依據）

---

## 1. 整體系統架構

```
┌──────────────────┐     ┌────────────────────┐
│   LINE App       │     │  Web Browser        │
│   (使用者)        │     │  (管理員 Dashboard) │
└────────┬─────────┘     └──────────┬──────────┘
         │ Webhook（HTTP POST）      │ REST API（Bearer JWT）
         ▼                          ▼
┌─────────────────────────────────────────────────────────┐
│                  FastAPI Backend                         │
│                                                         │
│  ┌─────────────┐  ┌──────────────────┐  ┌───────────┐  │
│  │  /webhook   │  │  /api/v1/expenses │  │/api/v1/   │  │
│  │  (public)   │  │  (JWT required)   │  │auth,admin │  │
│  └──────┬──────┘  └────────┬─────────┘  └─────┬─────┘  │
│         │                  │                   │        │
│         └──────────────────┴───────────────────┘        │
│                            │                            │
│               ┌────────────▼────────────┐               │
│               │      Service Layer       │               │
│               │  • expense_service.py    │               │
│               │  • line_service.py       │               │
│               │  • ocr_service.py        │               │
│               │  • auto_split_service.py │               │
│               │  • auto_split_timer.py   │               │
│               └────────────┬────────────┘               │
│                            │                            │
│               ┌────────────▼────────────┐               │
│               │   SQLAlchemy AsyncORM   │               │
│               └────────────┬────────────┘               │
└────────────────────────────┼────────────────────────────┘
                             │
                   ┌─────────▼──────────┐
                   │   PostgreSQL 16     │
                   │   (Docker)          │
                   └────────────────────┘

      ┌───────────────────────┐
      │  外部 API              │
      │  • Google Gemini API   │  (OCR 辨識)
      │  • LINE Messaging API  │  (Webhook / Push / Reply)
      └───────────────────────┘
```

---

## 2. 後端分層架構

### 分層責任對照

| 層級 | 檔案 | 只負責 | 絕對不做 |
|------|------|--------|---------|
| **Router** | `routers/*.py` | 接收請求、驗證格式、呼叫 Service、組裝回應 | 業務邏輯、DB 直接操作、OCR 呼叫 |
| **Service** | `services/*.py` | 業務邏輯、DB 操作封裝、第三方 API 呼叫 | 路由綁定、HTTP 回應格式化 |
| **Model** | `models/*.py` | ORM 資料結構定義、表關聯 | 業務邏輯 |
| **Schema** | `schemas/*.py` | Pydantic 請求/回應驗證 | DB 操作、業務邏輯 |
| **Core** | `core/*.py` | 全域設定（config.py）、DB session（database.py）、JWT（security.py） | 業務邏輯 |

### 目錄結構

```
ocr/
├── main.py                   # FastAPI 入口（掛載路由、CORS、startup）
├── core/
│   ├── config.py             # pydantic-settings；所有設定集中管理
│   ├── database.py           # SQLAlchemy engine/session；get_db() dependency
│   └── security.py           # JWT 建立/驗證（HS256）
├── models/
│   ├── user.py               # users 表 ORM
│   ├── expense.py            # expenses 表 ORM + ExpenseStatus enum
│   ├── expense_image.py      # expense_images 表 ORM（Sprint 2）
│   ├── user_state.py         # user_states 表 ORM
│   └── admin_user.py         # admin_users 表 ORM
├── schemas/
│   ├── expense.py            # ExpenseRead / ExpenseCreate / ExpenseUpdate
│   ├── expense_image.py      # ExpenseImageRead
│   ├── ocr.py                # VoucherOCRResult（Gemini 回傳結構）
│   └── user.py               # UserRead
├── routers/
│   ├── webhook.py            # POST /webhook（LINE 事件處理）
│   ├── expenses.py           # /api/v1/expenses CRUD
│   ├── auth.py               # /api/v1/auth/login & register
│   └── admin.py              # /api/v1/admin/setup-rich-menu
├── services/
│   ├── expense_service.py    # Expense CRUD + User CRUD + 批次建立
│   ├── line_service.py       # LINE API 封裝（reply/push/download/rich-menu）
│   ├── ocr_service.py        # Gemini OCR（classify_and_extract / extract_invoice_data）
│   ├── auto_split_service.py # Auto Split（Sprint 3）：buffer 解析 + 切割邏輯
│   └── auto_split_timer.py   # Per-user asyncio Timer 管理（Sprint 3）
├── alembic/
│   └── versions/             # 16 個 migrations（24e8bd9d46f1 → o2p3q4r5s6t7）
├── scripts/
│   └── setup_rich_menu.py    # 一次性 Rich Menu 設定腳本
├── tests/
│   ├── conftest.py           # SQLite in-memory fixtures + mock 注入
│   ├── unit/                 # 單元測試（test_batch_expense, test_ocr_classify, test_auto_split）
│   └── integration/          # 整合測試（test_batch_flow, test_auto_split_flow）
└── frontend/
    ├── src/
    │   ├── views/            # LoginView, ExpenseListView
    │   ├── components/       # AppHeader, ExpenseTable, AuditModal, FilterPanel
    │   ├── stores/           # expenseStore, authStore（Pinia）
    │   ├── api/              # expenseApi.js, authApi.js（Axios 封裝）
    │   ├── utils/            # axios.js（instance + interceptors）
    │   └── router/           # index.js（/login → / 路由守衛）
    └── ...
```

---

## 3. 關鍵資料流

### LINE Bot 批次報帳（主流程）

```
使用者傳圖片 → POST /webhook
  → 驗證 X-Line-Signature
  → 判斷 users.department IS NULL？ → Onboarding QuickReply
  → 下載圖片至 uploads/{uuid}.jpg
  → SELECT user_states FOR UPDATE
  → append pending_images（含 timestamp, message_id）
  → [Auto Split] auto_split_timer.schedule(user_id, 60s, callback)
  → 立即回 HTTP 200

使用者按「確認送出」（Postback: action=confirm_submit）
  → [Auto Split] auto_split_timer.cancel(user_id)
  → pending 為空 → 回覆提示，結束
  → reply「已送出報帳」（< 500ms）
  → 清空 pending（防重複）
  → background_tasks.add_task(_process_batch, trigger_by="manual_button")

_process_batch（BackgroundTask）
  → 序列 classify_and_extract() × N
  → create_batch_expense() → INSERT expenses + N × expense_images
  → db.close()
```

### Dashboard 審核（主流程）

```
管理員 → POST /api/v1/auth/login → JWT Token
        → GET /api/v1/expenses（含分頁篩選）
        → GET /api/v1/expenses/{id}/images（批次子圖）
        → PATCH /api/v1/expenses/{id}（核可）
        → PATCH /api/v1/expenses/{id}/reject（退件 + LINE 推播）
```

---

## 4. 功能開關（影響架構行為）

| 開關（.env） | 預設 | 影響 |
|-------------|------|------|
| `ENABLE_AUTO_SPLIT` | `false` | 是否啟動 Auto Split Timer（⚠️ 僅限單 Worker） |
| `AUTO_SPLIT_DEBOUNCE_SECONDS` | `60` | 滑動視窗等待秒數 |
| `ENABLE_USER_BINDING` | `true` | 是否啟用實名綁定 Onboarding 流程 |
| `ENABLE_LINE_PUSH_REJECT` | `true` | 退件時是否推播 LINE 通知 |
| `DEPARTMENTS` | `製片組,...,其他` | 部門清單（逗號分隔） |

---

## 5. 外部依賴

| 服務 | SDK | 用途 | 注意 |
|------|-----|------|------|
| Google Gemini API | `google-genai` | 發票 OCR 辨識（classify_and_extract） | 免費版 RPM 限制 → 序列執行，非並行 |
| LINE Messaging API | `line-bot-sdk` | Webhook 驗證、Reply/Push Message、Rich Menu | reply_token 只能用一次，逾時則 push |
| PostgreSQL 16 | SQLAlchemy 2.0 + asyncpg/psycopg2 | 主資料庫 | Docker Compose 本地開發 |

---

## 6. 測試架構

```
tests/
├── conftest.py          # SQLite in-memory（psycopg2 mock 注入）
├── unit/
│   ├── test_ocr_classify.py    # OCR 5 類別 + 降級（mock Gemini）
│   ├── test_batch_expense.py   # create_batch_expense 彙整規則
│   └── test_auto_split.py      # multi_split_logic + _parse_buffer + Timer
└── integration/
    ├── test_batch_flow.py       # Onboarding E2E + 批次流程 E2E
    └── test_auto_split_flow.py  # trigger_by 記錄 + Timer 取消
```

**關鍵 mock 策略**：
- `psycopg2` → `sys.modules.setdefault("psycopg2", MagicMock())` 防 import 失敗
- `Base.metadata.create_all` → patch 防 startup 連接真實 PG
- `_generate_serial_number` → 固定回傳值
- Gemini / LINE SDK → `MagicMock()` + `AsyncMock()`

---

*文件維護：每次 Sprint 有架構變動時同步更新，版本號遞增。*
