# 資料模型規範

> 版本: v2.0 | Sprint 3 | 最後更新: 2026-04-17

## 概述

AcctAssist 使用 PostgreSQL 16 + SQLAlchemy 2.0 ORM。
五張核心資料表：`users`、`expenses`、`expense_images`、`user_states`、`admin_users`。

---

## 資料表定義

### users

| 欄位 | 型別 | 約束 | 說明 |
|------|------|------|------|
| `id` | UUID | PK, default uuid4 | 系統主鍵 |
| `line_user_id` | VARCHAR(64) | UNIQUE, NOT NULL, indexed | LINE 平台識別碼 |
| `name` | VARCHAR(128) | nullable | LINE 顯示名稱 |
| `real_name` | VARCHAR(128) | nullable | 員工真實姓名（實名制綁定） |
| `employee_id` | VARCHAR(64) | nullable | 員工編號（選配） |
| `department` | VARCHAR(128) | nullable | 部門（**NULL = 尚未完成 Onboarding**） |
| `created_at` | TIMESTAMPTZ | NOT NULL, default now() | 首次登錄時間 |

**索引**：`line_user_id`（唯一索引）

---

### expenses

**系統欄位（程式自動填寫）：**

| 欄位 | 型別 | 約束 | 說明 |
|------|------|------|------|
| `id` | UUID | PK, default uuid4 | 系統主鍵 |
| `user_id` | UUID | FK → users.id (SET NULL), nullable | 關聯使用者 |
| `serial_number` | VARCHAR(32) | NOT NULL, UNIQUE | 案件流水號（EXP-YYYYMM-NNNN，月重置） |
| `image_url` | VARCHAR(512)[] | NOT NULL, default {} | 財務憑證圖片路徑陣列 |
| `item_image_url` | VARCHAR(512)[] | NOT NULL, default {} | 物品影像路徑陣列（非憑證） |
| `uploader_name` | VARCHAR(128) | nullable | 上傳者 LINE 顯示名稱 |
| `uploader_dept` | VARCHAR(64) | nullable | 上傳當下選擇的部門 |
| `upload_date` | TIMESTAMPTZ | NOT NULL, default now() | 上傳時間戳 |
| `status` | ENUM | NOT NULL, default PENDING | 審核狀態（見 Status Enum） |
| `reject_reason` | TEXT | nullable | 退件原因 |
| `trigger_by` | VARCHAR(32) | nullable | 觸發來源（`manual_button` / `auto_split` / null=舊資料） |
| `created_at` | TIMESTAMPTZ | NOT NULL, default now() | 建立時間 |
| `updated_at` | TIMESTAMPTZ | NOT NULL, onupdate now() | 最後更新時間 |

**OCR 解析欄位（Gemini 辨識結果，可能為 null）：**

| 欄位 | 型別 | 說明 |
|------|------|------|
| `submitter_name` | VARCHAR(128) | 發票上的申請人姓名 |
| `submitter_dept` | VARCHAR(64) | 申請人組別（OCR / 使用者填寫） |
| `item_description` | TEXT | 品項描述 |
| `expense_date` | DATE | 消費日期 |
| `invoice_number` | VARCHAR(64) | 發票號碼（主憑證） |
| `total_amount` | DECIMAL(12,2) | 含稅總金額 ← **狀態判定關鍵欄位**（批次模式 = 所有財務憑證加總） |
| `net_amount` | DECIMAL(12,2) | 未稅金額 |
| `tax_amount` | DECIMAL(12,2) | 稅額 |
| `seller_tax_id` | VARCHAR(16) | 賣方統一編號（8碼） |
| `seller_name` | VARCHAR(128) | 賣方名稱 |

**Sprint 2 新增欄位：**

| 欄位 | 型別 | 說明 |
|------|------|------|
| `user_description` | TEXT | 使用者傳送的文字備註（批次送出時附帶） |
| `image_count` | INTEGER | 本筆報帳包含的照片數量（預設 1） |
| `voucher_categories` | TEXT | 憑證類別去重清單（JSON 陣列字串，如 `["INVOICE","RECEIPT"]`） |

**Sprint 3 新增欄位：**

| 欄位 | 型別 | 說明 |
|------|------|------|
| `voucher_subtypes` | TEXT | 憑證子類型去重清單（JSON 陣列字串，如 `["HSR_TICKET","FUEL"]`） |
| `expense_categories` | TEXT | 費用科目去重清單（JSON 陣列字串，儲存中文名稱，如 `["勞-餐飲費","勞-交通費-油資"]`） |

**Status Enum 定義：**

| 值 | 說明 | 進入條件 |
|----|------|---------|
| `PENDING` | 待審核 | OCR 成功且 total_amount 有值；或待退貨流程完成後 |
| `APPROVED` | 已核准 | 管理員審核通過 |
| `REJECTED` | 已作廢 | 管理員退回，該筆作廢，流程結束 |
| `NEEDS_MANUAL_REVIEW` | 未審核（需特別注意） | OCR 失敗或 total_amount 為 null |
| `WAITING_RETURN` | 待退貨 | 使用者標記待退貨 |
| `REPLACED_VOID` | 已作廢（沖銷） | 換單/折讓三種情境下的舊交易 |

**索引**：`user_id`（FK 索引）、`status`（篩選用）、`upload_date`（排序/篩選用）

---

### expense_images（Sprint 2 新增）

批次報帳的各張子圖，每筆 Expense 對應 N 筆 ExpenseImage（CASCADE DELETE）。

| 欄位 | 型別 | 約束 | 說明 |
|------|------|------|------|
| `id` | UUID | PK, default gen_random_uuid() | 子圖主鍵 |
| `expense_id` | UUID | FK → expenses.id (CASCADE DELETE), indexed | 關聯 Expense |
| `image_url` | VARCHAR(512) | NOT NULL | 圖片路徑（uploads/{uuid}.jpg） |
| `is_voucher` | BOOLEAN | NOT NULL, default false | 是否為有效財務憑證（Gemini 判定） |
| `voucher_category` | VARCHAR(64) | nullable | 憑證頂層類別（INVOICE/RECEIPT/LABOR_SERVICE/TRANSPORTATION/CREDIT_NOTE） |
| `voucher_subtype` | VARCHAR(64) | nullable | 憑證子類型（HSR_TICKET/FUEL/EXEMPT_INVOICE 等，Sprint 3 新增） |
| `expense_category` | VARCHAR(64) | nullable | 費用科目中文名稱（平面清單，如「餐飲費」「油資」，對應 config/expense_categories.json） |
| `sequence_order` | INTEGER | NOT NULL, default 1 | 圖片上傳順序（從 1 開始） |
| `ocr_result` | TEXT | nullable | OCR 結果（JSON 字串，VoucherOCRResult 序列化） |
| `ocr_confidence` | NUMERIC(4,3) | nullable | Gemini overall_confidence 分數（0.000–1.000，Sprint 3 新增） |
| `created_at` | TIMESTAMPTZ | NOT NULL, default now() | 建立時間 |

---

### user_states

LINE 對話狀態機，以 `line_user_id` 為主鍵（非 FK，避免 cascade 問題）。

| 欄位 | 型別 | 約束 | 說明 |
|------|------|------|------|
| `line_user_id` | VARCHAR(64) | PK | LINE 使用者識別碼 |
| `step` | VARCHAR(128) | NOT NULL | 對話步驟（見下方有效值） |
| `dept` | VARCHAR(64) | nullable | 此次對話記憶的部門 |
| `pending_images` | TEXT | NOT NULL, default '[]' | 待送出圖片清單（JSON 陣列，Sprint 3 格式含 timestamp/message_id） |
| `pending_description` | TEXT | NOT NULL, default '' | 待送出文字備註（Sprint 2 新增） |
| `updated_at` | TIMESTAMPTZ | NOT NULL, onupdate now() | 最後更新時間 |

**step 有效值：**

| 值 | 說明 |
|----|------|
| `COLLECTING` | 正常批次收集模式（Sprint 2 起，取代舊 `WAITING_PHOTO`） |
| `BINDING_REAL_NAME` | 進行中的實名綁定（輸入真實姓名等待回覆） |
| `REUPLOADING_{expense_id}` | 補件模式（等待使用者重新上傳指定 expense_id 的圖片） |

> ⚠️ 舊值 `WAITING_PHOTO` 已透過 Migration `m0f1a2b3c4d5` data migration 全數轉為 `COLLECTING`，不再使用。

**pending_images JSON 格式（Sprint 3 升級）：**

```json
// Sprint 3 格式（含 metadata）
[
  {"path": "uploads/abc.jpg", "timestamp": 1714000000000, "message_id": "M123"},
  {"path": "uploads/def.jpg", "timestamp": 1714000005000, "message_id": "M124"}
]
// Sprint 2 格式（純字串，_parse_buffer 向後相容，timestamp=0 兜底）
["uploads/abc.jpg", "uploads/def.jpg"]
```

---

### admin_users（Sprint 1 後期新增）

Dashboard 管理員帳號，獨立於 LINE 使用者系統。

| 欄位 | 型別 | 約束 | 說明 |
|------|------|------|------|
| `id` | INTEGER | PK, autoincrement | 系統主鍵 |
| `username` | VARCHAR | UNIQUE, NOT NULL | 登入帳號 |
| `hashed_password` | VARCHAR | NOT NULL | bcrypt 雜湊密碼 |
| `display_name` | VARCHAR | nullable | 顯示姓名（右上角顯示用） |
| `employee_id` | VARCHAR | UNIQUE, nullable | 員工編號（選填，建立帳號時設定） |
| `created_at` | TIMESTAMPTZ | NOT NULL, default now() | 建立時間 |

---

## 案件流水號（Serial Number）

**用途**：`_generate_serial_number()` 查詢當月最大序號加 1 產生流水號。
**格式**：`EXP-{YYYYMM}-{4位數字}` 例：`EXP-202604-0001`
**特性**：每月重置（跨月從 0001 開始）；使用 `MAX(serial_number)` 取最大值（Sprint 2 修正，對已刪除記錄免疫）。
**防碰撞**：DB 層 UNIQUE constraint + 最多 5 次重試（Sprint 2 修正 Race Condition 問題）。

---

## 關聯圖

```
users ──────────── expenses ──────────── expense_images
(id) 1           * (user_id)    1      * (expense_id, CASCADE)

admin_users（獨立，管理員帳號）

user_states（獨立，以 line_user_id 字串關聯 users，不設 FK）
```

---

## Alembic 遷移歷史

| Migration ID | down_revision | 說明 |
|-------------|--------------|------|
| `24e8bd9d46f1` | — | 建立 users + expenses 基礎表 |
| `8bd1dbb125a7` | `24e8bd9d46f1` | 新增 OCR 解析欄位（金額、稅號等） |
| `a3f2c1d0e5b8` | `8bd1dbb125a7` | 新增 user_states 表 |
| `b7c3e2f1a4d9` | `a3f2c1d0e5b8` | 新增 item_image_url + image_url 改 nullable |
| `d4e5f6a7b8c9` | `b7c3e2f1a4d9` | image_url / item_image_url 改為 ARRAY |
| `e1f2a3b4c5d6` | `d4e5f6a7b8c9` | 擴充 user_states.step 欄位長度 |
| `f3a4b5c6d7e8` | `e1f2a3b4c5d6` | users 新增 real_name, employee_id |
| `g4b5c6d7e8f9` | `f3a4b5c6d7e8` | expenses 新增 serial_number |
| `h5c6d7e8f9a0` | `g4b5c6d7e8f9` | 建立 expense_serial_seq（後續廢棄） |
| `i6d7e8f9a0b1` | `h5c6d7e8f9a0` | 建立 admin_users 表（含 employee_id, display_name） |
| `j7c8d9e0f1a2` | `i6d7e8f9a0b1` | ExpenseStatus 新增 SUPPLEMENTED 值 |
| `k8d9e0f1a2b3` | `j7c8d9e0f1a2` | 建立 expense_images 表；expenses 新增 3 欄位 |
| `l9e0f1a2b3c4` | `k8d9e0f1a2b3` | user_states 新增 pending_images + pending_description |
| `m0f1a2b3c4d5` | `l9e0f1a2b3c4` | Data migration：WAITING_PHOTO → COLLECTING |
| `n1g2h3i4j5k6` | `m0f1a2b3c4d5` | expenses 新增 trigger_by |
| `o2p3q4r5s6t7` | `n1g2h3i4j5k6` | expense_images 新增 voucher_subtype, expense_category, ocr_confidence；expenses 新增 voucher_subtypes, expense_categories |

> 執行遷移：`alembic upgrade head`

---

## 注意事項

1. `image_url` / `item_image_url` 儲存為 PostgreSQL ARRAY（相對路徑 `uploads/xxx.jpg`），前端顯示時需加 `BACKEND_BASE_URL` 前綴
2. `serial_number` 由 `_generate_serial_number()` 使用 `MAX` 查詢產生，測試環境中舊版需要 mock，新版（Sprint 2 修正後）使用 SQLite 時仍需 mock（SQLite 不支援 MAX 對 VARCHAR 序號的比較格式）
3. `user_states` 使用 `line_user_id` 作為 PK（字串），非 FK，避免 users 刪除時的 cascade 問題
4. `total_amount` 在批次報帳模式下為所有 `is_voucher=True` 且有金額的子圖加總；`CREDIT_NOTE` 的 total_amount 強制為負數，加總時自動扣除
5. `trigger_by = "auto_split"` 時，Expense 由 Sprint 3 自動切割機制建立；`"manual_button"` 為使用者主動按「確認送出」
6. `ENABLE_AUTO_SPLIT=true` 時 **必須單 Worker 啟動**（`uvicorn --workers 1`），見 postmortem #013
7. Alembic migration `k~o` 全部採用冪等寫法（`CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`），可在已部分建立的環境重跑不報錯，見 postmortem #011
