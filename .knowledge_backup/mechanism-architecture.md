# AcctAssist — 機制一、機制二 & 機制三 技術架構與流程

> **文件版本**：v1.1
> **撰寫日期**：2026-04-14
> **適用 Sprint**：Sprint 2（批次報帳）、Sprint 3（Auto Split）
> **作者**：project-lead

---

## 目錄

1. [機制一：首次使用者 Onboarding（部門一次性設定）](#機制一)
2. [機制二：多張照片批次報帳（Batch Expense）](#機制二)
3. [機制三：自動切割報帳（Auto Split）](#機制三)
4. [共用資料表結構](#共用資料表結構)
5. [系統邊界與模組責任](#系統邊界與模組責任)

---

## 機制一：首次使用者 Onboarding（部門一次性設定） {#機制一}

### 1.1 設計目標

使用者**只需設定一次部門**，後續所有報帳操作不再詢問。
設定結果永久寫入 `users.department`，除非使用者主動輸入部門名稱更換。

---

### 1.2 觸發條件

| 條件 | 判斷方式 | 觸發動作 |
|------|---------|---------|
| 新使用者傳送任何訊息（文字或圖片） | `users.department IS NULL` | 進入 Onboarding 流程 |
| 啟用實名綁定且尚未綁定（選配） | `settings.enable_user_binding AND user.real_name IS NULL` | 先進行實名綁定，再選部門 |
| 已設定部門的使用者傳送部門名稱文字 | `text in DEPT_OPTIONS` | 更換部門（直接更新） |

---

### 1.3 完整流程

#### 標準 Onboarding（未啟用實名綁定）

```
使用者第一次傳送任何訊息（文字或圖片）
        │
        ▼
webhook.py → get_or_create_user()
        │
        ├─ user.department IS NULL？
        │         YES
        │          ▼
        │   line_service.reply_with_dept_selection(reply_token)
        │   ┌────────────────────────────────────────┐
        │   │  LINE Quick Reply 選單                  │
        │   │  [製片組] [美術組] [攝影組] [燈光組] [其他] │
        │   └────────────────────────────────────────┘
        │          │
        │          ▼
        │   使用者點選部門（PostbackEvent / TextMessage）
        │          │
        │          ▼
        │   expense_service.update_user_department(db, line_user_id, dept)
        │   → 寫入 users.department（永久，不再詢問）
        │          │
        │          ▼
        │   Bot 回覆：「✅ 已設定為『攝影組』，請直接上傳憑證照片 📷」
        │
        └─ user.department 已設定 → 進入正常批次收集流程（機制二）
```

#### 進階 Onboarding（啟用 `settings.enable_user_binding`）

```
使用者第一次傳送任何訊息
        │
        ▼
webhook.py → get_or_create_user()
        │
        ├─ user.department IS NULL AND user.real_name IS NULL
        │         │
        │         ├─ step == "BINDING_REAL_NAME" AND 傳送文字
        │         │         ▼
        │         │   expense_service.update_user_real_name(db, line_user_id, text)
        │         │   line_service.delete_user_state(db, line_user_id)
        │         │   Bot 回覆：「✅ 綁定成功，王小明您好！請選擇所屬組別」
        │         │
        │         └─ 尚未進入綁定步驟
        │                   ▼
        │           line_service.set_user_state(db, line_user_id, "BINDING_REAL_NAME")
        │           Bot 回覆：「請輸入您的【真實姓名】（例如：王小明）：」
        │
        └─ 綁定完成後 → 顯示部門選單（同標準流程）
```

---

### 1.4 部門清單管理

部門清單透過環境變數動態配置，**不寫死於程式碼**：

```ini
# .env
DEPARTMENTS=製片組,美術組,攝影組,燈光組,場務組,其他
```

```python
# core/config.py
class Settings(BaseSettings):
    departments: list[str] = Field(default=["製片組", "美術組", "攝影組", "燈光組", "其他"])

    @validator("departments", pre=True)
    def parse_departments(cls, v):
        if isinstance(v, str):
            return [d.strip() for d in v.split(",") if d.strip()]
        return v
```

> 修改部門清單：只需編輯伺服器 `.env` 並重啟服務，**無需重新部署程式碼**。

---

### 1.5 涉及模組與資料流

```
LINE App（使用者）
      │  TextMessage / ImageMessage
      ▼
POST /webhook  ←──── routers/webhook.py
      │
      ├─ get_or_create_user()       ← services/expense_service.py
      │    → SELECT users WHERE line_user_id = ?
      │    → INSERT users（首次）
      │
      ├─ get_user_state()           ← services/line_service.py
      │    → SELECT user_states WHERE line_user_id = ?
      │
      ├─ set_user_state()           ← services/line_service.py（實名綁定用）
      │    → UPSERT user_states SET step = "BINDING_REAL_NAME"
      │
      ├─ update_user_real_name()    ← services/expense_service.py
      │    → UPDATE users SET real_name = ?
      │
      ├─ update_user_department()   ← services/expense_service.py
      │    → UPDATE users SET department = ?
      │
      └─ reply_with_dept_selection() ← services/line_service.py
           → LINE Messaging API：Reply Message（Quick Reply）
```

---

### 1.6 資料庫變更

| 表 | 欄位 | 說明 |
|----|------|------|
| `users` | `department` | 部門名稱（NULL = 尚未設定，觸發 Onboarding） |
| `users` | `real_name` | 實名綁定姓名（NULL = 尚未綁定） |
| `user_states` | `step` | 狀態機步驟（`BINDING_REAL_NAME` / `COLLECTING` / `REUPLOADING_{id}`） |

---

---

## 機制二：多張照片批次報帳（Batch Expense） {#機制二}

### 2.1 設計目標

使用者可**連續傳送多張照片與文字備註**，全部累積後按一次「確認送出」，系統將所有圖片彙整為**一筆 Expense + N 筆 ExpenseImage**，並完成 OCR 分類與金額加總。

---

### 2.2 系統架構概覽

```
┌─────────────────────────────────────────────────────────────────┐
│  LINE 聊天視窗                                                    │
│                                                                  │
│  [圖片 1] [圖片 2] [圖片 3]  [文字備註]                           │
│  ┌──────────────────────────────────────┐                       │
│  │           ✅  確認送出                 │  ← Rich Menu 常駐    │
│  └──────────────────────────────────────┘                       │
└─────────────────────────────────────────────────────────────────┘
          │
          │ LINE Messaging API Webhook
          ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI  POST /webhook                                          │
│                                                                  │
│  ImageMessageContent → 累積至 UserState.pending_images           │
│  TextMessageContent  → 累積至 UserState.pending_description      │
│  PostbackEvent(action=confirm_submit) → 觸發送出                 │
└─────────────────────────────────────────────────────────────────┘
          │ BackgroundTask（非同步，不阻塞 Webhook 回應）
          ▼
┌─────────────────────────────────────────────────────────────────┐
│  _process_batch()                                                │
│                                                                  │
│  for image in pending_images:                                    │
│      ocr_results.append(await classify_and_extract(image))      │
│                                                                  │
│  create_batch_expense(db, user_id, pending_images, ocr_results) │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│  PostgreSQL                                                      │
│                                                                  │
│  expenses（1 筆）                                                 │
│  expense_images（N 筆，N = len(pending_images)）                 │
└─────────────────────────────────────────────────────────────────┘
```

---

### 2.3 詳細流程

#### Phase 1：圖片收集（每張照片觸發）

```
使用者傳送照片（ImageMessageContent）
        │
        ▼
webhook.py 接收 ImageMessageContent
        │
        ├─ 狀態確認：step.startswith("REUPLOADING_") → 補件流程（不在此描述）
        │
        └─ 一般批次收集模式
                 │
                 ▼
         line_service.download_image(message_id, save_path)
         → 下載至 uploads/{uuid}.jpg
                 │
                 ▼
         SELECT user_states ... FOR UPDATE   ← 防競態條件
         （db.begin_nested() 確保原子性）
                 │
                 ├─ UserState 不存在 → INSERT UserState(step="COLLECTING")
                 └─ UserState 存在  → 讀取 pending_images（JSON array）
                 │
                 ▼
         images.append({
             "path": str(save_path),
             "timestamp": event.timestamp,
             "message_id": message_id,
         })
         db_state.pending_images = json.dumps(images)
         db.commit()
                 │
                 ▼
         [選配] 若 settings.enable_auto_split:
             auto_split_timer.schedule(line_user_id, debounce_sec, callback)
             → 滑動視窗計時器：N 秒無新圖片 → 自動觸發切割送出
                 │
                 ▼
         ← 靜默，不回覆 LINE（減少訊息干擾）
```

#### Phase 2：文字備註累積

```
使用者傳送文字（非指令文字）
        │
        ▼
webhook.py → 判斷非系統指令（非部門名稱、非查詢指令）
        │
        ▼
db_state = db.get(UserState, line_user_id)
若不存在 → INSERT UserState(step="COLLECTING")
        │
        ▼
db_state.pending_description += "\n" + text
db.commit()
        │
        ▼
← 靜默，不回覆 LINE
```

#### Phase 3：確認送出（Postback 觸發）

```
使用者按下 Rich Menu「確認送出」
        │
        ▼
LINE 發送 PostbackEvent(data="action=confirm_submit")
        │
        ▼
webhook.py → 解析 PostbackEvent
        │
        ├─ [Sprint 3] 若 settings.enable_auto_split:
        │       auto_split_timer.cancel(line_user_id)  ← 取消自動切割計時器
        │
        ▼
get_or_create_user(db, line_user_id)
db.get(UserState, line_user_id)
pending_images = json.loads(state.pending_images or "[]")
        │
        ├─ pending_images 為空 → 空批次防護
        │       Bot 回覆：「尚未收到任何照片，請先傳送發票照片 📷」
        │       → 結束，無任何 DB 寫入
        │
        └─ pending_images 非空
                 │
                 ▼
         line_service.reply_text(reply_token, "已送出報帳")
         ← 立即回應（< 500ms，使用 reply_token，只能用一次）
                 │
                 ▼
         取出 pending_description
         state.pending_images = "[]"       ← 立即清空防重複送出
         state.pending_description = ""
         db.commit()
                 │
                 ▼
         background_tasks.add_task(_process_batch, ...)
         ← 非同步背景任務，不阻塞 Webhook 回應
```

#### Phase 4：背景批次處理

```
_process_batch(line_user_id, pending_images, user_description,
               uploader_name, uploader_dept, user_id, trigger_by)
        │
        ▼
【序列 OCR】for image_path in pending_images:
    result = await classify_and_extract(image_path)
    ← 序列執行（非並行），避免 Gemini 免費版 429 RPM 限制
    ocr_results.append(result)
        │
        ▼
create_batch_expense(db, user_id, pending_images, ocr_results, ...)
        │
        ├─ 錯誤處理：logger.error() 記錄，不拋出（避免中斷 BackgroundTask）
        └─ 完成後 db.close()（獨立 DB session，不與 request session 共用）
```

#### Phase 5：費用彙整（create_batch_expense）

```
create_batch_expense(...)
        │
        ▼
Step 1  _pick_primary_fields(ocr_results)
        主憑證優先級：INVOICE > RECEIPT > LABOR_SERVICE > TRANSPORTATION
        （CREDIT_NOTE 不作為主憑證）
        → 選出最高優先級憑證的欄位（invoice_number, seller_name,
          expense_date, total_amount, tax_amount 等）
        │
        ▼
Step 2  total_amount 加總
        for result in ocr_results:
            if result.success AND result.is_voucher AND total_amount != null:
                accumulated += Decimal(result.fields["total_amount"])
        ← CREDIT_NOTE 的 total_amount 已確保為負數，直接相減效果
        │
        ▼
Step 3  voucher_categories 去重
        seen_categories = [INVOICE, TRANSPORTATION] (例)
        → json.dumps(seen_categories) → 存為 TEXT 欄位
        │
        ▼
Step 4  判斷狀態
        total_amount is not None → PENDING（等待人工審核）
        total_amount is None     → NEEDS_MANUAL_REVIEW（OCR 全部失敗）
        │
        ▼
Step 5  分類圖片
        is_voucher=True  → voucher_images（→ expenses.image_url[]）
        is_voucher=False → item_images（→ expenses.item_image_url[]）
        │
        ▼
Step 6  INSERT expenses（含 5 次重試機制防流水號碰撞）
        serial_number = EXP-{YYYYMM}-{序號 4 位}  ← 月重置
        db.flush()（取得 expense.id，尚未 commit）
        │
        ▼
Step 7  INSERT N 筆 expense_images
        for seq, (image_path, ocr_result) in enumerate(zip(...), start=1):
            ExpenseImage(
                expense_id   = expense.id,
                image_url    = image_path,
                is_voucher   = ocr_result.is_voucher,
                voucher_category = ocr_result.voucher_category,
                sequence_order   = seq,          ← 上傳順序
                ocr_result       = json(fields), ← Gemini 原始回傳
            )
        db.commit()
        db.refresh(expense)
        return expense
```

---

### 2.4 OCR 分類引擎（classify_and_extract）

#### 輸入
- `image_path: str | Path` — 本地圖片路徑（`uploads/{uuid}.jpg`）

#### 內部流程

```
classify_and_extract(image_path)
        │
        ▼
Image.open(image_path)
        │
        ▼
Gemini API：aio.models.generate_content(
    model = settings.gemini_model,    # gemini-2.5-flash（預設）
    contents = [MULTI_TASK_PROMPT, img],
    config = GenerateContentConfig(response_mime_type="application/json"),
)
        │
        ▼
_parse_gemini_response(raw_text)
→ 去除 Markdown code fence，json.loads()
        │
        ├─ is_voucher = False
        │       → ImageOCRResult(is_voucher=False, voucher_category=None, fields=None)
        │
        └─ is_voucher = True
                 ▼
         voucher_category = INVOICE / RECEIPT / LABOR_SERVICE /
                            TRANSPORTATION / CREDIT_NOTE
                 │
                 ├─ CREDIT_NOTE：確保 total_amount 為負數
                 │       if fields["total_amount"] > 0:
                 │           fields["total_amount"] = -fields["total_amount"]
                 │
                 ▼
         ImageOCRResult(
             is_voucher      = True,
             voucher_category = "INVOICE",
             fields           = {invoice_number, seller_name, ...},
             raw_response     = raw_text,
             success          = True,
             error            = None,
         )
        │
        ├─ JSONDecodeError → success=False，error 記錄
        └─ Exception       → success=False，error 記錄
```

#### 憑證類別與欄位對應

| 類別 | 欄位 |
|------|------|
| `INVOICE`（統一發票） | `invoice_number`, `seller_name`, `seller_tax_id`, `buyer_tax_id`, `total_amount`, `tax_amount`, `expense_date` |
| `RECEIPT`（收據） | `seller_name`, `total_amount`, `expense_date`, `item_description` |
| `LABOR_SERVICE`（勞報單） | `payee_name`, `id_number`, `net_amount`, `tax_amount`, `total_amount`, `expense_date` |
| `TRANSPORTATION`（交通費） | `from_location`, `to_location`, `total_amount`, `expense_date`, `transport_type` |
| `CREDIT_NOTE`（退貨折讓） | `seller_name`, `invoice_number`, `total_amount`（**負數**）, `expense_date` |

---

### 2.5 Rich Menu 設定

```
LINE Bot 設定（一次性，透過 scripts/setup_rich_menu.py 執行）
        │
        ▼
line_service.setup_rich_menu()
        │
        ├─ 刪除既有 Rich Menu（若存在）
        │       DELETE /v2/bot/richmenu/{id}
        │
        ├─ 建立新 Rich Menu（2500×843，單格全寬）
        │       POST /v2/bot/richmenu
        │       area: { action: Postback(data="action=confirm_submit") }
        │
        ├─ 上傳 Rich Menu 圖片
        │       POST /v2/bot/richmenu/{id}/content
        │
        └─ 套用為 Default Rich Menu（所有使用者）
                POST /v2/bot/user/all/richmenu/{id}
```

**Fallback 機制**：`webhook.py` 同時保留文字 `"確認送出"` → Postback 相同邏輯，防止 Rich Menu 設定失敗時使用者無法操作。

---

### 2.6 特殊情境處理

| 情境 | 處理方式 | DB 狀態變化 |
|------|---------|-----------|
| 按「確認送出」但 pending 為空 | Bot 回覆「尚未收到任何照片 📷」 | 無 |
| 傳送貼圖、語音、影片 | 靜默忽略（`pass`） | 無 |
| OCR 全部失敗（無 total_amount） | 建立 `NEEDS_MANUAL_REVIEW` 狀態的 Expense | 正常建立 |
| 單張 CREDIT_NOTE（折讓單） | total_amount 為負數，PENDING 狀態 | 正常建立 |
| pending 超過 3 小時未送出 | 逾時自動清除（P1 功能，另行排程） | pending 清空 |
| Auto Split（Sprint 3）啟用 | 照片傳送後啟動滑動計時器，N 秒無新圖片自動送出 | 自動觸發 _process_batch |

---

### 2.7 資料一致性保護

| 風險 | 保護機制 |
|------|---------|
| 多個 WebSocket 連線同時寫入 pending_images | `SELECT ... FOR UPDATE`（悲觀鎖） |
| 使用者連按兩次「確認送出」 | 立即清空 pending（先 commit 再加 BackgroundTask） |
| BackgroundTask DB session 與 request session 衝突 | 獨立建立 `SessionLocal()`，最終 `db.close()` |
| 流水號並發碰撞 | IntegrityError 捕捉 + 最多 5 次重試 |

---

---

---

## 機制三：自動切割報帳（Auto Split） {#機制三}

### 3.1 設計目標

使用者在 LINE 聊天視窗**一次性連傳多張照片**（例如：發票 A、發票 B、附件、發票 C），
系統在**最後一張照片送達後靜待 N 秒**，
若期間沒有新照片則自動觸發切割：
以每張 `is_voucher=True` 的憑證圖片作為斷點，將 buffer 切割為**多筆獨立 Expense**，
不需使用者手動按「確認送出」。

> `trigger_by = "auto_split"`（區別於機制二的 `"manual_button"`）

---

### 3.2 觸發條件與開關

| 設定項 | 說明 |
|--------|------|
| `ENABLE_AUTO_SPLIT=true`（`.env`） | 總開關；`false` 時整個機制三不啟動 |
| `AUTO_SPLIT_DEBOUNCE_SECONDS`（`.env`，預設 60） | 滑動視窗長度（秒）；最後一張照片後等待此秒數 |

> ⚠️ **限制**：Auto Split 使用 `asyncio.create_task()` 儲存 per-user Timer，  
> **僅支援 uvicorn 單 Worker 模式**（`--workers 1`）。  
> 多 Worker 下各 Worker 各自持有 `_timers` dict，計時器無法跨 Worker 同步。

---

### 3.3 完整流程

#### 整體架構

```
使用者連傳多張照片（可混合憑證 + 物品照）
        │
        ▼
每張照片觸發：
  webhook.py → download_image → append pending_images（含 timestamp）
              → auto_split_timer.schedule(line_user_id, N秒, callback)
                ← 每次收到新照片都重設計時器（滑動視窗）
        │
        │（N 秒內無新照片）
        ▼
auto_split_timer 到期 → 觸發 _auto_split_callback
        │
        ▼
auto_split_service.auto_split_process()
  ① 讀 pending buffer → 立即清空（防重複觸發）
  ② 依 timestamp ASC 排序
  ③ 序列 OCR（classify_and_extract × N 張）
  ④ multi_split_logic：以 is_voucher=True 作斷點切割
  ⑤ 每個群組呼叫 create_batch_expense（trigger_by="auto_split"）
        │
        ▼
DB：建立 M 筆 Expense（M = 切割後的群組數量）
    每筆各自對應 N 筆 ExpenseImage
```

---

#### 滑動視窗計時器（auto_split_timer）

```
使用者傳照片 #1
        │
        ▼
auto_split_timer.schedule(user_id, 60s, callback)
→ _timers[user_id] = asyncio.create_task(_delayed_call(60, ...))
        │
   （45 秒後使用者傳照片 #2）
        │
        ▼
auto_split_timer.schedule(user_id, 60s, callback)
→ cancel(_timers[user_id])   ← 取消舊計時器（重設視窗）
→ 建立新 Task，重新從 0 計時
        │
        │（60 秒後無新照片）
        ▼
_delayed_call 到期 → await callback()
        │
        ▼
auto_split_service.auto_split_process(...)
```

#### 使用者按「確認送出」時取消計時器

```
使用者按 Rich Menu「確認送出」（PostbackEvent）
        │
        ▼
webhook.py PostbackEvent handler
        │
        ├─ [Auto Split 開啟] auto_split_timer.cancel(line_user_id)
        │     ← 取消自動計時器，改由機制二手動送出流程接管
        │
        └─ 繼續執行機制二的 confirm_submit 邏輯
```

---

#### 自動切割核心：multi_split_logic

```
輸入：
  entries = [img_A, img_B, img_C, img_D, img_E]（依 timestamp 排序）
  ocr_results = [INVOICE, 非憑證, INVOICE, 非憑證, RECEIPT]

切割規則：
  遇到 is_voucher=True  → 收尾前一群組（若有），開啟新群組
  遇到 is_voucher=False + 已有當前群組 → 附加至當前群組（物品照）
  遇到 is_voucher=False + 尚無當前群組 → 獨立成一筆

執行過程：
  img_A（INVOICE）  → current = [A]
  img_B（非憑證）   → current = [A, B]
  img_C（INVOICE）  → 收尾群組 [A,B]，current = [C]
  img_D（非憑證）   → current = [C, D]
  img_E（RECEIPT）  → 收尾群組 [C,D]，current = [E]
  結束              → 收尾群組 [E]

輸出（3 個群組）：
  Group 1: paths=[A,B]  ocr=[INVOICE, 非憑證]  → Expense #1（發票+附件）
  Group 2: paths=[C,D]  ocr=[INVOICE, 非憑證]  → Expense #2（發票+附件）
  Group 3: paths=[E]    ocr=[RECEIPT]           → Expense #3（收據）
```

**邊界情況**：

| 情況 | 切割結果 |
|------|---------|
| 全部為憑證（N 張） | N 個群組，每群組 1 張 |
| 全部非憑證（N 張） | N 個群組，每群組 1 張（各自獨立） |
| 首張是非憑證，後續有憑證 | 首張獨立成一筆，後續依憑證斷點繼續切割 |
| 只有 1 張憑證 + M 張物品照 | 1 個群組（憑證 + 物品照），行為與機制二一致 |
| buffer 為空 | 回傳 `[]`，不建立任何 Expense |

---

#### auto_split_process 完整執行步驟

```
auto_split_process(line_user_id, user_id, uploader_name, uploader_dept)
        │
        ▼
db = SessionLocal()   ← 獨立 DB session
        │
        ▼
state = db.get(UserState, line_user_id)
若 pending 為空 → log + return（靜默，不建立任何紀錄）
        │
        ▼
entries = _parse_buffer(state.pending_images)
← 支援新格式 {path, timestamp, message_id}
   及舊格式純字串（backward compat，timestamp=0）
← 依 timestamp ASC 排序
        │
        ▼
state.pending_images = "[]"   ← 立即清空，防重複觸發
state.pending_description = ""
db.commit()
        │
        ▼
序列 OCR（避免 Gemini RPM 429）：
  for entry in entries:
      result = await ocr_service.classify_and_extract(entry.path)
      ocr_results.append(result)
        │
        ▼
groups = multi_split_logic(entries, ocr_results)
← 純函式，無副作用，可獨立單元測試
        │
        ▼
for idx, (group_paths, group_ocr) in enumerate(groups):
    expense_service.create_batch_expense(
        db           = db,
        user_id      = user_id,
        pending_images = group_paths,
        ocr_results    = group_ocr,
        user_description = pending_description,
        uploader_name    = uploader_name,
        uploader_dept    = uploader_dept,
        trigger_by       = "auto_split",   ← 區別機制二的 "manual_button"
    )
        │
        ▼
db.close()（finally 保證）
```

---

### 3.4 機制二 vs 機制三 對比

| 維度 | 機制二（手動確認送出） | 機制三（Auto Split） |
|------|---------------------|-------------------|
| **觸發方式** | 使用者按 Rich Menu「確認送出」 | 最後一張照片後靜待 N 秒自動觸發 |
| **送出單位** | 全部 pending 合併為 1 筆 Expense | 依憑證圖片斷點切割為 M 筆 Expense |
| **使用者操作** | 需主動按按鈕 | 完全被動，照片傳完等 N 秒自動完成 |
| **trigger_by** | `"manual_button"` | `"auto_split"` |
| **計時器** | 無 | 每張照片重設滑動視窗計時器 |
| **互動關係** | 按確認送出 → 取消 Auto Split 計時器 | Auto Split 到期時若已手動送出 → pending 為空靜默 skip |
| **適用場景** | 使用者有意識地整理多張憑證後送出 | 使用者快速連傳多張照片，每張各自為一筆帳 |

---

### 3.5 涉及模組

```
每張照片收到時（webhook.py）
        │
        ├─ services/auto_split_timer.py
        │     schedule(user_id, delay, callback)
        │     → 管理 asyncio.Task per user（全域 _timers dict）
        │
        └─ callback（定義於 webhook.py 閉包）
               → 捕捉 user_id / uploader_name / dept / line_user_id

Timer 到期時：
        ├─ services/auto_split_service.py
        │     auto_split_process()   ← Timer callback 入口
        │     _parse_buffer()        ← JSON 解析 + timestamp 排序
        │     multi_split_logic()    ← 純函式切割演算法
        │
        ├─ services/ocr_service.py
        │     classify_and_extract() ← 每張圖片獨立 Gemini 呼叫
        │
        └─ services/expense_service.py
              create_batch_expense() ← 建立每個群組的 Expense + ExpenseImage
```

---

### 3.6 新舊格式相容

`pending_images` JSON 在 Sprint 3 從純路徑陣列升級為含 metadata 的物件陣列：

| Sprint | 格式 | 說明 |
|--------|------|------|
| Sprint 2 | `["uploads/a.jpg", "uploads/b.jpg"]` | 純字串路徑 |
| Sprint 3 | `[{"path":"uploads/a.jpg","timestamp":1714000000000,"message_id":"xxx"}]` | 含 LINE 時間戳與訊息 ID |

`_parse_buffer()` 同時支援兩種格式，舊格式 `timestamp=0` 兜底，不拋出錯誤。

---

---

## 共用資料表結構 {#共用資料表結構}

### users

| 欄位 | 類型 | 說明 |
|------|------|------|
| `id` | UUID (PK) | 系統主鍵 |
| `line_user_id` | VARCHAR(64) unique | LINE 平台識別碼 |
| `name` | VARCHAR(128) nullable | LINE 顯示名稱 |
| `real_name` | VARCHAR(128) nullable | 實名綁定姓名 |
| `department` | VARCHAR(128) nullable | **NULL = 尚未完成 Onboarding** |
| `employee_id` | VARCHAR(64) nullable | 員工編號（選配） |
| `created_at` | TIMESTAMPTZ | 首次登錄時間 |

### user_states

| 欄位 | 類型 | 說明 |
|------|------|------|
| `line_user_id` | VARCHAR(64) PK | LINE 使用者識別碼 |
| `step` | VARCHAR(128) | `COLLECTING` / `BINDING_REAL_NAME` / `REUPLOADING_{expense_id}` |
| `dept` | VARCHAR(64) nullable | 此次對話記憶的部門 |
| `pending_images` | TEXT | JSON array of `{path, timestamp, message_id}` |
| `pending_description` | TEXT | 累積的使用者文字備註 |
| `updated_at` | TIMESTAMPTZ | 最後更新時間 |

### expenses

| 欄位 | 類型 | 說明 |
|------|------|------|
| `id` | UUID (PK) | 系統主鍵 |
| `serial_number` | VARCHAR(32) unique | `EXP-YYYYMM-NNNN`（月重置） |
| `user_id` | UUID (FK) | 關聯 users.id |
| `image_url` | VARCHAR(512)[] | 財務憑證圖片路徑陣列 |
| `item_image_url` | VARCHAR(512)[] | 物品影像路徑陣列（非憑證） |
| `uploader_name` | VARCHAR(128) | 上傳者顯示名稱 |
| `uploader_dept` | VARCHAR(64) | 上傳時的部門 |
| `status` | ENUM | `PENDING / APPROVED / REJECTED / NEEDS_MANUAL_REVIEW / SUPPLEMENTED` |
| `total_amount` | NUMERIC(12,2) | **批次模式 = 所有財務憑證金額加總** |
| `invoice_number` | VARCHAR(64) | 主憑證發票號碼 |
| `expense_date` | DATE | 主憑證費用日期 |
| `user_description` | TEXT nullable | 使用者文字備註（批次收集） |
| `image_count` | INT default 1 | 此批次照片總數 |
| `voucher_categories` | TEXT (JSON) | 去重後的憑證類別清單，例：`["INVOICE","TRANSPORTATION"]` |
| `trigger_by` | VARCHAR(32) nullable | `manual_button` / `auto_split` |

### expense_images

| 欄位 | 類型 | 說明 |
|------|------|------|
| `id` | UUID (PK) | 系統主鍵 |
| `expense_id` | UUID (FK, CASCADE) | 關聯 expenses.id |
| `image_url` | VARCHAR(512) | 圖片路徑 |
| `is_voucher` | BOOLEAN | 是否為財務憑證（Gemini 判斷） |
| `voucher_category` | VARCHAR(64) nullable | `INVOICE / RECEIPT / LABOR_SERVICE / TRANSPORTATION / CREDIT_NOTE` |
| `sequence_order` | INT | 上傳順序（1, 2, 3...） |
| `ocr_result` | TEXT (JSON) nullable | Gemini 原始回傳欄位 |
| `created_at` | TIMESTAMPTZ | 建立時間 |

---

## 系統邊界與模組責任 {#系統邊界與模組責任}

| 模組 | 機制一責任 | 機制二責任 | 機制三責任 |
|------|----------|----------|----------|
| `routers/webhook.py` | Onboarding 觸發偵測、部門更新路由、實名綁定狀態路由 | 圖片累積路由、文字累積路由、Postback confirm_submit 路由 | 每張照片後呼叫 `auto_split_timer.schedule()`；confirm_submit 時呼叫 `auto_split_timer.cancel()` |
| `services/auto_split_timer.py` | — | — | 全域 `_timers` dict 管理；`schedule()`（滑動視窗重設）；`cancel()`；`active_count()` |
| `services/auto_split_service.py` | — | — | `auto_split_process()`（Timer callback 入口）；`_parse_buffer()`（JSON 解析 + timestamp 排序）；`multi_split_logic()`（純函式切割演算法） |
| `services/expense_service.py` | `get_or_create_user()`、`update_user_department()`、`update_user_real_name()` | `create_batch_expense()`、`_pick_primary_fields()`、`get_expense_images()` | 複用 `create_batch_expense()`（`trigger_by="auto_split"`） |
| `services/line_service.py` | `reply_with_dept_selection()`、`set_user_state()`、`delete_user_state()` | `download_image()`、`get_user_state()`（讀取 pending） | — |
| `services/ocr_service.py` | — | `classify_and_extract()`（Multi-task Gemini） | 複用 `classify_and_extract()`（序列呼叫） |
| `models/user.py` | `department`、`real_name` 欄位 | — | — |
| `models/user_state.py` | `step` 欄位 | `pending_images`、`pending_description` 欄位 | 複用 `pending_images`（新格式含 `timestamp` + `message_id`） |
| `models/expense.py` | — | `user_description`、`image_count`、`voucher_categories`、`trigger_by`、`images` relationship | `trigger_by="auto_split"` 區別機制二 |
| `models/expense_image.py` | — | 完整定義（`is_voucher`、`voucher_category`、`sequence_order`、`ocr_result`） | 複用（每個切割群組各自建立 N 筆） |
| `core/config.py` | `departments`（.env 解析）、`enable_user_binding` | `storage_path` | `enable_auto_split`、`auto_split_debounce_seconds` |

---

*文件維護：每次 Sprint 有變動時同步更新本文件，版本號遞增。*
