# Sprint 提案書：Sprint 2 — 多張照片批次報帳（Batch Expense）

> **專案**: AcctAssist（LINE Bot 智能報帳系統）
> **提案人**: product-manager
> **日期**: 2026-04-10
> **Sprint 編號**: S2
> **版本**: v2（依老闆指示更新：簡化 UX、Rich Menu 常駐確認按鈕、部門一次性設定）
> **狀態**: 待 G0 審核

---

## 1. Sprint 背景與目標

### 1.1 背景

現有系統每次報帳需要重複選部門、每次只能傳一張照片，操作繁瑣。
本次 Sprint 做兩件事：

1. **簡化操作流程**：部門只在第一次使用時設定一次，之後永久記錄，不再每次詢問。
2. **批次報帳**：直接傳照片（可多張）+ 文字備註，完成後按畫面底部常駐的「確認送出」按鈕，所有內容合併為一筆報帳紀錄。

舊流程的「我要報帳」觸發按鈕與「查看審核結果」按鈕一併移除，Rich Menu 只保留一個「確認送出」功能鍵。

### 1.2 Sprint 目標

| # | 目標 | 衡量標準 |
|---|------|---------|
| 1 | 部門一次性設定 | 首次使用後，後續傳照片不再詢問部門 |
| 2 | Rich Menu 常駐確認按鈕 | LINE 聊天視窗底部永遠顯示「確認送出」一個按鈕 |
| 3 | 多照片批次收集 | 可連續接收 ≥ 5 張照片不觸發送出 |
| 4 | 憑證類型自動辨識 | OCR 能分類 6 種類型，準確率 ≥ 85% |
| 5 | 多張照片彙整為一筆 | 一次批次 → 一筆 Expense + 多筆 ExpenseImage |
| 6 | 文字說明整合 | 使用者打字備註正確寫入 `user_description` |

---

## 2. 目標用戶

| 角色 | 使用情境 | 改善前的痛點 |
|------|---------|------------|
| **報帳人員** | 一次出差有 4–6 張憑證，希望一次傳完按一下就送出 | 每張都要重新選部門、一次只能傳一張 |
| **財務審核人員** | 一筆報帳事件看到所有憑證與說明 | 同一事件的憑證分散在多筆紀錄 |

---

## 3. 核心功能範圍

### P0 — 必須完成（阻斷發布）

| 功能 | 說明 |
|------|------|
| **[新] LINE Rich Menu（單按鈕）** | 移除所有舊按鈕，Rich Menu 只保留一個「✅ 確認送出」Postback 按鈕，常駐於聊天視窗底部 |
| **[新] 部門一次性設定（首次 Onboarding）** | 使用者第一次傳訊息時詢問部門，選定後寫入 `users.department`，後續永不再問 |
| **[移除] 「我要報帳」觸發流程** | 不再需要主動觸發；傳照片即開始收集 |
| **[移除] 「查看審核結果」按鈕** | 從 Rich Menu 移除 |
| 批次收集狀態（`COLLECTING`） | `UserState` 負責累積 `pending_images`、`pending_description`；永遠處於收集模式 |
| `ExpenseImage` 資料表 | 一對多：一筆 Expense 對應多筆 ExpenseImage（含 `image_category`、`ocr_result`） |
| 多圖 OCR 辨識 | 每張圖片獨立呼叫 Gemini：先判斷是否為財務憑證，若是則同時辨識憑證類別（6 種）並萃取財務欄位，結果寫入 `voucher_category` |
| 費用彙整邏輯 | `total_amount` = 所有財務憑證加總；主憑證欄位取第一張財務憑證 |
| `user_description` 欄位 | Expense 表新增欄位，收集批次中所有使用者文字訊息 |
| Dashboard 顯示多圖 | 詳情頁展示所有子圖片 + 各自 `voucher_category` 標籤；報帳清單新增「憑證類別」欄位 |

### P1 — 應完成（體驗提升）

| 功能 | 說明 |
|------|------|
| 即時圖片計數回饋 | 每收到一張圖片，Bot 立即回覆「已收到第 N 張，按確認送出完成這筆」 |
| 批次摘要回覆 | 送出後推送結構化摘要（憑證類型清單 + 合計金額 + 說明） |
| 空批次防護 | 按確認送出時 pending 為空，Bot 回覆「尚未收到任何照片」，不建立空紀錄 |
| 逾時自動清除 | 超過 3 小時無任何訊息，自動清除 pending 並通知「上次未送出的照片已清除」 |

### P2 — 可延後（未來 Sprint）

| 功能 | 說明 |
|------|------|
| Dashboard 多圖縮圖 Grid | 詳情頁以 Grid 方式展示所有圖片縮圖 |
| 重新辨識單張圖片 | 財務人員可在 Dashboard 對辨識錯誤的圖片重觸 OCR |
| 人工標記憑證類型 | Dashboard 允許財務手動修改 `image_category` |
| 部門修改指令 | 使用者輸入指令重新設定部門（e.g. 「修改部門」） |

---

## 4. 範圍界定

### 做（Sprint 2 範圍內）
- **LINE Rich Menu 建立**：呼叫 LINE API 建立僅含「確認送出」的 Rich Menu，並套用至 Bot
- **首次 Onboarding**：首次偵測 + 部門 Quick Reply + 寫入 `users.department`（一次性）
- **移除舊 Rich Menu 與按鈕邏輯**：清除 `webhook.py` 中的「我要報帳」文字觸發與「查看審核結果」觸發
- `UserState` 表新增 `pending_images`（JSON）、`pending_description`（TEXT）欄位
- 新建 `expense_images` 資料表（含 Alembic migration）
- `Expense` 表新增 `user_description`（TEXT）、`image_count`（INT）欄位
- 多圖批次 OCR 流程（`ocr_service.py` 新增 `classify_and_extract()`）
- 費用彙整服務（`expense_service.py` 新增 `create_batch_expense()`）
- Postback handler for "確認送出"（`webhook.py`）
- Dashboard 詳情頁顯示多圖資訊（Vue3 更新）
- 批次送出後的摘要 Flex Message

### 不做（明確排除）
- 「查看審核結果」LINE Bot 功能（保留在 Dashboard 網頁）
- 多語言支援
- 部門清單 Dashboard 動態管理頁面（選用方案 B：.env 設定）
- 多圖比對去重（Phase 3）
- 圖片壓縮或轉檔（Phase 3）
- 修改 Dashboard 審核操作邏輯（延續 Sprint 1 行為）

---

## 5. 技術設計

### 5.1 新使用者流程（狀態機）

#### 首次使用（Onboarding）

```
使用者第一次傳送任何訊息（包含照片）
    ↓
webhook.py 偵測：users.department IS NULL
    ↓
Bot: 「👋 歡迎使用 AcctAssist！
       請先選擇您的所屬組別（只需設定一次）：」
       + Quick Reply [製片組] [美術組] [攝影組] [燈光組] [其他]
    ↓
使用者點選部門
    ↓
寫入 users.department（永久）
Bot: 「✅ 已設定為「攝影組」
       您可以直接傳送憑證照片，
       完成後按畫面下方「確認送出」即可 📋」
    ↓
後續永不詢問部門（除非使用者主動輸入修改指令）
```

#### 日常使用（已設定部門）

```
使用者直接傳送照片 1
    ↓ （無需任何觸發詞）
Bot: 「📷 已收到第 1 張，可繼續傳送其他照片或文字說明
       完成後按畫面下方「確認送出」」
    ↓
使用者傳照片 2、3…（或打字說明）
    → 每張照片：Bot 回覆「📷 已收到第 N 張」
    → 每段文字：Bot 回覆「📝 備註已記錄」
    ↓
    ┌───────────────────────────────────────┐
    │  LINE 聊天視窗底部（Rich Menu 常駐）     │
    │  ┌─────────────────────────────────┐  │
    │  │        ✅  確認送出               │  │
    │  └─────────────────────────────────┘  │
    └───────────────────────────────────────┘
    ↓ 使用者按下「確認送出」
Bot: 「⏳ 處理中，請稍候…」（< 500ms 立即回覆）
    ↓ BackgroundTask：OCR 所有圖片 → 分類 → 彙整 → 建立 Expense + ExpenseImage
    ↓
Bot push: 批次摘要 Flex Message（見 5.6）
    ↓
pending 清空，等待下一批次（Rich Menu 按鈕持續常駐）
```

#### 特殊情境處理

| 情境 | Bot 回應 | 狀態變化 |
|------|---------|---------|
| 按「確認送出」但 pending 為空 | 「尚未收到任何照片，請先傳送憑證」 | 無變化 |
| 傳送貼圖、語音、影片 | 「目前僅支援照片與文字說明」 | 無變化 |
| pending 超過 3 小時未送出 | push「上次未送出的 N 張照片已自動清除」 | pending 清空 |
| 首次 Onboarding 期間傳照片 | 「請先選擇組別後再傳送照片」+ 再次顯示 Quick Reply | 等待部門選擇 |

---

### 5.2 部門清單設定方式（方案 B：.env）

部門清單透過環境變數管理，不寫死在程式碼內。

**.env 設定（範例）**
```
DEPARTMENTS=製片組,美術組,攝影組,燈光組,場務組,其他
```

**core/config.py 讀取**
```python
departments: list[str] = Field(default=["製片組", "美術組", "攝影組", "燈光組", "其他"])

@validator("departments", pre=True)
def parse_departments(cls, v):
    if isinstance(v, str):
        return [d.strip() for d in v.split(",") if d.strip()]
    return v
```

**效果**：想新增或修改組別，只需編輯伺服器上的 `.env` 並重啟服務，LINE Bot 的部門選單自動更新，**不需動程式碼、不需重新部署**。

> `.env.example` 同步維護 `DEPARTMENTS` key，供新環境參考。

---

### 5.3 LINE Rich Menu 設計

```
Rich Menu 規格：
  - 尺寸：2500 × 843（LINE 標準，1 格全寬）
  - 顯示文字：「✅ 確認送出」
  - 動作類型：Postback（data="action=confirm_submit"）
  - 顯示時機：永遠顯示（set as default rich menu）
  - 移除舊 Rich Menu（若 Sprint 1 有設定）
```

```
視覺示意（LINE 聊天畫面底部）：
┌─────────────────────────────────────────┐
│                                          │
│            ✅  確認送出這筆               │
│                                          │
└─────────────────────────────────────────┘
```

> **注意**：Rich Menu 需透過 LINE Messaging API 的 `/v2/bot/richmenu` 建立並套用。
> 建議新增 `scripts/setup_rich_menu.py` 一次性設定腳本，不寫入 `webhook.py`。

---

### 5.4 資料庫變更

#### 新增 `expense_images` 表

```python
class ExpenseImage(Base):
    __tablename__ = "expense_images"
    id               : UUID (PK)
    expense_id       : UUID (FK → expenses.id, CASCADE DELETE)
    image_url        : str              # uploads/{uuid}.jpg
    is_voucher       : bool             # True=財務憑證、False=品項照片或無法辨識
    voucher_category : str | null       # 見 5.5；is_voucher=False 時為 null
    sequence_order   : int              # 上傳順序 (1, 2, 3...)
    ocr_result       : JSON (nullable)  # Gemini 原始回傳（is_voucher=True 才有值）
    created_at       : datetime
```

> `is_voucher` 控制是否做財務萃取；`voucher_category` 是業務分類，直接對應 Dashboard 的「憑證類別」欄位。

#### 修改 `expenses` 表（新增欄位，不動現有欄位）

| 欄位 | 類型 | 說明 |
|------|------|------|
| `user_description` | TEXT (nullable) | 使用者文字備註（批次中的文字訊息合併） |
| `image_count` | INT (default 1) | 此批次共幾張圖片 |
| `voucher_categories` | TEXT (JSON array, nullable) | 此批次所有財務憑證的類別清單，供 Dashboard 快速顯示。例：`["發票", "車費", "收據"]` |

> 既有欄位（`total_amount`、`invoice_number` 等）語意調整為「主憑證的資料」，不影響欄位名稱與型別。

#### 修改 `user_states` 表（新增欄位，不動現有欄位）

| 欄位 | 類型 | 說明 |
|------|------|------|
| `pending_images` | TEXT (JSON, default '[]') | 累積的圖片路徑列表 |
| `pending_description` | TEXT (default '') | 累積的文字說明 |

> `step` 欄位原值 `WAITING_PHOTO` 統一 migration 至 `COLLECTING`。
> `dept` 欄位保留（作為當次批次部門冗余備份），但主要部門來源改為 `users.department`。

#### `users` 表（既有欄位，新增語意說明）

| 欄位 | 類型 | 說明（更新後） |
|------|------|--------------|
| `department` | str \| null | **一次性設定後永久保留**；null 表示尚未完成 Onboarding |

---

### 5.5 憑證類別定義（`voucher_category`）

OCR 的分類分為**兩層**：

**第一層：是否為財務憑證（`is_voucher`）**

| 值 | 說明 | OCR 行為 |
|----|------|---------|
| `true` | 財務憑證（有金額、有業務意義） | 同時進行第二層分類 + 萃取財務欄位 |
| `false` | 品項照片 或 無法辨識 | 不萃取財務欄位，`voucher_category` 為 null |

**第二層：憑證類別（`voucher_category`）— 僅 `is_voucher=true` 時填入**

各類別的辨識特徵與萃取欄位如下：

#### 1. 發票 `INVOICE`
| 萃取欄位 | 說明 |
|---------|------|
| `invoice_number` | 發票號碼（格式：2碼英文 + 8碼數字，如 AB12345678） |
| `seller_tax_id` | 賣方統一編號（8碼數字） |
| `buyer_tax_id` | 買方統一編號（8碼數字，B2B 才有） |
| `expense_date` | 發票日期（YYYY-MM-DD） |
| `total_amount` | 總金額（含稅） |
| `tax_amount` | 稅額 |
| `tax_type` | 課稅別（應稅 / 零稅率 / 免稅） |

#### 2. 收據 `RECEIPT`
| 萃取欄位 | 說明 |
|---------|------|
| `seller_name` | 店名 / 收款方名稱 |
| `expense_date` | 消費日期（YYYY-MM-DD） |
| `total_amount` | 總金額 |
| `has_exempt_stamp` | 是否有「免用統一發票」章（true / false） |

#### 3. 勞報 `LABOR_SERVICE`
| 萃取欄位 | 說明 |
|---------|------|
| `payee_name` | 收款人姓名 |
| `payee_id` | 身分證字號（1碼英文 + 9碼數字） |
| `total_amount` | 申報總金額（含預扣所得稅） |
| `net_amount` | 實領金額（扣稅後） |
| `labor_content` | 勞務內容說明 |

#### 4. 交通 `TRANSPORTATION`
| 萃取欄位 | 說明 |
|---------|------|
| `expense_date` | 乘車/使用日期（YYYY-MM-DD） |
| `transport_type` | 交通工具類型（高鐵 / 台鐵 / 捷運 / 計程車 / 客運 / 停車 / 其他） |
| `route_from` | 起點 |
| `route_to` | 迄點（停車費填停車地點） |
| `total_amount` | 金額 |

#### 5. 退貨折讓 `CREDIT_NOTE`
| 萃取欄位 | 說明 |
|---------|------|
| `original_invoice_number` | 原始發票號碼 |
| `expense_date` | 折讓日期（YYYY-MM-DD） |
| `total_amount` | 折讓金額（**必須轉為負數**，例：-1200） |

> **分類邏輯**：Gemini 單次呼叫同時完成 `is_voucher` 判斷 + `voucher_category` 分類 + 各類別專屬欄位萃取，避免多次 API 呼叫。
> `voucher_category` 結果直接寫入 Dashboard 的「憑證類別」欄位，財務人員無需手動填寫。

---

### 5.6 費用彙整規則

```
主憑證欄位（expense.invoice_number, seller_name, expense_date）
  → 優先取第一張 INVOICE，若無則依序取 RECEIPT → LABOR_SERVICE → TRANSPORTATION

total_amount（expense.total_amount）
  → sum(所有 is_voucher=true 且 total_amount 非 null 的圖片金額)
  → CREDIT_NOTE（退貨折讓）的 total_amount 已為負數，直接加總自動扣除
  → 若所有金額為 null → total_amount 為 null

voucher_categories（expense.voucher_categories）
  → 蒐集此批次所有 is_voucher=true 的 voucher_category，去重後存為 JSON array
  → 例：["INVOICE", "TRANSPORTATION", "RECEIPT"]
  → Dashboard 顯示時轉為中文：發票 / 收據 / 勞報 / 交通 / 退貨折讓

user_description
  → 批次中所有文字訊息以換行合併

status 判斷
  → total_amount != null → PENDING（等待財務審核，含負數或 0 的情況）
  → total_amount 為 null（全部辨識失敗）→ NEEDS_MANUAL_REVIEW

image_count → len(pending_images)
```

---

### 5.7 OCR 服務擴充（`ocr_service.py`）

```python
# 新增方法（不修改現有 extract_invoice_data，保留舊介面相容）
async def classify_and_extract(image_path: str) -> ImageOCRResult:
    """
    單次 Gemini 呼叫完成三件事：
    1. 判斷是否為財務憑證（is_voucher）
    2. 若是 → 辨識憑證類別（voucher_category）
    3. 若是 → 萃取財務欄位（金額、發票號碼等）
    """

MULTI_TASK_PROMPT = """
你是財務憑證辨識 AI，專門處理台灣的報帳憑證。
請分析圖片，先判斷是否為財務憑證，再依類別萃取對應欄位，以 JSON 回傳。

【第一步：判斷 is_voucher】
- true：圖片為財務憑證（含金額的正式文件）
- false：品項照片、模糊照片、非財務文件 → 回傳 {"is_voucher": false, "voucher_category": null, "fields": null}

【第二步：判斷 voucher_category 並萃取欄位】

若 is_voucher = true，依下列規則判斷類別並回傳對應 fields：

■ INVOICE（發票）：含「統一發票」字樣或發票號碼（2碼英文+8碼數字）
{
  "is_voucher": true,
  "voucher_category": "INVOICE",
  "fields": {
    "invoice_number": "AB12345678",
    "seller_tax_id": "12345678",
    "buyer_tax_id": null,
    "expense_date": "YYYY-MM-DD",
    "total_amount": 1200,
    "tax_amount": 57,
    "tax_type": "應稅 | 零稅率 | 免稅"
  }
}

■ RECEIPT（收據）：有金額與店章，但非統一發票
{
  "is_voucher": true,
  "voucher_category": "RECEIPT",
  "fields": {
    "seller_name": "店名",
    "expense_date": "YYYY-MM-DD",
    "total_amount": 500,
    "has_exempt_stamp": true
  }
}

■ LABOR_SERVICE（勞報單）：含「勞務報酬」、「勞報」、身分證字號
{
  "is_voucher": true,
  "voucher_category": "LABOR_SERVICE",
  "fields": {
    "payee_name": "王小明",
    "payee_id": "A123456789",
    "total_amount": 10000,
    "net_amount": 9000,
    "labor_content": "拍攝剪接作業"
  }
}

■ TRANSPORTATION（交通）：交通票根、計程車收據、停車費
{
  "is_voucher": true,
  "voucher_category": "TRANSPORTATION",
  "fields": {
    "expense_date": "YYYY-MM-DD",
    "transport_type": "高鐵 | 台鐵 | 捷運 | 計程車 | 客運 | 停車 | 其他",
    "route_from": "台北",
    "route_to": "台中",
    "total_amount": 375
  }
}

■ CREDIT_NOTE（退貨折讓）：含「退貨」、「折讓」、「退款」字樣
{
  "is_voucher": true,
  "voucher_category": "CREDIT_NOTE",
  "fields": {
    "original_invoice_number": "AB12345678",
    "expense_date": "YYYY-MM-DD",
    "total_amount": -1200
  }
}

注意：CREDIT_NOTE 的 total_amount 必須為負數。
無法辨識的欄位填 null，不要猜測。
"""
```

---

### 5.8 Flex Message 設計

#### A. 送出後的批次摘要

```
┌─────────────────────────────────┐
│  ✅ 報帳已送出                    │
│  ─────────────────────────────  │
│  🧾 發票     × 1     NT$2,400   │
│  🚌 交通     × 2     NT$680     │
│  📋 收據     × 1     NT$350     │
│  ↩️  退貨折讓 × 1    -NT$500    │
│  📦 品項照片 × 1     (無金額)    │
│  ─────────────────────────────  │
│  合計金額：NT$2,930              │
│  所屬組別：攝影組                 │
│  備註：高鐵票和計程車費           │
│                                  │
│  案件編號：2026-0042             │
└─────────────────────────────────┘
```

> 憑證類別圖示對照：發票 🧾 / 收據 📋 / 勞報 👤 / 交通 🚌 / 退貨折讓 ↩️ / 品項照片 📦

> 摘要訊息使用 `push_message`（非 reply），確保 BackgroundTask 完成後才發送。
> 不含「繼續報帳」或「結束」按鈕（Rich Menu 確認按鈕已常駐，無需引導）。

---

## 6. 風險評估

| 風險 | 影響 | 可能性 | 緩解方式 |
|------|------|--------|---------|
| Rich Menu API 設定錯誤導致按鈕不顯示 | 使用者無法送出批次 | 中 | 準備 `scripts/setup_rich_menu.py` 可重複執行；webhook.py 同時保留 TEXT 觸發「確認送出」作為 fallback |
| 多圖 OCR 超時（5 張 × ~5 秒 = 25 秒）超過 LINE 5 秒 Webhook 限制 | 使用者收不到確認 | 高 | Postback 收到後立即 reply「⏳ 處理中」，OCR 改用 BackgroundTask + push_message 推送結果 |
| Gemini RPM 限制（免費版）導致批次 OCR 失敗 | 大量 NEEDS_MANUAL_REVIEW | 中 | 序列執行（非並行）；失敗時記錄錯誤日誌，狀態設 NEEDS_MANUAL_REVIEW 並通知使用者 |
| 舊版 `WAITING_PHOTO` 狀態遷移後使用者卡住 | 舊用戶無法操作 | 中 | Migration 時 `WAITING_PHOTO` → `COLLECTING`；pending_images 預設空陣列 |
| 首次 Onboarding 中傳照片（部門未設定）導致照片遺失 | 使用體驗差 | 中 | 偵測到首次使用時，先記錄照片至 pending，部門設定完成後繼續收集，不丟棄 |
| `pending_images` 競態（同一用戶快速傳多張） | 圖片遺失或重複 | 低 | DB transaction + `SELECT FOR UPDATE` 保護 append 操作 |

---

## 7. 步驟與關卡規劃

### 勾選的步驟

- [x] 需求分析（G0）
- [x] UI 圖稿（G1）— **需要**（Rich Menu 視覺稿 + 批次摘要 Flex Message 設計稿）
- [x] 實作（G2）
- [x] 測試（G3）
- [x] 文件（G4）
- [ ] 部署（G5）— **不需要**（沿用 Sprint 1 部署環境）
- [ ] 發佈（G6）— **不需要**

### 阻斷規則

- **G1 阻斷**：Rich Menu 視覺稿與 Flex Message 設計稿未通過審核前，不得開始實作 LINE 訊息相關功能
- **G3 阻斷**：批次流程 E2E 測試未通過，不得進入文件階段

### 關卡序列

```
G0（需求確認）→ G1（設計審核）→ G2（程式碼審查）→ G3（測試驗收）→ G4（文件審查）
```

---

## 8. 初步時程

| # | 階段 | 工作內容 | 預估時間 | 交付物 |
|---|------|---------|---------|--------|
| — | G0 規劃 | 開發計畫書、任務拆解 | 0.5 天 | `sprint2-dev-plan.md` |
| T1 | 設計（→G1） | Rich Menu 視覺稿 + 批次摘要 Flex Message mockup | 1 天 | `static/mockup/sprint2/` |
| T2 | Rich Menu 設定 | LINE API 建立 Rich Menu、`scripts/setup_rich_menu.py` | 0.5 天 | `scripts/setup_rich_menu.py` |
| T3 | DB Migration | 3 個 migration（expense_images、expenses 新欄位、user_states 新欄位） | 0.5 天 | `alembic/versions/` |
| T4 | OCR 擴充 | `classify_and_extract()`、新 Prompt、`ImageOCRResult` schema | 1.5 天 | `services/ocr_service.py` |
| T5 | Webhook 重構 | 移除舊觸發邏輯、新增 Postback handler、首次 Onboarding 偵測、批次收集流程 | 2 天 | `routers/webhook.py`、`services/line_service.py` |
| T6 | 費用彙整服務 | `create_batch_expense()`、彙整規則、ExpenseImage CRUD | 1 天 | `services/expense_service.py` |
| T7 | Dashboard 更新 | 詳情頁顯示多圖 + 類型標籤 + `user_description` | 1 天 | `frontend/` |
| T8 | 測試 | 單元測試 + E2E（首次 Onboarding、批次流程 mock） | 2 天 | `tests/` |
| T9 | 文件 | API 規格更新、LINE Bot 操作說明更新 | 0.5 天 | `.knowledge/` |
| | **總計** | | **約 10.5 天** | |

---

## 9. 團隊組成

| 角色 | Agent | 負責任務 |
|------|-------|---------|
| Product Manager (L1) | product-manager | G0 規劃、PM Review、Gate 審核呈報 |
| Tech Lead (L1) | tech-lead | 開發計畫書、任務拆解、Code Review |
| Designer (L2) | designer | T1（Rich Menu 視覺稿 + Flex Message） |
| Backend Dev (L2) | backend-dev | T2、T3、T4、T5、T6 |
| Frontend Dev (L2) | frontend-dev | T7（Dashboard 多圖顯示） |
| QA (L2) | qa-engineer | T8（測試套件） |
| Tech Writer (L2) | tech-writer | T9（文件更新） |

---

## 10. 驗收標準（G0 Checklist）

### Rich Menu 驗收
- [ ] LINE 聊天底部永遠顯示「確認送出」按鈕（Rich Menu），不顯示舊有按鈕
- [ ] 「確認送出」正確觸發 Postback（data="action=confirm_submit"）
- [ ] 舊的「我要報帳」與「查看審核結果」按鈕已完全移除

### 首次 Onboarding 驗收
- [ ] 新用戶傳任何訊息（含照片）都觸發部門選擇，不直接進入收集流程
- [ ] 部門選定後寫入 `users.department`，後續操作不再詢問
- [ ] Onboarding 期間傳入的照片不丟失（保留至 pending）

### 批次收集驗收
- [ ] 已設定部門的使用者直接傳照片可進入收集，無需任何觸發詞
- [ ] 可連續收集 ≥ 5 張照片，Bot 正確計數回饋
- [ ] 使用者文字訊息正確附加至 `pending_description`
- [ ] 貼圖、語音等非支援類型回覆提示，不破壞 pending 狀態
- [ ] 按「確認送出」時 pending 為空，Bot 提示「尚未收到照片」，不建立空紀錄
- [ ] 按「確認送出」後立即回覆「⏳ 處理中」（< 500ms）

### OCR 與分類驗收
- [ ] `is_voucher` 判斷正確：財務憑證回傳 true，品項照片/模糊圖片回傳 false
- [ ] 5 種 `voucher_category`（INVOICE / RECEIPT / LABOR_SERVICE / TRANSPORTATION / CREDIT_NOTE）均可正確辨識（測試集準確率 ≥ 85%）
- [ ] 各類別萃取正確的專屬欄位（發票萃取統編/課稅別；勞報萃取身分證/實領金額；交通萃取起訖點；依此類推）
- [ ] `voucher_category` 正確寫入 `expense_images.voucher_category` 並顯示於 Dashboard「憑證類別」欄位
- [ ] `is_voucher=false` 的圖片不萃取財務欄位，`voucher_category` 為 null，`fields` 為 null
- [ ] CREDIT_NOTE 的 `total_amount` 正確為負數，加總時自動扣除
- [ ] `total_amount` 正確加總多張憑證（含部分 null、含退貨折讓負數的場景）
- [ ] `expenses.voucher_categories` JSON array 正確彙整去重，Dashboard 顯示中文名稱

### 資料庫驗收
- [ ] `expense_images` 表正確建立，FK 關聯與 CASCADE DELETE 正確
- [ ] `expenses.user_description` 與 `image_count` 正確寫入
- [ ] 批次 OCR 全部失敗時 `status` 正確設為 `NEEDS_MANUAL_REVIEW`
- [ ] 舊的 `WAITING_PHOTO` state migration 後正確變為 `COLLECTING`

### Dashboard 驗收
- [ ] 詳情頁正確顯示所有子圖片清單（URL + 類型標籤 + OCR 金額摘要）
- [ ] `user_description` 欄位正確顯示

### 測試驗收
- [ ] 首次 Onboarding E2E 測試通過（mock LINE API）
- [ ] 批次收集完整流程 E2E 測試通過（mock LINE API + mock Gemini）
- [ ] `ocr_service.classify_and_extract()` 單元測試覆蓋率 ≥ 80%
- [ ] `expense_service.create_batch_expense()` 費用彙整規則測試通過（多財務憑證、含 null 金額）
- [ ] 空批次防護、貼圖防護邊界測試通過

---

## 11. 已知問題與技術債

| # | 問題 | 嚴重度 | 處理計畫 |
|---|------|--------|---------|
| LINE Webhook 超時 | 多圖 OCR 超過 5 秒限制 | 高 | T5 強制使用 BackgroundTasks + push_message，Postback 立即 reply |
| Gemini 序列執行速度慢 | 5 張需 ~25 秒才能收到摘要 | 中 | 接受此限制（push 非同步不影響 UX）；未來可升級 Gemini API 等級加速 |

---

## 12. 不在此 Sprint 的功能（Backlog）

| 功能 | 優先級 | 預估 Sprint |
|------|--------|------------|
| 部門修改指令（輸入「修改部門」重新設定） | P1 | Sprint 3 |
| 重複發票偵測（發票號碼去重） | P1 | Sprint 3 |
| Dashboard 多圖縮圖 Grid | P2 | Sprint 3 |
| 人工重新辨識單張圖片 | P2 | Sprint 4 |
| 逾時自動清除 pending（3 小時） | P1 | Sprint 3 |

---

## 13. 本次重大設計決策記錄

> 記錄本次與 v1 提案的主要差異，供後續 Sprint 參考。

| 決策 | v1 設計 | v2 設計（本版）| 原因 |
|------|--------|--------------|------|
| 按鈕數量 | Rich Menu 含「我要報帳」+「查看審核結果」+「確認送出」 | 只有「確認送出」 | 簡化操作，報帳無需主動觸發 |
| 部門選擇 | 每次報帳都選擇部門 | 首次設定，永久記錄 | 減少重複操作，提升效率 |
| 觸發方式 | 需要先按「我要報帳」 | 直接傳照片即開始收集 | 降低操作步驟 |
| 送出後流程 | 詢問「是否繼續報下一筆？」含[繼續][結束]按鈕 | 直接顯示摘要，Rich Menu 常駐可直接繼續 | 簡化 UX，避免不必要的確認步驟 |
| 部門清單管理 | 靜態寫死在 config | 方案 B：.env 環境變數設定 | 不需改程式碼，改 .env 重啟即生效 |
| pending 逾時 | 2 小時 | **3 小時** | 避免拍攝現場忙碌時照片被過早清除 |
| 憑證類別（第二層） | 6 類（含押金/車費） | **5 類**（INVOICE / RECEIPT / LABOR_SERVICE / TRANSPORTATION / CREDIT_NOTE），各自萃取專屬欄位 | 對應真實報帳業務類型，去除不常用的押金類別 |

---

## 14. 參考文件

| 文件 | 路徑 |
|------|------|
| 專案開發規範 | `CLAUDE.md` |
| 現有系統架構 | `.knowledge/project-overview.md` |
| 踩坑紀錄 | `.knowledge/postmortem-log.md` |
| Sprint 1 提案 | `proposal/sprint1-proposal.md` |
| 共用開發規則 | `.knowledge/company-rules.md` |

---

**老闆決策**: [x] 通過進入 G0 / [ ] 調整範圍 / [ ] 擱置

> G0 通過時間：2026-04-11　審核人：老闆

> 備註：G0 審核通過後，Tech Lead 將產出 `sprint2-dev-plan.md` 並進行任務拆解。
> G1 審核重點：Rich Menu 視覺稿（單按鈕佈局）+ 批次摘要 Flex Message 是否符合 LINE 設計規範。
