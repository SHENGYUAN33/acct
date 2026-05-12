# 資料模型規範

> 版本: v1.0 | Sprint 1 | 最後更新: 2026-04-08

## 概述

AcctAssist 使用 PostgreSQL 16 + SQLAlchemy 2.0 ORM。
三張核心資料表：`users`、`expenses`、`user_states`，外加一個 DB sequence。

---

## 資料表定義

### users

| 欄位 | 型別 | 約束 | 說明 |
|------|------|------|------|
| `id` | UUID | PK, default uuid4 | 系統主鍵 |
| `line_user_id` | VARCHAR | UNIQUE, NOT NULL, indexed | LINE 平台識別碼 |
| `name` | VARCHAR | nullable | LINE 顯示名稱 |
| `real_name` | VARCHAR | nullable | 員工真實姓名（實名制） |
| `department` | VARCHAR | nullable | 部門（由對話選擇寫入） |
| `created_at` | TIMESTAMP | NOT NULL, default now() | 首次登錄時間 |

**索引**：`line_user_id`（唯一索引）

---

### expenses

**系統欄位（程式自動填寫）：**

| 欄位 | 型別 | 約束 | 說明 |
|------|------|------|------|
| `id` | UUID | PK, default uuid4 | 系統主鍵 |
| `user_id` | UUID | FK → users.id, nullable | 關聯使用者 |
| `serial_number` | VARCHAR | NOT NULL, UNIQUE | 案件流水號（EXP-YYYYMM-NNNN） |
| `image_url` | JSON | NOT NULL, default [] | 憑證圖片路徑陣列 |
| `item_image_url` | JSON | NOT NULL, default [] | 品項圖片路徑陣列 |
| `uploader_name` | VARCHAR | nullable | 上傳者 LINE 顯示名稱 |
| `uploader_dept` | VARCHAR | nullable | 上傳當下選擇的部門 |
| `upload_date` | TIMESTAMP | NOT NULL, default now() | 上傳時間戳 |
| `status` | ENUM | NOT NULL, default PENDING | 審核狀態 |
| `reject_reason` | TEXT | nullable | 退件原因 |
| `created_at` | TIMESTAMP | NOT NULL, default now() | 建立時間 |
| `updated_at` | TIMESTAMP | NOT NULL, onupdate now() | 最後更新時間 |

**OCR 解析欄位（Gemini 辨識結果，可能為 null）：**

| 欄位 | 型別 | 說明 |
|------|------|------|
| `submitter_name` | VARCHAR | 發票上的申請人姓名 |
| `submitter_dept` | VARCHAR | 申請人組別（OCR / 使用者填寫） |
| `item_description` | TEXT | 品項描述 |
| `expense_date` | DATE | 消費日期 |
| `invoice_number` | VARCHAR | 發票號碼 |
| `total_amount` | DECIMAL(12,2) | 含稅總金額 ← **狀態判定關鍵欄位** |
| `net_amount` | DECIMAL(12,2) | 未稅金額 |
| `tax_amount` | DECIMAL(12,2) | 稅額 |
| `seller_tax_id` | VARCHAR | 賣方統一編號（8碼） |
| `seller_name` | VARCHAR | 賣方名稱 |

**Status Enum 定義：**

| 值 | 說明 | 進入條件 |
|----|------|---------|
| `PENDING` | 待審核 | OCR 成功且 total_amount 有值 |
| `APPROVED` | 已通過 | 財務審核通過 |
| `REJECTED` | 已退件 | 財務退件（需填原因） |
| `NEEDS_MANUAL_REVIEW` | 需人工檢視 | OCR 失敗或 total_amount 為 null |

**索引**：`user_id`（FK 索引）、`status`（篩選用）、`upload_date`（排序/篩選用）

---

### user_states

| 欄位 | 型別 | 約束 | 說明 |
|------|------|------|------|
| `line_user_id` | VARCHAR | PK | LINE 使用者識別碼（非 FK，輕耦合） |
| `step` | VARCHAR | NOT NULL | 對話步驟（目前僅 `WAITING_PHOTO`） |
| `dept` | VARCHAR | nullable | 此次對話選擇的部門 |
| `updated_at` | TIMESTAMP | NOT NULL, onupdate now() | 最後更新時間 |

---

## 案件流水號（Serial Number）

**用途**：`_generate_serial_number()` 查詢當月已有幾筆，加 1 產生流水號。
**格式**：`EXP-{YYYYMM}-{4位數字}` 例：`EXP-202604-0001`
**特性**：每月從 0001 重新計算（跨月重置）；`serial_number` 欄位有 UNIQUE constraint，極低機率重複時由 DB 層拋 IntegrityError。
**注意**：已移除舊版 PostgreSQL sequence（`expense_serial_seq`），測試環境使用 SQLite 不再需要 mock `_generate_serial_number`。

---

## 關聯圖

```
users ──────────── expenses
(id) 1           * (user_id)

user_states（獨立，以 line_user_id 字串關聯）
```

---

## Alembic 遷移歷史

| Migration ID | 說明 |
|-------------|------|
| `24e8bd9d46f1` | 建立 users + expenses 基礎表 |
| `8bd1dbb125a7` | 新增 OCR 解析欄位（金額、稅號等） |
| `a3f2c1d0e5b8` | 新增 user_states 表 |

> 執行遷移：`alembic upgrade head`

---

## 注意事項

1. `image_url` / `item_image_url` 儲存為 JSON 陣列（相對路徑 `uploads/xxx.jpg`），前端顯示時需加 `BACKEND_BASE_URL` 前綴
2. `serial_number` 依賴 PostgreSQL sequence，**測試環境若使用 SQLite 需 mock `_generate_serial_number()`**
3. `user_states` 使用 `line_user_id` 作為 PK（字串），非 FK，避免 users 刪除時的 cascade 問題
4. `total_amount` 為 `DECIMAL(12,2)`，前端傳入時須確保格式正確（不可傳字串 `"1200.00"`）
