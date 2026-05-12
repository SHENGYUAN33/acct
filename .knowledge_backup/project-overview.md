# AcctAssist 專案概述

> **專案類型**: 企業內部報帳系統
> **版本**: v1.2 (Sprint 2 — 批次報帳)
> **最後更新**: 2026-04-11

---

## 1. 專案簡介

AcctAssist 是一個結合 LINE Bot 與 AI OCR 的智能報帳系統，專為影視製作團隊設計。使用者透過 LINE 上傳發票照片，系統自動辨識發票資訊並建立報帳記錄，管理者透過 Web Dashboard 進行審核與管理。

**核心價值**：
- 📱 零學習成本：使用 LINE 作為前端介面
- 🤖 AI 自動化：Gemini OCR 自動擷取發票資訊
- 📊 集中管理：Dashboard 統一審核與追蹤
- 🔒 實名制：LINE ID 綁定使用者身份

---

## 2. 技術棧

### 後端 (Backend)

| 技術 | 版本 | 用途 |
|------|------|------|
| **Python** | 3.10+ | 主程式語言 |
| **FastAPI** | - | Web 框架 + 非同步 API |
| **PostgreSQL** | 16 | 主資料庫（Docker） |
| **SQLAlchemy** | 2.0 | ORM |
| **Alembic** | - | 資料庫遷移工具 |
| **Google Gemini API** | 2.5-flash | 發票 OCR 辨識 |
| **LINE Bot SDK** | - | LINE Messaging API 整合 |
| **Pydantic Settings** | - | 設定管理（.env） |

### 前端 (Frontend)

| 技術 | 用途 |
|------|------|
| **Vue 3** | 前端框架（Composition API） |
| **TailwindCSS** | CSS 框架 |
| **Axios** | HTTP 客戶端 |

### 開發工具

| 工具 | 用途 |
|------|------|
| **pytest** | 單元測試 |
| **Docker Compose** | PostgreSQL 容器化 |
| **Git** | 版本控制 |

---

## 3. 系統架構

### 3.1 整體架構圖

```
┌─────────────┐
│  LINE App   │ (使用者介面)
└──────┬──────┘
       │ Webhook
       ↓
┌─────────────────────────────────────┐
│         FastAPI Backend             │
│  ┌──────────┐  ┌─────────────────┐ │
│  │  Webhook │  │  Dashboard API  │ │
│  │  Router  │  │  (CRUD)         │ │
│  └─────┬────┘  └────────┬────────┘ │
│        ↓                ↓           │
│  ┌──────────────────────────────┐  │
│  │      Service Layer           │  │
│  │  • LINE Service              │  │
│  │  • OCR Service (Gemini)      │  │
│  │  • Expense Service (CRUD)    │  │
│  └──────────┬───────────────────┘  │
│             ↓                       │
│  ┌──────────────────────┐          │
│  │  SQLAlchemy ORM      │          │
│  └──────────┬───────────┘          │
└─────────────┼────────────────────────┘
              ↓
      ┌───────────────┐
      │  PostgreSQL   │
      │   (Docker)    │
      └───────────────┘

            ↑
            │ HTTP
      ┌─────────────┐
      │  Vue 3 SPA  │ (審核 Dashboard)
      └─────────────┘
```

### 3.2 資料流程

**批次報帳流程（Sprint 2 — LINE → Backend）：**
```
首次使用（Onboarding）：
  使用者傳任意訊息
    ↓
  Webhook 偵測 users.department IS NULL
    ↓
  回覆部門 Quick Reply 選單（一次性，永久記錄）
    ↓
  使用者選部門 → Postback → 寫入 users.department

日常批次流程：
  使用者傳發票照片（可多張，靜默累積不回覆）
    ↓
  ImageMessage → SELECT FOR UPDATE 取得 UserState
    ↓
  append image_path 至 pending_images（JSON 陣列）

  使用者傳文字備註（可選，靜默累積不回覆）
    ↓
  append 至 pending_description

  使用者按 Rich Menu「✅ 確認送出」
    ↓
  Postback(action=confirm_submit)
    ↓
  [空批次防護] pending 為空 → reply 提示，結束
    ↓
  立即 reply「已送出報帳」（< 500ms，唯一回覆）
    ↓
  清空 pending（防重複送出）
    ↓
  BackgroundTask 非同步執行（靜默，不推播）：
    序列 classify_and_extract() × N 張（防 Gemini 429）
      ↓
    create_batch_expense()：
      - is_voucher=True  → image_url（憑證圖片陣列）
      - is_voucher=False → item_image_url（物品影像陣列）
      - user text note   → item_description
      - voucher_categories（去重憑證類別清單）
```

**審核流程（Dashboard → Backend）：**
```
管理者登入 Dashboard
  ↓
GET /api/v1/expenses (查詢待審核清單)
  ↓
GET /api/v1/expenses/{id}/images (查詢子圖清單)
  ↓
AuditModal 顯示發票圖片 + OCR 資料 + 各憑證類型
  ↓
PATCH /api/v1/expenses/{id} (APPROVED / REJECTED + 原因)
  ↓
更新資料庫狀態
```

---

## 4. 核心功能

### 4.1 LINE Bot 報帳流程

**功能清單：**
- ✅ 部門一次性設定（Onboarding，首次使用時選部門，永久記錄）
- ✅ 批次照片上傳（多張累積，COLLECTING 模式）
- ✅ 文字備註累積（附加說明可分段傳送）
- ✅ Rich Menu 常駐「✅ 確認送出」按鈕
- ✅ 即時計數回饋（「已收到第 N 張 📸」）
- ✅ 批次摘要 Flex Message（各憑證類型 × 數量 × 金額 + 合計 + 案件編號）
- ✅ 5 類憑證 OCR 辨識（INVOICE/RECEIPT/LABOR_SERVICE/TRANSPORTATION/CREDIT_NOTE）
- ✅ CREDIT_NOTE 折讓自動扣除（負數加總）
- ✅ 實名制（LINE User ID 綁定）
- ✅ 空批次防護（pending 為空時按「確認送出」→ 提示）
- ✅ 非支援訊息防護（貼圖/語音 → 提示，不破壞 pending）

**對話範例（批次報帳）：**
```
[首次使用]
Bot: 👋 歡迎使用 AcctAssist！請先選擇你的部門
     [QuickReply: 製片組 | 美術組 | 攝影組 | 燈光組 | 其他]
使用者: [點選] 攝影組
Bot: ✅ 部門已設定：攝影組（之後無需再選）

[日常批次報帳]
使用者: [上傳發票照片 1]
Bot: 已收到第 1 張 📸
使用者: [上傳發票照片 2]
Bot: 已收到第 2 張 📸
使用者: 4/10 拍攝餐費
Bot: 備註已記錄 📝
使用者: [按 Rich Menu 確認送出]
Bot: ⏳ 處理中，請稍候...
     （< 500ms 即時回應）
Bot: [Flex Message 批次摘要]
     ✅ 報帳完成 | EXP-202604-0001
     統一發票 × 1｜$2,400
     收 據  × 1｜$350
     合計 NT$ 2,750
     組別：攝影組｜備註：4/10 拍攝餐費
```

### 4.2 Gemini OCR 發票辨識

**辨識欄位：**
- 申請人姓名 (`submitter_name`)
- 品項描述 (`item_description`)
- 消費日期 (`expense_date`)
- 發票號碼 (`invoice_number`)
- 總金額 (`total_amount`) ✨ **關鍵欄位**
- 稅前金額 (`net_amount`)
- 稅額 (`tax_amount`)
- 賣方統一編號 (`seller_tax_id`)
- 賣方名稱 (`seller_name`)

**狀態判定邏輯：**
- OCR 成功且有 `total_amount` → `PENDING`（等待審核）
- OCR 失敗或無 `total_amount` → `NEEDS_MANUAL_REVIEW`（需人工處理）

### 4.3 Dashboard 審核管理

**功能清單：**
- ✅ 報帳清單查詢（支援 status / 日期範圍過濾）
- ✅ 發票圖片檢視
- ✅ OCR 資料檢視
- ✅ 審核操作（通過/退件）
- ✅ 退件原因記錄
- ⏳ 使用者統計報表（未來功能）
- ⏳ 部門消費分析（未來功能）

**API 端點：**
```
# 認證
POST   /api/v1/auth/login              # 帳號密碼登入，回傳 JWT
POST   /api/v1/auth/register           # 建立新管理員帳號

# 報帳管理（需 JWT）
GET    /api/v1/expenses                # 清單查詢（含分頁/狀態/日期篩選）
GET    /api/v1/expenses/{id}           # 單筆詳情
GET    /api/v1/expenses/{id}/images    # 批次子圖清單（Sprint 2 新增）
PATCH  /api/v1/expenses/{id}           # 部分更新（含 status=APPROVED）
PATCH  /api/v1/expenses/{id}/reject    # 退件（設 REJECTED + 原因 + LINE 推播）
DELETE /api/v1/expenses/{id}           # 刪除

# 系統
POST   /webhook                        # LINE Webhook
GET    /health                         # 健康檢查
```

**前端認證流程：**
```
使用者在 LoginView 輸入帳號密碼
  ↓
POST /api/v1/auth/login (application/x-www-form-urlencoded)
  ↓
取得 access_token → 存入 localStorage
username → 存入 localStorage (authStore)
  ↓
router 導向 /（ExpenseListView）
  ↓
AppHeader 右上角顯示 authStore.username
```

---

## 5. 資料庫結構

### 核心資料表

| 表名 | 用途 | 關鍵欄位 |
|------|------|---------|
| `users` | 使用者主表 | `line_user_id` (unique), `department` |
| `expenses` | 報帳主表（每次批次送出一筆） | `status`, `total_amount`, `serial_number`, `voucher_categories` |
| `expense_images` | 批次報帳的各張子圖（Sprint 2 新增） | `expense_id` (FK), `is_voucher`, `voucher_category`, `sequence_order` |
| `user_states` | LINE 對話狀態（COLLECTING 模式） | `pending_images`, `pending_description` |
| `admin_users` | Dashboard 登入帳號 | `username` (unique), `employee_id` (unique), `display_name`, `hashed_password` |

**expenses 表 — Sprint 2 新增欄位：**

| 欄位 | 型別 | 說明 |
|------|------|------|
| `user_description` | TEXT \| null | 使用者傳送的文字備註（批次送出時附帶） |
| `image_count` | INTEGER | 本筆報帳包含的照片數量（預設 1） |
| `voucher_categories` | TEXT \| null | 憑證類別去重清單（JSON 陣列字串，如 `["INVOICE","RECEIPT"]`） |

**expense_images 表（Sprint 2 新增）：**

| 欄位 | 型別 | 說明 |
|------|------|------|
| `id` | UUID (PK) | 子圖主鍵 |
| `expense_id` | UUID (FK) | 關聯 expenses（CASCADE DELETE） |
| `image_url` | TEXT | 圖片路徑 |
| `is_voucher` | BOOLEAN | 是否為有效憑證（Gemini 判定） |
| `voucher_category` | TEXT \| null | 憑證類別（INVOICE/RECEIPT/LABOR_SERVICE/TRANSPORTATION/CREDIT_NOTE） |
| `sequence_order` | INTEGER | 圖片順序（從 0 開始） |
| `ocr_result` | TEXT \| null | OCR 結果（JSON 字串） |
| `created_at` | TIMESTAMP | 建立時間 |

**user_states 表 — Sprint 2 新增欄位：**

| 欄位 | 型別 | 說明 |
|------|------|------|
| `pending_images` | TEXT | 待送出圖片路徑清單（JSON 陣列，預設 `'[]'`） |
| `pending_description` | TEXT | 待送出文字備註（預設 `''`） |

> **注意**：`step` 欄位在 Sprint 2 已統一遷移為 `COLLECTING`（舊值 `WAITING_PHOTO` 透過 data migration 轉換，不再使用）。

**Expense Status Enum：**
- `PENDING` - 待審核（有 total_amount）
- `APPROVED` - 已通過
- `REJECTED` - 已退件
- `NEEDS_MANUAL_REVIEW` - 需人工檢視（total_amount 為 null 或 OCR 全部失敗）

**OCR 憑證分類（Sprint 2 新增）：**
- `INVOICE` - 統一發票（含統編/課稅別）
- `RECEIPT` - 收據/免統發票
- `LABOR_SERVICE` - 勞務報酬單（含身分證/實領金額）
- `TRANSPORTATION` - 交通費（含起訖點）
- `CREDIT_NOTE` - 退貨折讓單（`total_amount` 強制為負數）

---

## 6. 部署架構

### 開發環境
```
本地 FastAPI (uvicorn)
  ↓
本地 PostgreSQL (Docker Compose)
  ↓
ngrok 或 localtunnel (Webhook 轉發)
```

### 生產環境（規劃中）
```
Cloud VM (GCP / AWS)
  ├─ FastAPI (Gunicorn + Uvicorn)
  ├─ PostgreSQL (Managed Service)
  ├─ Nginx (Reverse Proxy + SSL)
  └─ Vue 3 SPA (Static Hosting)
```

---

## 7. 安全性考量

| 項目 | 實作方式 |
|------|---------|
| **LINE Webhook 驗證** | X-Line-Signature 檢查 |
| **API Key 管理** | `.env` + `pydantic-settings` |
| **SQL Injection 防護** | SQLAlchemy ORM 參數化查詢 |
| **CORS 設定** | FastAPI CORSMiddleware 白名單 |
| **敏感資料隱藏** | `.env` 不納入版控 |
| **Dashboard 登入** | JWT (HS256) + bcrypt 密碼雜湊，`admin_users` 表儲存帳號 |
| **前端 Token 管理** | localStorage + Axios interceptor 自動注入 Bearer Token；401 自動跳轉登入頁 |

---

## 8. 未來規劃

### Phase 2 功能
- [ ] 使用者權限系統（Admin / Viewer）
- [ ] Email 通知（審核結果）
- [ ] 批次匯出報表（Excel / CSV）
- [ ] LINE Rich Menu 整合
- [ ] 發票重複上傳檢查

### Phase 3 功能
- [ ] 多專案支援（專案代碼綁定）
- [ ] 預算控管與警示
- [ ] 會計系統 API 整合
- [ ] 行動版 Dashboard（RWD）

---

## 9. 相關文件

| 文件 | 路徑 |
|------|------|
| 開發規範 | `CLAUDE.md` |
| 共用規則 | `.knowledge/company-rules.md` |
| 團隊流程 | `.knowledge/team-workflow.md` |
| 踩坑紀錄 | `.knowledge/postmortem-log.md` |
| 文件索引 | `.knowledge/file-index.md` |
| API 文件 | `/docs` (FastAPI 自動生成) |

---

## 10. 快速開始

### 環境設定
```bash
# 1. 複製環境變數範本
cp .env.example .env

# 2. 啟動 PostgreSQL
docker-compose up -d

# 3. 安裝依賴
pip install -r requirements.txt

# 4. 執行資料庫遷移
alembic upgrade head

# 5. 啟動後端
uvicorn main:app --reload

# 6. 啟動前端（開發模式）
cd frontend && npm run dev
```

### 測試 API
```bash
# 健康檢查
curl http://localhost:8000/health

# 查詢報帳清單
curl http://localhost:8000/api/v1/expenses
```

---

**維護者**: product-manager Agent
**最後審查**: 2026-04-08
