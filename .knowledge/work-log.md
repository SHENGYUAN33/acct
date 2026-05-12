# Work Log — AcctAssist

> **用途**：記錄每日工作內容、完成任務、遇到的問題
> **更新規則**：每日工作結束後補充當天記錄

---

## 2026-05-05

**負責人**：tech-lead (L1)

### 完成的任務

#### 1. 退回機制重構 — 改為作廢原單 + LINE 純文字通知

- **需求**：退回單據時，原單不再標記 `REJECTED`，改標記為 `REPLACED_VOID`（作廢）；Dashboard 該列視覺灰化反白；LINE 通知改為純文字（移除重新上傳按鈕）
- **`services/expense_service.py`**：`reject_expense()` 改寫 `REJECTED` → `REPLACED_VOID`
- **`services/line_service.py`**：`push_reject_notification()` 由 Flex Message 改為純文字，顯示上傳日期、發票號碼、發票金額，並附備註「此發票已退回請重新上傳」；函式簽名同步縮減（移除 `expense_id`、`serial_number`、`reject_reason` 參數）
- **`routers/expenses.py`**：reject 端點改傳 `upload_date`、`invoice_number`、`total_amount` 給推播函式
- **`frontend/src/components/ExpenseTable.vue`**：`REPLACED_VOID` 列套用 `opacity-40 bg-gray-100`，視覺灰化

#### 2. 退回對話框移除原因輸入欄

- **需求**：退回不再需要填寫原因，直接確認即可
- **`routers/expenses.py`**：`RejectRequest.reason` 改為選填（`str = ""`）
- **`frontend/src/api/expenseApi.js`**：`rejectExpense()` 移除 reason 參數，固定送空字串
- **`frontend/src/stores/expenseStore.js`**：`rejectExpense(id)` 移除 reason 參數
- **`frontend/src/components/AuditModal.vue`**：移除 `rejectReason` ref、textarea 輸入欄，確認按鈕不再需要 reason 才能點擊

#### 3. Dashboard 拖曳排序功能

- **需求**：Dashboard 列表支援滑鼠拖曳調整順序，前後端排序一致且持久化
- **新增 Alembic Migration** `s5t6u7v8w9x0`：`expenses` 表新增 `display_order` 欄位（nullable Integer）
- **`models/expense.py`**：新增 `display_order: Mapped[int | None]` 欄位
- **`services/expense_service.py`**：
  - `list_expenses()` 排序改為 `display_order ASC NULLS LAST`，再以 `created_at DESC` 補位
  - 新增 `reorder_expenses(db, ordered_ids)`：依傳入的 ID 順序寫入 `display_order = 0, 1, 2...`
- **`routers/expenses.py`**：新增 `PATCH /api/v1/expenses/reorder` 端點；**刻意置於** `PATCH /expenses/{expense_id}` 之前，避免 `"reorder"` 被解析為 UUID 路徑參數
- **`frontend/src/api/expenseApi.js`**：新增 `reorderExpenses(orderedIds)` 函式
- **`frontend/src/stores/expenseStore.js`**：`reorderExpenses()` 改為 async，本地重排後呼叫 API；API 失敗時還原本地順序並拋出例外
- **`frontend/src/components/ExpenseTable.vue`**：新增 `GripVertical` icon、drag 事件處理（`onDragStart`/`onDragOver`/`onDrop`/`onDragEnd`）、拖曳中視覺高亮（被拖列黃底半透明、目標列藍底藍線）

### 遇到的問題

#### 問題 1：拖曳排序顯示「儲存失敗」

**現象**：拖曳後前端顯示 toast「排序儲存失敗」

**原因**：`PATCH /expenses/reorder` 定義在 `PATCH /expenses/{expense_id}` 之後，FastAPI 路由按定義順序匹配，`"reorder"` 被當成 UUID 路徑參數，嘗試轉型失敗，回傳 422

**處理方式**：將 `PATCH /expenses/reorder` 移至 `PATCH /expenses/{expense_id}` 之前（`routers/expenses.py` 第 172 行），並加上注釋說明順序原因

---

## 2026-04-28

**負責人**：project-lead (L1)

### 完成的任務

#### 1. 排程批次處理機制（取代 60 秒滑動計時器）

- **需求背景**：原有「機制二」為每位使用者獨立的 60 秒 debounce timer，用戶希望改為每天固定時間統一批次處理所有 pending 圖片
- **設計決策**：以逗號分隔的 `HH:MM` 清單支援「單一時間 / 雙時段 / 模擬時間範圍」三種模式
- **新建 `services/scheduled_batch_service.py`**：
  - `run_scheduled_batch()`：查詢所有 `UserState.pending_images != '[]'` 的使用者，逐一呼叫 `auto_split_service.auto_split_process()`
  - 使用者之間序列執行（避免 Gemini RPM 429），per-user 並行由既有 Semaphore 限速
  - 靜默執行，不推播 LINE 通知
- **新建 `services/scheduler.py`**：
  - 使用 `APScheduler AsyncIOScheduler`，依 `SCHEDULED_BATCH_TIMES` 建立多個 `CronTrigger`
  - 提供 `start_scheduler()` / `stop_scheduler()` / `get_scheduled_jobs()` 三個介面
  - `misfire_grace_time=300`：服務重啟後 5 分鐘內補跑錯過的觸發點
  - 格式驗證：無效的 `HH:MM` 格式記 error log 並略過，不中斷啟動
- **`core/config.py`**：新增 `enable_scheduled_batch: bool = False`、`scheduled_batch_times: list[str] = ["20:00"]`、`scheduled_batch_timezone: str = "Asia/Taipei"`，配合 `parse_scheduled_batch_times` validator 支援逗號分隔與 JSON array 兩種格式
- **`requirements.txt`**：新增 `apscheduler>=3.10.0`
- **`main.py`**：
  - `on_startup()`：新增 `start_scheduler()` 呼叫
  - 新增 `on_shutdown()`：呼叫 `stop_scheduler()`，避免殘留任務
  - `/health` 端點回應新增 `scheduled_jobs` 欄位（顯示各排程的 `next_run_time`）
- **`.env.example`**：新增 `ENABLE_SCHEDULED_BATCH`、`SCHEDULED_BATCH_TIMES`、`SCHEDULED_BATCH_TIMEZONE` 三項說明

#### 2. Dashboard 「立即處理 Pending」按鈕

- **需求**：在 Dashboard 匯出按鈕右側新增按鈕，可不等排程時間立即觸發所有 pending 圖片處理
- **`routers/admin.py`**：新增 `POST /api/v1/admin/process-pending` 端點（需 JWT 認證）
  - 以 `BackgroundTask` 非同步執行 `run_scheduled_batch()`，端點立即回傳，不阻塞請求
- **`frontend/src/api/expenseApi.js`**：新增 `processPendingNow()` 呼叫 `/api/v1/admin/process-pending`
- **`frontend/src/views/ExpenseListView.vue`**：
  - 新增 `isProcessing` / `processResult` 響應式狀態
  - 新增 `handleProcessPending()`：防重複點擊 + 5 秒後自動 refresh 列表 + 提示條自動消失
  - 按鈕樣式：橘色（`bg-orange-500`），與藍色匯出按鈕視覺區隔，icon 使用 `Zap`（閃電）
  - 成功顯示綠色提示條、失敗顯示紅色提示條，右側有 `×` 可手動關閉

### 明日待辦

- [ ] 安裝新依賴：`pip install apscheduler>=3.10.0`
- [ ] 在 `.env` 補入排程相關設定（`ENABLE_SCHEDULED_BATCH`、`SCHEDULED_BATCH_TIMES`、`SCHEDULED_BATCH_TIMEZONE`）
- [ ] 重啟服務後呼叫 `GET /health`，確認 `scheduled_jobs` 中出現對應的 `next_run_time`
- [ ] 實機測試：上傳圖片後點擊「立即處理 Pending」→ 確認 5 秒後列表出現新報帳記錄
- [ ] 確認 `.env` 中 `GEMINI_API_KEY` 為有效金鑰（非 placeholder）
- [ ] 瀏覽器 `Ctrl+Shift+R` 強制刷新後，點擊「重新辨識」→ 觀察 F12 Console `[ReOCR]` log 確認實際錯誤
- [ ] 修復 `routers/webhook.py` line 357 的 `ocr_service.extract_invoice_data()` 不存在問題（應改為 `classify_and_extract_with_retry`）

#### 3. 修復備註（pending_description）分配錯誤至多筆報帳群組

**問題現象**：測試投入「憑證、物品、備註1、憑證、備註2、憑證」共三組時，Dashboard 顯示兩則備註全部歸入同一筆資料。

**根因分析（兩層）**：
- **Bug 1 — 分隔符不一致**：`webhook.py` 用 `\n` 拼接備註，但 `distribute_description()` 用 `\n\n` 切段落，永遠只會產生 1 個 paragraph
- **Bug 2 — 設計缺陷（根本）**：`pending_description` 為扁平字串，無時序資訊，`distribute_description()` 依「段落數 ≈ 群組數」的計數匹配邏輯先天無法正確對應

**修復內容**：
- **`routers/webhook.py`**：備註改為帶 `event.timestamp` 的 JSON array 格式 `[{"text": "...", "timestamp": 毫秒Unix}]`，`confirm_submit` 路徑同步展開為純文字
- **`services/auto_split_service.py`**：
  - 新增 `_flatten_description()`：統一將新/舊格式轉換為純文字（向後相容）
  - 新增 `distribute_description_by_timestamps()`：依各群組憑證的 timestamp 作為時間邊界，將備註按時序歸入對應群組；舊格式自動降級為段落分配
  - `auto_split_process()` 改用 `distribute_description_by_timestamps()`，以 `path_to_timestamp` 字典取得各群組憑證的時間點

**不需要 DB Migration**：`UserState.pending_description` 欄位型別不變（仍為 Text），僅儲存格式改為 JSON 字串；`UserState` 為暫存 buffer，處理後即清空，無舊資料遺留問題。

**確認的設計行為**：
- LINE 相簿多選一次傳送時，每張圖片仍為獨立 `ImageMessageContent` event，`event.timestamp` 依選取順序遞增，現行 timestamp 排序邏輯正確
- `message_id` 作為次要排序 key 可加強穩定性（防同毫秒極端情境），待後續加入

#### 4. 開發環境一鍵啟動（`npm run dev`）

- **需求**：每次啟動需手動開三個終端（uvicorn、ngrok、Vite），改為單一指令啟動全部服務
- **方案**：根目錄新增 `package.json`，使用 `concurrently` 套件並行管理三個 process
- **新建 `package.json`（根目錄）**：
  - `concurrently --kill-others`：任一 process crash 全部停止，避免殭屍 process
  - `--names "API,UI,TUNNEL" --prefix-colors "cyan.bold,green.bold,yellow.bold"`：彩色前綴區分輸出
  - 加入 `set PYTHONIOENCODING=utf-8` 解決 Windows 終端機中文 log 亂碼
- **`.gitignore`**：新增根目錄 `node_modules/`、`package-lock.json`
- **`.env.example`**：修正 `SCHEDULED_BATCH_TIMES` 範例格式為 JSON array（`["20:00"]`），防止 pydantic-settings 解析錯誤

#### 5. Debug「重新辨識」按鈕（AuditModal Re-OCR）

- **問題現象**：Dashboard AuditModal 點擊「重新辨識」後直接顯示「重新辨識失敗，請確認圖片是否正常」，未看到 loading 狀態
- **根因分析（兩層）**：
  - **Bug 1 — Axios timeout 過短**：全域設定 15 秒，但 Gemini OCR + 最多 3 次指數退避重試需 30–90 秒，請求被 Axios 提前中斷（`ECONNABORTED`）
  - **Bug 2 — `catch` 缺少錯誤參數**：原始碼 `catch {`（ES2019 optional binding）無法存取 `err.response.data.detail`，永遠顯示同一則 generic 錯誤訊息，無法區分 timeout / API 錯誤 / 網路中斷
- **修正內容**：
  - **`frontend/src/api/expenseApi.js`**：`reOcrExpense()` 新增第三參數 `{ timeout: 120000 }`，僅覆蓋此端點 timeout，不影響其他 API
  - **`frontend/src/components/AuditModal.vue`**：`catch {` 改為 `catch (err)`，加入 `console.error('[ReOCR]', ...)` 完整 log；依情境分支顯示訊息：`ECONNABORTED` → 逾時提示、`err.response.data.detail` 存在 → 顯示後端說明、無 response → 無法連線提示、其他 → HTTP status code

- **附帶發現的 Bug（尚未修復）**：
  - `routers/webhook.py` line 357：`await ocr_service.extract_invoice_data(save_path)` — 該函式不存在於 `ocr_service.py`（僅有 `classify_and_extract_with_retry`），補件流程（`REUPLOADING_` step）觸發時會 `AttributeError`

### 遇到的問題（本日新增）

#### 問題 4：`SCHEDULED_BATCH_TIMES` .env 格式錯誤導致啟動失敗
**現象**：`pydantic_settings.exceptions.SettingsError: error parsing value for field "scheduled_batch_times"` — `json.decoder.JSONDecodeError: Extra data`

**根本原因**：pydantic-settings v2 對 `list[str]` 型別欄位，在執行自訂 `@field_validator(mode="before")` 之前，會先呼叫內部 `decode_complex_value()` → `json.loads()` 解析原始字串。若值為 `20:00`（非合法 JSON）custom validator 根本沒機會執行就已拋錯。

**處理方式**：`.env` 改為合法 JSON array 格式：`SCHEDULED_BATCH_TIMES=["20:00"]`；同步更新 `.env.example` 範例格式

#### 問題 5：`concurrently` 未安裝直接執行報錯
**現象**：`'concurrently' 不是內部或外部命令`
**處理方式**：執行 `npm install` 安裝根目錄 devDependency 後即正常

#### 問題 6：`apscheduler` 套件未安裝
**現象**：`ModuleNotFoundError: No module named 'apscheduler'`
**處理方式**：`pip install -r requirements.txt` 補裝所有依賴（套件已在 requirements.txt 但未實際安裝）

---

## 2026-04-20

**負責人**：project-lead (L1)

### 完成的任務

#### 1. 劇組四情境報帳關聯邏輯實作（`services/relation_service.py`）

- **新建** `services/relation_service.py`，實作劇組四種特殊報帳情境
- **情境 1 — WAITING_RETURN**：偵測說明文字含「待退貨」關鍵字，物品照補傳後自動結清（status → COMPLETED）；支援 Flow A（說明文字帶裸號碼 `AB-12345678`）與 fallback（最新一筆）雙重匹配
- **情境 2 — VOID_REPLACE**：說明文字含 `[AB-12345678]` 括號格式 → 舊單作廢（`is_active=False` + `REPLACED_VOID`），新單以 `parent_id` 串聯，`void_reason` 由 regex 提取（換貨換單 / 統編錯誤 / 金額錯誤 / 作廢重開）
- **情境 3A — CREDIT_NOTE**：Gemini 辨識出 `voucher_category=CREDIT_NOTE` + `original_invoice_number` → 自動連結原始發票，計算 `net_amount`（原單金額 + 折讓負數）
- **情境 3B — SUPPLEMENT**：說明文字含「之前收據日期：YYYY-MM-DD、金額：NNN」→ 三維模糊搜尋（日期 ±3 天 × 金額 ±10% × 店家名稱前綴比對）
- **情境 4（孤立物品圖向前關聯）**：`attach_orphan_images_to_recent_expense()` 在 10 分鐘視窗內補入前一筆報帳
- **`services/expense_service.py`** / **`routers/webhook.py`**：呼叫 `auto_link_records()` + `attach_item_photos_to_waiting_return()`，整合至批次報帳主流程
- git commits：`feat: 新增劇組四情境報帳邏輯 — 待退貨、換單作廢、折讓關聯、Bundle 群組化 (59c6602)`

#### 2. 使用者情境全覽文件整理（Session 輸出）

- 整理系統七大使用者情境（Onboarding、批次報帳 A1/A2、補件 B、查詢 C、劇組四情境）
- 每個情境含完整步驟 + 真實情境舉例
- 狀態機總覽（PENDING / APPROVED / REJECTED / NEEDS_MANUAL_REVIEW / SUPPLEMENTED / WAITING_RETURN / COMPLETED / REPLACED_VOID）

---

## 2026-04-17

**負責人**：project-lead (L1)

### 完成的任務

#### 1. 緊急 Bug 修正 — `ExpenseImage.image_url` 收到 dict 導致 DB INSERT 失敗

- **現象**：LINE 使用者按「確認送出」後，背景任務 `_process_batch` 丟出 `psycopg2.ProgrammingError: can't adapt type 'dict'`，報帳資料無法寫入 DB
- **根本原因**：Sprint 3 將 `pending_images` 格式從純路徑字串升級為 dict（含 `path` / `timestamp` / `message_id`），但 `services/expense_service.py` 的 `create_batch_expense()` 在建立 `ExpenseImage` 時直接把整個 dict 傳給 `image_url`（VARCHAR 欄位），psycopg2 無法序列化
- **修正位置**：`services/expense_service.py` 第 626–628 行（INSERT ExpenseImage 迴圈）
- **修正方式**：在建立 `ExpenseImage` 前加入型別判斷，取出 `path` 字串：
  ```python
  image_url_str: str = image_path["path"] if isinstance(image_path, dict) else str(image_path)
  ```
- **向下相容**：若 `image_path` 為舊格式字串，`str()` 兜底，不影響既有資料

### 遇到的問題

#### 問題 1：Sprint 3 格式升級未同步更新 expense_service
**現象**：`webhook.py` 中 `pending_images` 元素改為 `{"path": ..., "timestamp": ..., "message_id": ...}` 的新格式，但 `expense_service.py` 內建立 `ExpenseImage` 的程式碼仍沿用舊邏輯，直接將 `image_path`（實為 dict）賦給 `image_url`

**處理方式**：最小侵入修正，一行型別判斷，保留兩種格式相容性；不動其他欄位邏輯

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
