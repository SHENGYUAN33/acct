# Work Log — AcctAssist

> **用途**：記錄每日工作內容、完成任務、遇到的問題
> **更新規則**：每日工作結束後補充當天記錄

---

## 2026-04-14

**負責人**：tech-lead (L1)

### 完成的任務

#### 1. Sprint 3 架構規劃（SOP Plan + Plan Mode）
- 讀取 `proposal/sprint2-dev-plan.md`（Sprint 2 已封版，確認本次為 Sprint 3）
- 讀取 `.knowledge/postmortem-log.md`，標記 5 條相關地雷（#003 #004 #007 #011 #012）
- 確認三項架構決策：單 Worker / 新 buffer 格式 / 方案 A（OCR 先跑再切割）
- 使用 Plan Mode 產出完整計畫至 `~/.claude/plans/woolly-sprouting-lemur.md`
- 任務拆解：10 個任務（T1–T10），並行策略確認

#### 2. Sprint 3 實作 — LINE Webhook 雙軌觸發機制（T1–T10 全部完成）

**T1 — Config 擴充**
- `core/config.py`：新增 `enable_auto_split: bool = False`、`auto_split_debounce_seconds: int = 60`
- `.env.example`：新增 `ENABLE_AUTO_SPLIT=false`、`AUTO_SPLIT_DEBOUNCE_SECONDS=60`

**T2 — DB Migration + ORM**
- 新建 `alembic/versions/n1g2h3i4j5k6_add_trigger_by_to_expenses.py`（down_revision: m0f1a2b3c4d5）
- `models/expense.py`：新增 `trigger_by: Mapped[str | None]`（VARCHAR 32）

**T3 — Pydantic Schema**
- `schemas/expense.py`：`ExpenseRead` 新增 `trigger_by: str | None = None`

**T4 — expense_service 擴充**
- `services/expense_service.py`：`create_batch_expense()` 新增 `trigger_by: str | None = None` 參數（向後相容，預設 None）

**T5 — Timer Manager（新建）**
- `services/auto_split_timer.py`：per-user `asyncio.create_task()` 滑動視窗 Timer
- 提供 `schedule()` / `cancel()` / `active_count()` 三個介面

**T6 — Auto-Split Service（新建）**
- `services/auto_split_service.py`：
  - `_parse_buffer()`：新舊格式解析（新格式含 timestamp/message_id，舊格式 timestamp=0 兜底）
  - `multi_split_logic()`：純函式，依 `is_voucher=True` 作為斷點切割群組
  - `auto_split_process()`：Timer callback，序列 OCR → 切割 → 多筆 `create_batch_expense`

**T7 — Webhook 重構（最小侵入 3 處）**
- `routers/webhook.py`：
  1. `_process_batch()` 新增 `trigger_by="manual_button"` 參數
  2. `confirm_submit` handler 頂部插入 `auto_split_timer.cancel()`（Priority Event）
  3. Image 收集區塊：buffer 升級為新格式（含 timestamp/message_id）+ 排程 Timer

**T8 — 前端 Badge 顯示**
- `frontend/src/stores/expenseStore.js`：`mapExpense()` 新增 `trigger_by` 欄位
- `frontend/src/components/AuditModal.vue`：案件編號旁顯示 `⏱ 自動送出` / `✅ 手動送出` badge
- `frontend/src/components/ExpenseTable.vue`：案件編號欄位加上 `⏱` 小標記

**T9 — 測試套件**
- `tests/conftest.py`：expenses 表新增 `trigger_by` 欄位、settings mock 新增 auto_split 相關設定
- `tests/unit/test_auto_split.py`（新建）：`multi_split_logic` 7 種場景、`_parse_buffer` 5 種格式、Timer 行為 5 個測試
- `tests/integration/test_auto_split_flow.py`（新建）：confirm_submit 取消 Timer、trigger_by 欄位記錄、多筆切割、buffer 新格式驗證

**T10 — 文件更新**
- `.knowledge/postmortem-log.md`：新增 #013「asyncio Timer 僅支援單 Worker」(monitoring)

#### 3. 問題排查 — 機制二未觸發
- **現象**：用戶回報上傳照片後機制二未啟動
- **根因**：`.env` 中 `ENABLE_AUTO_SPLIT=false`（僅有 `.env.example` 有該設定，`.env` 未手動補入）
- **處理**：說明 `.env` vs `.env.example` 差異；直接修改 `.env` 為 `ENABLE_AUTO_SPLIT=true`、`AUTO_SPLIT_DEBOUNCE_SECONDS=15`（測試用）

### 遇到的問題

#### 問題 1：.env 與 .env.example 未同步
**現象**：新增功能開關後，`.env.example` 已更新，但用戶的 `.env` 未同步，導致功能開關仍為預設值（False）

**處理方式**：每次在 `.env.example` 新增設定後，應提醒用戶手動將對應行貼入 `.env`，或由 tech-lead 直接修改 `.env`（含預設安全值）

### 明日待辦

- [ ] 執行 `alembic upgrade head` 確認 `n1g2h3i4j5k6` migration 成功跑過
- [ ] 實機測試：傳照片等 15 秒 → 確認 Dashboard 出現 `trigger_by=auto_split` 筆數
- [ ] 實機測試：傳照片 → 15 秒內按「確認送出」→ 確認只有 1 筆且 `trigger_by=manual_button`
- [ ] 跑測試套件 `pytest tests/unit/test_auto_split.py tests/integration/test_auto_split_flow.py -v`
- [ ] 測試完成後將 `.env` 的 debounce 改回 60 秒

---

## 2026-04-10

**負責人**：product-manager (PM / L1)

### 完成的任務

#### 1. LINE Rich Menu 亂碼修正
- **問題根因**：`_build_rich_menu_image()` 使用 PIL 動態生成圖片 + 系統中文字型，字型載入失敗時 fallback 到 `ImageFont.load_default()`（不支援中文），導致選單文字顯示方框
- **修正方式（B 方案）**：改為讀取靜態設計圖 `static/rich_menu.jpg`，完全移除字型依賴
- **關鍵變更**：
  - `services/line_service.py`：移除 `_FONT_CANDIDATES`、`_load_font()`、PIL 生成邏輯（共約 70 行）
  - `_build_rich_menu_image()` 改為 `return _RICH_MENU_IMAGE_PATH.read_bytes()`（3 行）
  - `_RICH_MENU_NAME` 由 `v2` → `v3`，觸發伺服器重啟時自動清除舊選單並重建
  - `RichMenuSize` 由 1686×843 → **1200×810**（配合設計圖實際尺寸）
  - `RichMenuBounds` 分割點由 `W//2`（600px）→ **595px**（配合設計圖實際分割線位置）

#### 2. 重複發票偵測回覆邏輯修正
- **問題根因**：`needs_review` 變數同時承載「OCR 失敗」與「重複發票」兩種情境，導致 OCR 成功但偵測到重複時，仍顯示「無法辨識圖片」的錯誤訊息
- **修正方式**：拆分為兩個獨立變數
  - `ocr_failed`：OCR 真正失敗或金額為 null
  - `duplicate_serial`：重複發票號碼（原始單號）
  - `needs_manual_review = ocr_failed or (duplicate_serial is not None)`
- **回覆邏輯**：
  - OCR 失敗 → 顯示「無法辨識」訊息
  - OCR 成功 → 顯示完整辨識結果（賣方、金額、日期、發票號碼等）
  - 有重複 → 任何情境皆在訊息末尾附加 `⚠️ 此圖片已有重複提交紀錄（單號：EXP-XXXXXX），以標記人工審核`
- **補件流程（`REUPLOADING_`）**：完整保留，不受影響，不觸發重複偵測
- **關鍵變更**：`routers/webhook.py` 第 240–312 行

#### 3. Serial Number UniqueViolation 修復
- **問題根因（Race Condition）**：`_generate_serial_number()` 用 `COUNT(*)` 查當月筆數 +1 產生序號，兩個請求同時查到相同 count 時產生重複序號，DB commit 時觸發 `uq_expenses_serial_number` unique constraint 錯誤
- **額外缺陷**：若有記錄被刪除（如 0003 刪除後 COUNT=4），下一筆仍嘗試插入已存在的 0005
- **修正方式（兩層防護）**：
  1. `COUNT` → `MAX`：改查當月 `serial_number` 最大值，對刪除記錄免疫
  2. 重試機制：`create_expense` / `create_expense_manual` 的 commit 加 `try-except IntegrityError`，碰撞時 rollback 並重新產生序號，最多重試 5 次；其他 IntegrityError 仍直接拋出
- **關鍵變更**：`services/expense_service.py`
  - 新增 `from sqlalchemy.exc import IntegrityError`
  - `_generate_serial_number()` 第 22–25 行：`func.count()` 改為 `func.max(Expense.serial_number)` + 序號解析邏輯
  - `create_expense()` / `create_expense_manual()`：INSERT 包裝在 `for _attempt in range(5)` 重試迴圈中

---

### 明日待辦

- [ ] 重啟伺服器，確認 Rich Menu 成功重建（觀察 log：`Rich Menu 建立完成：rich_menu_id=xxx`）
- [ ] 在 LINE 實機測試點擊左右區域是否正確觸發「我要報帳」與「查詢進度」
- [ ] 測試重複發票上傳情境，確認 OCR 成功時顯示完整辨識結果 + 末尾附加重複警告
- [ ] 壓測 serial number 並發情境（同時送出 2+ 張圖片），確認不再出現 UniqueViolation

---

#### 4. Dashboard 登入系統實作（帳號管理）
- **需求**：Dashboard 需要登入機制，帳號資料存於 PostgreSQL，登入後顯示姓名於右上角
- **新增 model**：`models/admin_user.py` 加入 `employee_id`（唯一索引）、`display_name` 欄位
- **新增 migration**：`alembic/versions/i6d7e8f9a0b1_...py` — CREATE TABLE `admin_users`（含 username、hashed_password、employee_id、display_name、created_at）
- **後端 `routers/auth.py`**：
  - `RegisterRequest` 新增 `display_name`、`employee_id` 欄位（選填）
  - 工號重複檢查邏輯
  - Login 回應新增 `display_name`、`employee_id`、`username` 欄位
- **前端**：
  - `stores/authStore.js`：新增 `displayName`、`employeeId` state，存 localStorage
  - `api/authApi.js`：`register()` 帶上 `display_name`、`employee_id`
  - `components/AppHeader.vue`：右上角改顯示 `authStore.displayName`（工號括號顯示）
  - `views/LoginView.vue`：建立帳號表單加入姓名、工號欄位（必填）

### 遇到的問題

#### 問題 4：Migration 寫法錯誤導致 pgAdmin 看不到 admin_users 表
**現象**：`admin_users` 在 `models/admin_user.py` 為新增檔案（從未有對應 migration），`i6d7e8f9a0b1` 初版寫成 `add_column` 對既有表加欄位，但表根本不存在，導致 `alembic upgrade head` 無報錯但表沒出現

**處理方式**：修正 migration 改為 `create_table`，完整建立 `admin_users` 表含所有欄位與 unique constraint / index

#### 5. 補件成功 LINE 回覆模板更新 + 新增「已補件」狀態
- **需求**：補件成功的 LINE 回覆要與原始報帳回覆格式一致（完整 OCR 欄位）；前後端新增 `SUPPLEMENTED`（已補件）狀態
- **`models/expense.py`**：`ExpenseStatus` 新增 `SUPPLEMENTED = "SUPPLEMENTED"`
- **`services/expense_service.py`**：`reupload_expense()` 補件 OCR 成功後 status 由 `PENDING` 改為 `SUPPLEMENTED`；OCR 失敗仍為 `NEEDS_MANUAL_REVIEW`
- **`routers/webhook.py`**：
  - 補件成功回覆改為完整 9 行模板（賣方、統編、日期、發票號碼、品項、含稅、未稅、稅額、狀態：已補件）
  - 兩處 `status_map` 新增 `"SUPPLEMENTED": "⚠️ 已補件"`（單號查詢 & 最近 3 筆查詢）
- **`frontend/src/components/ExpenseTable.vue`**：`statusConfig` 新增 `SUPPLEMENTED`（黃色燈號 `bg-yellow-400`、標籤「已補件」）
- **`alembic/versions/j7c8d9e0f1a2_...py`**：新增 migration，`ALTER TYPE expense_status ADD VALUE IF NOT EXISTS 'SUPPLEMENTED'`

#### 6. Header 「篩選條件」按鈕移至 FilterPanel（勾選上方）
- **需求**：將 `AppHeader` 右側登出按鈕左邊的「篩選條件」按鈕，移至 `FilterPanel` 的「勾選」下拉選單上方
- **`frontend/src/components/AppHeader.vue`**：移除 `SlidersHorizontal` 按鈕與 import
- **`frontend/src/components/FilterPanel.vue`**：新增 `SlidersHorizontal` import；在 Row 1（勾選選單）上方加入 Row 0 篩選條件按鈕

---

## 2026-04-08

**負責人**：product-manager (PM / L1)

### 完成的任務

#### 1. Sprint 1 提案書審核（G0）
- 讀取並審核 `proposal/sprint1-proposal.md`
- 確認 Sprint 目標：後端測試、Dashboard 完善、Webhook 超時修正、技術文件、Staging 部署
- G0 狀態：**已通過**，進入執行階段

#### 2. 規範文件建立（`.knowledge/specs/`）

| 檔案 | 內容 |
|------|------|
| `specs/data-model.md` | 三張資料表（users / expenses / user_states）完整欄位定義、DB sequence 說明、Alembic 遷移歷史、注意事項 |
| `specs/feature-spec.md` | F1~F5 功能規格（LINE Bot 對話流程、Dashboard 審核、測試套件、Webhook 超時修正、技術文件）、邊界條件、驗收標準 |

> `specs/api-design.md` 已預先存在，內容完整，無需重建。

#### 3. 開發計畫書產出（`proposal/sprint1-dev-plan.md`）
- 依 `/dev-plan` 流程，根據提案書與現有程式碼現況產出完整計畫書
- 包含：技術方案比較、檔案變更清單、5 個任務定義（T1~T5）、各 Agent 啟動指令、測試計畫、風險評估
- 第 10 節預建稽核軌跡空表（任務完成紀錄 / Review 紀錄 / Gate 紀錄）

---

### 遇到的問題

#### 問題 1：現有程式碼現況與提案書有落差
**現象**：提案書描述 Dashboard「待確認」，實際查看後發現前端完成度比預期高
- `expenseApi.js`、`expenseStore.js`、多個 Vue 元件已完整實作
- 但缺少 `ExpenseDetailView.vue`（詳情頁）與 `/expenses/:id` 路由
- Router 僅有 `/` 一條路由

**處理方式**：
- T2 任務調整聚焦於「補齊詳情頁 + serial_number 顯示 + E2E 驗證」，不需重建現有元件
- 在計畫書技術方案中選定「AuditModal 保留 + 新增 Detail 路由」組合方案

#### 問題 2：`serial_number` 依賴 PostgreSQL sequence 造成測試障礙
**現象**：`_generate_serial_number()` 呼叫 `SELECT nextval('expense_serial_seq')`，SQLite in-memory 無此語法，T1 測試環境會直接報錯

**處理方式**：
- 在計畫書風險與緩解章節標注
- 指示 backend-dev 在 `conftest.py` 中 `monkeypatch` mock `_generate_serial_number`，回傳固定值
- 不更動生產程式碼，純測試層處理

#### 問題 3：Webhook 超時（Postmortem #003）狀態為 `monitoring`
**現象**：#003 顯示解法已設計（BackgroundTasks + push_message），但狀態為 `monitoring` 而非 `resolved`，意味著尚未在生產環境驗證

**處理方式**：
- 拆解為獨立任務 T3 交由 backend-dev 正式實作與驗測
- T4 文件任務中包含將 #003 更新為 `resolved` 的步驟

---

### 明日待辦

- [ ] 等待老闆確認 `sprint1-dev-plan.md`
- [ ] Tech Lead 執行 `/task-delegation` 建立 `.tasks/` 追蹤檔案
- [ ] 啟動 T1（backend-dev）、T2（frontend-dev）、T3（backend-dev）並行執行

---
