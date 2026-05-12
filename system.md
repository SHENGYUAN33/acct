## AcctAssist 系統流程口稿（晶晶體版）

---

### 流程一：Initialize — 部門選擇 + 身份 Binding

1. User 在 LINE 傳送任意訊息
2. LINE Platform trigger Webhook，`POST /webhook` 驗證 `X-Line-Signature`，呼叫 `get_or_create_user()` 查詢或建立 users 記錄
3. 若 User **還沒 set 部門**：
   - 若有開 `ENABLE_USER_BINDING` 且 `user.real_name` 為空：
     - 若 UserState.step 已是 `BINDING_REAL_NAME` 且收到文字 → `update_user_real_name()` 寫入 DB，清除 state，reply「綁定成功，請選擇組別」
     - 否則 → `set_user_state(step="BINDING_REAL_NAME")`，reply 請輸入真實姓名
   - 系統 call `reply_with_dept_selection()`，return QuickReply 部門選單
4. User 選擇部門，系統執行 `update_user_department()` 寫進 DB，回覆 confirm

---

### 流程二：LINE Bot 報帳 — 手動 Confirm Submit（trigger_by = manual_button）

**Result：所有圖片 merge 成 1 筆 Expense + N 筆 ExpenseImage**

1. User upload 圖片，系統 download 到本地 `uploads/{uuid}.jpg`
2. 用 `SELECT FOR UPDATE` lock 住 state，建立或 update `UserState(step=COLLECTING)`，把圖片 info（path、timestamp、message_id）append 進 `pending_images`（JSON array，Sprint 3 新格式）
3. 若有開 `ENABLE_AUTO_SPLIT`，同步排程 sliding window Timer（`auto_split_timer.schedule()`），debounce 秒數由 `AUTO_SPLIT_DEBOUNCE_SECONDS` 設定
4. User 可以穿插傳**文字 note**，系統確認非指令文字後 silent 地 append 進 `UserState.pending_description`，不回覆
5. User 繼續 upload 第 2、3…N 張圖，每次重複步驟 2～3，Timer 每次 reset 滑動視窗
6. User 點 Rich Menu「**確認送出**」，trigger `PostbackEvent(action=confirm_submit)`：
   - 立刻 cancel Timer（`auto_split_timer.cancel()`）
   - 取出所有 `pending_images` 跟 `pending_description`，立即清空 buffer 並 commit（防重複）
   - 優先 reply「已送出報帳」（< 500ms）
7. BackgroundTask `_process_batch()` 開始跑：
   - **並行** `asyncio.gather()` + `_OCR_SEMAPHORE`（最多 3 張同時）call `classify_and_extract_with_retry()`，每張最多重試 3 次（指數退避）
   - **情境 1 判斷**：若所有圖片均非憑證（`is_voucher=False`）→ 嘗試 `attach_item_photos_to_waiting_return()`，從說明文字 regex 抽取裸號碼（AB-12345678）精準對應 WAITING_RETURN 單；成功則 push 通知並直接結束
   - 一般路徑：生成 `batch_group_id`，call `create_batch_expense(trigger_by="manual_button")`
8. `create_batch_expense()` 執行彙整：
   - **Flow B：重複憑證偵測** — 若主憑證 invoice_number 與同 user 的 WAITING_RETURN 單吻合，補入物品照到舊單，status 改 COMPLETED，直接回傳，不重複建帳
   - 依 priority 選 primary 憑證：INVOICE > RECEIPT > LABOR_SERVICE > INSURANCE > RENTAL > ACCOMMODATION > UTILITY > POSTAGE > TRANSPORTATION（CREDIT_NOTE 不作為主憑證）
   - 加總所有 `is_voucher=True` 圖片的金額（CREDIT_NOTE 為負數，直接加總）
   - 判斷 status：`total_amount=None` 或任一關鍵稽核欄位 confidence < 閾值 → `NEEDS_MANUAL_REVIEW`；說明文字含「待退貨/待退/退貨中」且 PENDING → 改為 `WAITING_RETURN`；否則 `PENDING`
   - 序號以 MAX 查詢當月最大流水號 +1 產生（`EXP-YYYYMM-NNNN`），5 次 retry 防 race condition
   - INSERT 1 筆 Expense（憑證圖入 `image_url[]`、物品圖入 `item_image_url[]`）+ N 筆 ExpenseImage（含 sequence_order / OCR JSON）
   - commit 後呼叫 `auto_link_records()` 執行關聯偵測（情境 2/3A/3B），失敗不影響已建立的報帳
9. Push 報帳完成摘要給 User（serial number）

---

### 流程三：LINE Bot 報帳 — Auto Split（trigger_by = auto_split）

**Result：依 OCR 結果兩階段切割，可能 generate 多筆 Expense，User 完全無感**

1. User upload 多張圖片，系統 silent 地累積（同流程二 step 1～5）
2. 每張圖片都 reset sliding window Timer
3. **User 沒按 confirm，debounce 秒數無新 upload → Timer expired**，trigger `auto_split_service.auto_split_process()`：
   - 讀取 `pending_images`，若 empty 直接 return（防空批次）
   - `_parse_buffer()` parse 並依 timestamp ASC sort（毫秒 Unix）
   - 立刻清空 buffer 並 commit（防重複 trigger）
   - **並行** `asyncio.gather()` + Semaphore 逐張跑 `classify_and_extract_with_retry()`
   - `multi_split_logic_v2()` 兩階段切割：
     - **Phase 1**：掃描整個 batch，識別所有 `is_voucher=True` 的憑證索引
     - **Phase 2**：第一個憑證「之前」的非憑證圖 → 歸入 `orphan_paths`；從第一個憑證開始依 `is_voucher=True` 作為群組斷點
   - **Orphan 處理**：`attach_orphan_images_to_recent_expense()` 嘗試補入 10 分鐘內最新報帳；若無可關聯記錄 → 建立純物品圖報帳（`trigger_by="auto_split_orphan"`，標記 NEEDS_MANUAL_REVIEW）
   - `distribute_description()` 以雙換行分段，將說明文字分配給各群組
   - 所有群組共用同一 `batch_group_id`（供 Dashboard 整捆操作）
   - 對每個 group 各自 call `create_batch_expense(trigger_by="auto_split")`，建立獨立 Expense
   - 單一 group fail 不影響其他 group（try-except 隔離）
4. User 完全無感，系統 silent 地 complete，可能同時建立多筆報帳單

---

### 流程四：劇組四情境關聯邏輯（auto_link_records）

**在 create_batch_expense commit 之後自動執行，失敗不影響主流程**

**情境 1：WAITING_RETURN — 待退貨物品補傳**
- 觸發：所有圖片均為非憑證圖（`is_voucher=False`）
- 說明文字抽取裸發票號碼（`AB-12345678` regex）精準比對，或 fallback 同 user 最新 WAITING_RETURN 單
- 找到 → 補入物品照，status 改 `COMPLETED`，push 通知

**情境 2：VOID_REPLACE — 換單作廢**
- 觸發：說明文字含 `[AB-12345678]` 括號格式發票號碼
- 找到原單 → `is_active=False`、status 改 `REPLACED_VOID`、填入 `void_reason`
- 新單 `parent_id` 指向舊單，`relation_type="VOID_REPLACE"`

**情境 3A：CREDIT_NOTE — 折讓關聯**
- 觸發：Gemini 辨識出 `voucher_category=CREDIT_NOTE` 且有 `original_invoice_number`
- 找到原始發票（發票號碼精準比對，備援：店家名稱前 4 字元 + 7 天內）
- 折讓單 `parent_id` 指向原單，`relation_type="CREDIT_NOTE"`
- 計算 `target.net_amount = target.total_amount + 折讓金額（負數）`

**情境 3B：SUPPLEMENT — 差額補足**
- 觸發：說明文字含「之前收據日期：YYYY-MM-DD、金額：XXX」格式
- `search_fuzzy_expense()` 三維模糊搜尋：日期 ±3 天 + 金額 ±10% + 店家名稱（完整 → 前 4 字元前綴 → 無 seller）
- 找到 → 新單 `parent_id` 指向原單，`relation_type="SUPPLEMENT"`

---

### 流程五：Supplement 流程（Reject → LINE Push → Re-upload）

1. 審核者在 Dashboard 對報帳單執行退回，call `PATCH /api/v1/expenses/{id}/reject`
2. `reject_expense()` 把 status 改成 `REJECTED`，寫入 reject reason
3. 若有開 `ENABLE_LINE_PUSH_REJECT`，查詢 uploader 的 `line_user_id`，push Flex Message（含 reject reason + 「重新上傳照片」PostbackAction）
4. User 點 button，trigger `PostbackEvent(action=reupload&expense_id=xxx)`
5. 系統把 state set 成 `REUPLOADING_{expense_id}`，reply 提示 upload 新圖片
6. User upload 新圖片：
   - download 圖片，call `ocr_service.extract_invoice_data()`（單張簡化版 OCR）
   - `reupload_expense()` 取代原單第一張圖片路徑，更新 OCR 欄位
   - status 改：OCR 成功 → `SUPPLEMENTED`；OCR 失敗 → `NEEDS_MANUAL_REVIEW`
   - `delete_user_state()` 清除 supplement state
7. reply 補件結果摘要（賣方、統編、日期、發票號碼、品項、金額等）

---

### 流程六：Dashboard 審核流程

**Login**
1. 審核者輸入帳密，frontend call `POST /api/v1/auth/login`
2. Backend 用 bcrypt verify 密碼，pass 後 generate JWT（expire 60 分鐘）
3. Frontend 收到 `access_token` 存進 local storage，後續 request 一律帶 `Authorization: Bearer {token}`

**Query List**

4. Frontend 依 filter 條件（status、日期 range、page）call `GET /api/v1/expenses`
5. Router 透過 `get_current_user()` verify JWT，再 call `list_expenses()`
   - 預設排除 `is_active=False` 的作廢記錄（REPLACED_VOID 不計入）
   - 依 `created_at DESC` sort 並 paginate

**Detail View**

6. 點單筆後 fetch Expense 詳情（`GET /api/v1/expenses/{id}`）
7. 分別 fetch ExpenseImage list（`GET /api/v1/expenses/{id}/images`，依 `sequence_order ASC` sort）

**Approve**

8. 審核者點 approve，call `PATCH /api/v1/expenses/{id}` 把 status update 成 `APPROVED`，寫回 DB

**Reject**

9. 審核者輸入 reject reason，call `PATCH /api/v1/expenses/{id}/reject`，status 改成 `REJECTED`
10. 若有開 push 開關，自動 trigger 流程五（LINE push supplement 通知）

**其他 Dashboard 操作**

- `POST /api/v1/expenses/{id}/reocr`：重新跑 OCR 並更新欄位
- `POST /api/v1/expenses/{id}/images`：追加補件圖片（expense / item 類型）
- `GET /api/v1/expenses/export`：CSV 匯出（含 BOM，附 status / 日期過濾，最多 10,000 筆）

---

### 進度查詢（使用者文字觸發）

- 傳送 `EXP-YYYYMM-NNNN` 格式 → 查詢指定單號狀態（支援 WAITING_RETURN / COMPLETED / REPLACED_VOID 等全部狀態）
- 傳送「查詢進度」或「查詢」→ 回傳最近 3 筆報帳狀態（含金額、日期、狀態）

---

### 狀態機一覽

| 狀態 | 說明 |
|------|------|
| `PENDING` | OCR 成功，等待人工審核 |
| `APPROVED` | 已核准 |
| `REJECTED` | 已退回（含 reject_reason） |
| `NEEDS_MANUAL_REVIEW` | OCR 失敗或關鍵欄位信心不足，需人工處理 |
| `SUPPLEMENTED` | 補件成功，重新進入審核流程 |
| `WAITING_RETURN` | 待退貨未結清（說明文字含「待退貨」關鍵字） |
| `COMPLETED` | 已結清（WAITING_RETURN + 物品照補傳後轉入） |
| `REPLACED_VOID` | 作廢換單（VOID_REPLACE 情境舊單） |
