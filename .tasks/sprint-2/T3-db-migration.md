# DB Migration

| 欄位 | 值 |
|------|-----|
| ID | T3 |
| 專案 | AcctAssist |
| Sprint | Sprint 2 |
| 指派給 | backend-dev |
| 優先級 | P0 |
| 狀態 | done |
| 依賴 | — |
| 預估 | 2h |
| 建立時間 | 2026-04-11T00:00:00.000Z |

---

## 任務描述

撰寫 3 個 Alembic migration 並同步更新 ORM model。

> ⚠️ 最新既有 migration revision：`j7c8d9e0f1a2`（all_new revision 為起點）

### Migration (k) — `k8d9e0f1a2b3_add_expense_images_and_batch_fields`
- `down_revision = 'j7c8d9e0f1a2'`
- **建立 `expense_images` 表**：
  - `id` UUID PK
  - `expense_id` FK → expenses.id（CASCADE DELETE）
  - `image_url` str
  - `is_voucher` bool
  - `voucher_category` str nullable（INVOICE/RECEIPT/LABOR_SERVICE/TRANSPORTATION/CREDIT_NOTE）
  - `sequence_order` int
  - `ocr_result` JSON nullable
  - `created_at` datetime
- **`expenses` 表新增欄位**：
  - `user_description` TEXT nullable
  - `image_count` INT default 1
  - `voucher_categories` TEXT nullable（JSON array 格式）

### Migration (l) — `l9e0f1a2b3c4_add_user_states_pending_fields`
- `down_revision = 'k8d9e0f1a2b3'`
- **`user_states` 表新增欄位**：
  - `pending_images` TEXT default `'[]'`（JSON array）
  - `pending_description` TEXT default `''`

### Migration (m) — `m0f1a2b3c4d5_migrate_waiting_photo_to_collecting`
- `down_revision = 'l9e0f1a2b3c4'`
- **Data migration**：`UPDATE user_states SET step='COLLECTING' WHERE step='WAITING_PHOTO'`
- downgrade：`UPDATE user_states SET step='WAITING_PHOTO' WHERE step='COLLECTING'`

### ORM 更新
- **新建** `models/expense_image.py`：ExpenseImage ORM
- **修改** `models/expense.py`：新增 3 欄位 + `images` relationship
- **修改** `models/user_state.py`：新增 `pending_images`、`pending_description`

## 驗收標準

- [ ] `alembic upgrade head` 執行成功（無錯誤）
- [ ] `expense_images` 表存在，FK/CASCADE DELETE 正確
- [ ] `expenses` 表含新欄位：`user_description`、`image_count`、`voucher_categories`
- [ ] `user_states` 表含新欄位：`pending_images`、`pending_description`
- [ ] 既有 `WAITING_PHOTO` 記錄已轉換為 `COLLECTING`
- [ ] `alembic downgrade -1` 可成功回滾（所有 3 個 migration）
- [ ] ORM model 與 DB schema 同步

---

## 事件紀錄

### 2026-04-11T00:00:00.000Z — 建立任務（assigned）
由 L1（project-lead）透過 /task-delegation 建立
✅ 可立即開始（無前置依賴）

### 2026-04-10T18:36:39.000Z — 開始執行（in_progress）
由 L1（project-lead）委派給 backend-dev，第一波並行啟動

### 2026-04-10T18:36:39.000Z — 完成交付（in_review）
3 個 Alembic migration（k/l/m）+ ORM 更新完成

### 2026-04-10T18:36:39.000Z — L1 審核通過（done）
審核者：project-lead。Migration chain 正確、FK/CASCADE 完整、ORM 同步、downgrade 全實作。小缺項：user_state.py 使用 String 而非 Text，行為相同可接受。
撰寫 3 個 Alembic migration（k/l/m）、新建 models/expense_image.py、更新 models/expense.py 與 models/user_state.py，請 L1 審查。
