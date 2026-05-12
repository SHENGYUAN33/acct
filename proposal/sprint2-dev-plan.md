# 開發計畫書: Sprint 2 — 多張照片批次報帳（Batch Expense）

> **撰寫者**: product-manager (PM / L1)
> **日期**: 2026-04-11
> **專案**: AcctAssist（LINE Bot 智能報帳系統）
> **Sprint 提案書**: `proposal/sprint2-proposal.md`
> **狀態**: ✅ G4 通過，Sprint 2 封版（2026-04-11）

---

> 本文件在 G0 通過後由 PM 撰寫，依據提案書中勾選的步驟展開技術細節。

## 1. 需求摘要

### 背景

現有報帳流程每次需重新選部門、每次只能傳一張照片，操作繁瑣。
Sprint 2 做兩件事：

1. **簡化操作流程**：部門首次設定後永久記錄（Onboarding），後續無需再選。
2. **批次報帳**：傳送多張照片 + 文字備註，按 LINE 底部常駐的「確認送出」Rich Menu 按鈕，合併為一筆 Expense + 多筆 ExpenseImage。

同時移除舊有的「我要報帳」TextMessage 觸發流程與「查看審核結果」Rich Menu 按鈕，Rich Menu 只保留一個「確認送出」功能鍵。

### 確認的流程

```
G0（需求確認）✅ → 設計（T1）→ G1（設計審核）
    → 實作（T2/T3/T4/T5/T6/T7 依依賴並行）→ G2（程式碼審查）
    → 測試（T8）→ G3（測試驗收）
    → 文件（T9）→ G4（文件審查）
```

**關卡序列**：G0 → G1 → G2 → G3 → G4

**阻斷規則**：
- **G1 阻斷**：T1 設計稿（Rich Menu 視覺稿 + 批次摘要 Flex Message）未通過 G1 審核前，T5 中 LINE 訊息格式相關實作（`push_batch_summary()` 的 Flex Message 結構）不得開始
- **G3 阻斷**：T8 批次流程 E2E 測試未通過，不得進入 T9 文件階段

---

## 2. 技術方案

### 2.1 多圖批次收集架構

**選定方案：UserState 累積 + Postback 觸發送出**

```
使用者傳照片
    ↓
webhook.py 偵測 users.department（是否為首次使用）
    ↓
[首次] → Onboarding Quick Reply（只需一次）
[非首次] → append image_path 至 UserState.pending_images（JSON array）
           → push 即時計數回饋「已收到第 N 張」
    ↓
使用者按 Rich Menu「確認送出」→ Postback(action=confirm_submit)
    ↓
立即 reply「⏳ 處理中」（< 500ms）
    ↓
BackgroundTask：classify_and_extract（序列執行）→ create_batch_expense()
    ↓
push_batch_summary（Flex Message）
    ↓
UserState.pending_images 清空
```

**UserState 永遠處於 COLLECTING 模式**（舊 WAITING_PHOTO 透過 data migration 轉換），無需手動觸發啟動批次。

| 方案 | 優點 | 缺點 | 結論 |
|------|------|------|------|
| A: UserState 累積 + Postback 觸發 | 不需外部 Queue、架構簡單、即時計數 | pending 存 DB，大量圖片 JSON 稍大 | ✅ 選定 |
| B: Redis Queue + Worker | 效能佳、可擴展 | 引入新依賴、複雜度高、小系統殺雞用牛刀 | ❌ 排除 |

### 2.2 OCR 擴充方案（保留舊介面不動）

**選定方案：新增 `ImageOCRResult` + `classify_and_extract()` 並列**

- **`extract_invoice_data()`**：**不修改**，Sprint 1 既有功能保持完整
- **新增 `ImageOCRResult`** dataclass：
  ```python
  @dataclass
  class ImageOCRResult:
      is_voucher: bool
      voucher_category: str | None        # INVOICE / RECEIPT / LABOR_SERVICE / TRANSPORTATION / CREDIT_NOTE
      fields: dict | None                 # 各類別專屬欄位
      raw_response: str
      success: bool
      error: str | None
  ```
- **新增 `classify_and_extract(image_path)`**：單次 Gemini 呼叫完成判斷 + 分類 + 萃取
- **序列執行**（非並行）：避免 Gemini 免費版 RPM 限制觸發 429 錯誤

| 方案 | 優點 | 缺點 | 結論 |
|------|------|------|------|
| A: 新增方法並列，不動舊方法 | 向下相容、降低迴歸風險 | 兩個方法存在 | ✅ 選定 |
| B: 重構合併為單一方法 | 程式碼整潔 | 改動舊介面、Sprint 1 測試需重寫 | ❌ 排除 |

### 2.3 資料庫變更方案（3 個 Alembic Migration）

**選定方案：Schema migration + data migration 分離**

> ⚠️ 最新既有 migration revision：`j7c8d9e0f1a2`，所有新 migration 以此為起點

| Migration ID | down_revision | 內容 |
|-------------|--------------|------|
| `k8d9e0f1a2b3` | `j7c8d9e0f1a2` | 建立 `expense_images` 表；`expenses` 新增 3 欄位 |
| `l9e0f1a2b3c4` | `k8d9e0f1a2b3` | `user_states` 新增 2 欄位 |
| `m0f1a2b3c4d5` | `l9e0f1a2b3c4` | data migration：`WAITING_PHOTO` → `COLLECTING` |

### 2.4 Rich Menu 建立方案

**選定方案：更新既有 `setup_rich_menu()` + 新增獨立腳本**

- `services/line_service.py` 中 `setup_rich_menu()` 已存在，Sprint 2 **更新其邏輯**：
  1. 呼叫 `DELETE /v2/bot/richmenu/{id}` 刪除舊有 Rich Menu（若存在）
  2. 以單按鈕「確認送出」規格重新建立
  3. 套用為 default Rich Menu
- 新增 `scripts/setup_rich_menu.py`：可獨立執行的一次性設定腳本（在 Staging/Production 執行一次即可）
- webhook.py 同時保留 TEXT "確認送出" fallback（防止 Rich Menu 設定失敗時使用者無法操作）

### 2.5 `certificate_type` 欄位銜接方案

**現況**：前端 `expenseStore.js` 的 `mapExpense()` 已預留 `certificate_type` 欄位，但後端尚未回傳（目前顯示 null）。

**Sprint 2 解法**：
- 後端 `ExpenseRead` schema 新增 `voucher_categories: list[str] | None`（JSON array，如 `["INVOICE", "TRANSPORTATION"]`）
- 前端 `expenseStore.js` 更新 `mapExpense()`：`certificate_type` 從 `voucher_categories[0]` 轉換為中文顯示名稱

```javascript
// expenseStore.js mapExpense() 更新
const CATEGORY_LABEL = {
  INVOICE: '發票', RECEIPT: '收據', LABOR_SERVICE: '勞報',
  TRANSPORTATION: '交通', CREDIT_NOTE: '退貨折讓',
}
certificate_type: item.voucher_categories?.[0]
  ? (CATEGORY_LABEL[item.voucher_categories[0]] ?? item.voucher_categories[0])
  : (item.certificate_type ?? null),
```

- `AuditModal.vue` 的 `certificate_type` 輸入框改為唯讀顯示

---

## 3. UI 圖稿

本 Sprint 需要 G1 設計審核（Rich Menu 視覺稿 + Flex Message 設計稿）。

| 頁面/元件 | Mockup 檔案 | 說明 |
|----------|------------|------|
| Rich Menu 單按鈕 | `static/mockup/sprint2/rich_menu_design.html` | 2500×843，「✅ 確認送出」全寬單格 |
| 批次摘要 Flex Message | `static/mockup/sprint2/flex_message_design.html` | 各憑證類型 × 數量 × 金額 + 合計 + 組別 + 備註 + 案件編號 |

### 圖稿驗收標準

- [ ] 兩個 HTML mockup 可在瀏覽器直接開啟預覽
- [ ] Rich Menu 設計稿符合 LINE 官方尺寸規範（2500×843）
- [ ] Flex Message 設計稿涵蓋：各憑證類型行、合計金額行、組別/備註/案件編號欄位
- [ ] 繁體中文化完成，圖示對照正確（🧾📋👤🚌↩️📦）
- [ ] 設計稿放置於 `static/mockup/sprint2/` 目錄

---

## 4. 檔案變更清單

### 新增

| 檔案 | 用途 |
|------|------|
| `models/expense_image.py` | ExpenseImage ORM（expense_images 資料表） |
| `schemas/expense_image.py` | ExpenseImageRead Pydantic schema |
| `alembic/versions/k8d9e0f1a2b3_add_expense_images_and_batch_fields.py` | expense_images 表 + expenses 3 欄位 |
| `alembic/versions/l9e0f1a2b3c4_add_user_states_pending_fields.py` | user_states 新增 pending_images + pending_description |
| `alembic/versions/m0f1a2b3c4d5_migrate_waiting_photo_to_collecting.py` | data migration：WAITING_PHOTO → COLLECTING |
| `scripts/__init__.py` | scripts 套件標記 |
| `scripts/setup_rich_menu.py` | Rich Menu 一次性設定腳本（可重複執行） |
| `static/mockup/sprint2/rich_menu_design.html` | Rich Menu 視覺稿 |
| `static/mockup/sprint2/flex_message_design.html` | 批次摘要 Flex Message 設計稿 |
| `tests/unit/test_ocr_classify.py` | `classify_and_extract()` 單元測試 |
| `tests/unit/test_batch_expense.py` | `create_batch_expense()` 費用彙整規則測試 |
| `tests/integration/test_batch_flow.py` | 批次流程 + Onboarding E2E 整合測試 |

### 修改

| 檔案 | 變更內容 |
|------|---------|
| `models/user_state.py` | 新增 `pending_images`（TEXT, JSON, default '[]'）、`pending_description`（TEXT, default ''） |
| `models/expense.py` | 新增 `user_description`（TEXT nullable）、`image_count`（INT default 1）、`voucher_categories`（TEXT nullable JSON array）；新增 `images` relationship → ExpenseImage |
| `services/ocr_service.py` | 新增 `ImageOCRResult` dataclass；新增 `classify_and_extract()` 方法；**不修改 `extract_invoice_data()`** |
| `services/expense_service.py` | 新增 `create_batch_expense()`；新增 `get_expense_images()` |
| `services/line_service.py` | 更新 `setup_rich_menu()`（單按鈕邏輯）；新增 `push_batch_summary()` |
| `routers/webhook.py` | 移除舊「我要報帳」TextMessage 觸發、「查看審核結果」觸發；新增首次 Onboarding 偵測；新增 COLLECTING 狀態圖片累積；新增 Postback `action=confirm_submit` handler |
| `routers/expenses.py` | 新增 `GET /api/v1/expenses/{id}/images` 端點（回傳 ExpenseImage 列表） |
| `schemas/expense.py` | `ExpenseRead` 新增 `user_description`、`image_count`、`voucher_categories` 欄位 |
| `core/config.py` | 新增 `departments: list[str]`（含 validator 解析逗號分隔字串） |
| `.env.example` | 新增 `DEPARTMENTS=製片組,美術組,攝影組,燈光組,場務組,其他` |
| `frontend/src/stores/expenseStore.js` | `mapExpense()` 新增 `voucher_categories` mapping + `certificate_type` 轉換邏輯 |
| `frontend/src/api/expenseApi.js` | 新增 `fetchExpenseImages(id)` API 方法 |
| `frontend/src/components/AuditModal.vue` | `certificate_type` 輸入框改為唯讀 + 顯示 `voucher_categories` 列表 |
| `frontend/src/views/ExpenseListView.vue` 或 `AuditModal.vue` | 詳情區塊新增子圖片清單（URL + voucher_category 標籤 + OCR 金額）、`user_description` 顯示 |

### 刪除

無（不刪除任何現有檔案）

---

## 5. 新增 API 端點

### 新增

| Method | Path | 說明 | 認證 |
|--------|------|------|------|
| `GET` | `/api/v1/expenses/{id}/images` | 取得某筆 Expense 的所有子圖片（ExpenseImage 列表） | JWT |

**回應格式（`GET /api/v1/expenses/{id}/images`）：**
```json
{
  "status": "success",
  "data": {
    "expense_id": "uuid",
    "images": [
      {
        "id": "uuid",
        "image_url": "uploads/xxx.jpg",
        "is_voucher": true,
        "voucher_category": "INVOICE",
        "sequence_order": 1,
        "ocr_result": { "invoice_number": "AB12345678", "total_amount": 2400 },
        "created_at": "2026-04-11T10:00:00"
      }
    ]
  },
  "message": "成功"
}
```

### 修改（新增回應欄位）

`GET /api/v1/expenses` 和 `GET /api/v1/expenses/{id}` 的 `ExpenseRead` schema 新增欄位：

```json
{
  "user_description": "高鐵票和計程車費",
  "image_count": 3,
  "voucher_categories": ["INVOICE", "TRANSPORTATION"]
}
```

---

## 6. 任務定義與分配

> L1（Tech Lead）讀取本節後按依賴順序執行。第一步先執行 `/task-delegation` 建立 `.tasks/sprint-2/` 檔案，系統自動追蹤進度。

### 任務清單

| # | 任務名稱 | 說明 | 負責 Agent | 依賴 | 對應步驟 | 驗收標準 |
|---|---------|------|-----------|------|---------|---------|
| T1 | UI 設計圖稿 | 建立 `static/mockup/sprint2/rich_menu_design.html`（2500×843 單格）和 `flex_message_design.html`（批次摘要格式）；兩份 mockup 可在瀏覽器直接預覽 | designer | 無 | UI 圖稿 | 兩個 HTML mockup 在瀏覽器可預覽；涵蓋所有憑證類型行、合計金額、組別、備註、案件編號；圖示正確；繁體中文 |
| T2 | Rich Menu 設定 | 更新 `services/line_service.py` 的 `setup_rich_menu()` 為單按鈕版本；建立 `scripts/setup_rich_menu.py` 一次性腳本；webhook.py 同時保留 TEXT fallback「確認送出」 | backend-dev | T1（G1 通過後） | 實作 | `python scripts/setup_rich_menu.py` 執行成功；LINE 聊天視窗底部顯示「確認送出」；Postback data="action=confirm_submit"；舊按鈕已移除 |
| T3 | DB Migration | 撰寫 3 個 Alembic migration：(k) expense_images 表 + expenses 新欄位、(l) user_states 新欄位、(m) WAITING_PHOTO→COLLECTING data migration；更新對應 ORM model | backend-dev | 無 | 實作 | `alembic upgrade head` 無錯誤；expense_images 表存在且 FK/CASCADE 正確；expenses 含新 3 欄位；user_states 含 pending_images + pending_description；`alembic downgrade -1` 可回滾 |
| T4 | OCR 擴充 | 在 `services/ocr_service.py` 新增 `ImageOCRResult` dataclass 和 `classify_and_extract()` 方法（不修改 `extract_invoice_data()`）；含 5 種憑證類別的完整 Gemini Prompt | backend-dev | 無 | 實作 | `classify_and_extract()` 可獨立呼叫；5 種類別 INVOICE/RECEIPT/LABOR_SERVICE/TRANSPORTATION/CREDIT_NOTE 各自回傳正確 fields 結構；`extract_invoice_data()` 仍正常執行；CREDIT_NOTE total_amount 為負數 |
| T5 | Webhook 重構 | 重構 `routers/webhook.py`：移除「我要報帳」TextMessage 觸發、查詢功能保留；新增首次 Onboarding 偵測（`users.department IS NULL`）；新增 COLLECTING 狀態圖片收集流程（累積至 UserState.pending_images）；新增 Postback `action=confirm_submit` handler（立即 reply + BackgroundTask）；`line_service.py` 新增 `push_batch_summary()` | backend-dev | T1（G1 通過後）、T3、T4 | 實作 | 新用戶傳訊息觸發 Onboarding Quick Reply；已設定部門使用者傳照片直接累積 pending；按確認送出後 500ms 內回應「⏳ 處理中」；OCR 完成後 push 摘要；貼圖/語音回覆提示；空批次防護 |
| T6 | 費用彙整服務 | 在 `services/expense_service.py` 新增 `create_batch_expense(user_id, pending_images, ocr_results, user_description, uploader_dept)` 和 `get_expense_images(db, expense_id)`；實作費用彙整規則（主憑證選取、total_amount 加總、voucher_categories 去重） | backend-dev | T3 | 實作 | `create_batch_expense()` 正確建立 1 筆 Expense + N 筆 ExpenseImage；total_amount 正確加總（含 CREDIT_NOTE 負數、含部分 null）；voucher_categories 去重後存為 JSON array；image_count 正確；全部批次 OCR 失敗時 status = NEEDS_MANUAL_REVIEW |
| T7 | Dashboard 更新 | 更新 `frontend/src/stores/expenseStore.js`（`mapExpense()` 加入 `voucher_categories` + `certificate_type` 中文轉換）；更新 `frontend/src/api/expenseApi.js`（新增 `fetchExpenseImages()`）；更新詳情頁/AuditModal 顯示子圖片清單 + voucher_category 標籤 + `user_description`；`AuditModal.vue` `certificate_type` 改為唯讀 | frontend-dev | T6（API schema 已確定） | 實作 | ExpenseTable 中 `certificate_type` 欄位正確顯示中文類別名稱；AuditModal 詳情頁顯示所有子圖片清單（含類型標籤與 OCR 金額摘要）；`user_description` 欄位正確顯示 |
| T8 | 測試套件 | 撰寫：`tests/unit/test_ocr_classify.py`（5 種類別 + is_voucher=false + mock Gemini）、`tests/unit/test_batch_expense.py`（彙整規則各場景）、`tests/integration/test_batch_flow.py`（Onboarding E2E、批次流程 E2E、空批次防護、貼圖防護） | qa-engineer | T2~T7 全完成 | 測試 | `pytest` 全綠（無 flaky test）；`classify_and_extract` 覆蓋率 ≥ 80%；`create_batch_expense` 費用彙整規則測試全數通過；Onboarding + 批次流程 E2E 通過 |
| T9 | 文件更新 | 更新 `.knowledge/specs/api-design.md`（新增 `/expenses/{id}/images` 端點；更新 ExpenseRead schema）；更新 `.knowledge/project-overview.md`（新流程圖、新資料表）；執行 `/pitfall-resolve` 將 postmortem #003 更新為 resolved | tech-writer | T8（G3 通過後） | 文件 | api-design.md 含新端點說明；project-overview.md 流程圖更新為批次報帳流程；#003 狀態更新為 resolved |

### 依賴圖

```
T1（UI 設計）──────(G1 通過)──┬──→ T2（Rich Menu 設定）
                              └──→ T5（Webhook 重構）◄─────────┐
                                                               │
T3（DB Migration）────────────────→ T6（費用彙整服務）         │
                              └──→ T5（需要 schema）           │
                                                               │
T4（OCR 擴充）────────────────────→ T5（需要 classify_and_extract）
                                                               │
T2 + T3 + T4 + T5 + T6 ──────────→ T7（Dashboard 更新）       │
                                                               │
T2 + T3 + T4 + T5 + T6 + T7 ─────→ T8（測試）                 │
                                                               │
T8（G3 通過後）───────────────────→ T9（文件更新）
```

**並行執行策略**：
- **第一波（立即開始）**：T1、T3、T4 可同時開始
- **T1 G1 通過後解鎖**：T2（立即開始）、T5（需等 T3 + T4 也完成才能開始）
- **T3 完成後解鎖**：T6（可開始）
- **T6 API schema 確定後解鎖**：T7
- **T2~T7 全部完成後解鎖**：T8
- **T8 G3 通過後解鎖**：T9

### L1（Tech Lead）執行指令

> PM 產出此區塊，老闆複製貼入 Tech Lead session 啟動。

**Tech Lead（tech-lead）：**
```
請執行 Sprint 2 AcctAssist 開發計畫。

📄 計畫書：proposal/sprint2-dev-plan.md
🎯 Sprint 目標：多張照片批次報帳 + 部門一次性 Onboarding + LINE Rich Menu 單按鈕

第一步請先執行 /task-delegation 建立 .tasks/sprint-2/ 任務檔案。

任務分派：
🎨 委派 designer：T1（UI 設計圖稿）← 立即啟動
🔧 委派 backend-dev：T3（DB Migration）← 立即啟動（不等 G1）
🔧 委派 backend-dev：T4（OCR 擴充）← 立即啟動（不等 G1）
⚠️ T1 通過 G1 後才能啟動：T2（Rich Menu）、T5（Webhook 重構，同時等 T3+T4）
⚠️ T3 完成後才能啟動：T6（費用彙整服務）
⚠️ T6 完成後才能啟動：T7（Dashboard 更新）
⚠️ T2~T7 全完成才能啟動：T8（測試）
⚠️ T8 G3 通過才能啟動：T9（文件）

阻斷規則：
- G1 阻斷：T5 的 push_batch_summary() Flex Message 結構需等 G1 通過
- G3 阻斷：T9 不得在 G3 通過前開始
```

**Designer（designer）：**
```
請執行 Sprint 2 AcctAssist 開發任務 T1（UI 設計圖稿）。

📄 計畫書：proposal/sprint2-dev-plan.md
📋 你負責的任務：T1（UI 設計圖稿）

T1 說明：
- 建立 static/mockup/sprint2/rich_menu_design.html
  - LINE Rich Menu 視覺稿，尺寸 2500×843
  - 全寬單格，顯示「✅ 確認送出」
  - 動作類型標注：Postback data="action=confirm_submit"
- 建立 static/mockup/sprint2/flex_message_design.html
  - 批次摘要 Flex Message 設計稿
  - 需包含：各憑證類型行（🧾發票/📋收據/👤勞報/🚌交通/↩️退貨折讓/📦品項照片）× 數量 × 金額
  - 底部：合計金額、所屬組別、備註、案件編號
- 兩份 mockup 需可在瀏覽器直接開啟預覽（不需 build）
- 統一使用繁體中文

第一步請先執行 /task-start T1-sprint2。
完成後執行 /task-done T1-sprint2。
```

**Backend Dev（backend-dev）- 第一波（T3、T4）：**
```
請執行 Sprint 2 AcctAssist 後端開發，第一波任務 T3 和 T4（可並行執行）。

📄 計畫書：proposal/sprint2-dev-plan.md
📋 你負責的任務：T3（DB Migration）、T4（OCR 擴充）

T3 說明 - DB Migration（down_revision 起點：j7c8d9e0f1a2）：
1. alembic/versions/k8d9e0f1a2b3_add_expense_images_and_batch_fields.py
   - 建立 expense_images 表（id UUID PK、expense_id FK→expenses CASCADE DELETE、image_url str、is_voucher bool、voucher_category str nullable、sequence_order int、ocr_result JSON nullable、created_at datetime）
   - expenses 表新增：user_description TEXT nullable、image_count INT default 1、voucher_categories TEXT nullable
2. alembic/versions/l9e0f1a2b3c4_add_user_states_pending_fields.py
   - user_states 新增：pending_images TEXT default '[]'、pending_description TEXT default ''
3. alembic/versions/m0f1a2b3c4d5_migrate_waiting_photo_to_collecting.py
   - data migration：UPDATE user_states SET step='COLLECTING' WHERE step='WAITING_PHOTO'
4. 同步更新 models/expense_image.py（新建）、models/user_state.py、models/expense.py

T4 說明 - OCR 擴充（不修改 extract_invoice_data）：
1. services/ocr_service.py 新增：
   - ImageOCRResult dataclass（is_voucher, voucher_category, fields, raw_response, success, error）
   - classify_and_extract(image_path) async 方法
   - 完整的 MULTI_TASK_PROMPT（含 5 種類別格式，參考提案書 5.7 節）
2. CREDIT_NOTE 的 total_amount 必須確保為負數

⚠️ 地雷提醒：
- postmortem #004：SQLAlchemy 所有 DB 操作需全程 async/await
- migration 必須能 downgrade（實作 down() 函式）

第一步請先執行 /task-start T3-sprint2 和 /task-start T4-sprint2。
```

**Backend Dev（backend-dev）- 第二波（T2、T5、T6，等 G1 通過且 T3/T4 完成）：**
```
請執行 Sprint 2 AcctAssist 後端開發，第二波任務 T2、T5、T6。

📄 計畫書：proposal/sprint2-dev-plan.md
📋 前置條件：T1 G1 已通過 + T3 已完成 + T4 已完成

T2 說明 - Rich Menu 設定（G1 通過後才執行）：
1. 更新 services/line_service.py 的 setup_rich_menu()：刪除舊 Rich Menu → 建立單按鈕版本 → set as default
2. 新建 scripts/ 目錄 + scripts/__init__.py + scripts/setup_rich_menu.py（獨立可執行腳本）
3. webhook.py 新增 TEXT fallback："確認送出" → 觸發 confirm_submit 邏輯

T5 說明 - Webhook 重構（G1 通過 + T3 + T4 完成後才執行）：
1. 移除 TextMessage 中的「我要報帳」觸發邏輯（查詢功能保留）
2. 所有 MessageEvent：先判斷 users.department IS NULL → 是則 Onboarding Quick Reply
3. ImageMessage（部門已設定）：append to UserState.pending_images（SELECT FOR UPDATE 防競態），push「已收到第 N 張」
4. ImageMessage（Onboarding 進行中）：暫存圖片，等部門選定後繼續
5. TextMessage（非指令）：append to UserState.pending_description，push「備註已記錄」
6. Postback action=confirm_submit：
   - pending 為空 → reply「尚未收到任何照片」
   - 否則 → reply「⏳ 處理中」→ BackgroundTask(process_batch, pending_images, pending_description, user_id)
   - BackgroundTask 呼叫 create_batch_expense() → push_batch_summary()
   - 清空 UserState.pending_images + pending_description
7. services/line_service.py 新增 push_batch_summary()：參考 Flex Message 設計稿（T1 產出）

T6 說明 - 費用彙整服務（T3 完成後才執行）：
1. services/expense_service.py 新增 create_batch_expense(db, user_id, pending_images, ocr_results, user_description, uploader_dept)
2. 費用彙整規則（提案書 5.6 節）：
   - 主憑證優先級：INVOICE > RECEIPT > LABOR_SERVICE > TRANSPORTATION
   - total_amount = sum(is_voucher=true 且 total_amount 非 null)，CREDIT_NOTE 為負數直接加總
   - voucher_categories = deduplicated list of is_voucher=true 類別
   - image_count = len(pending_images)
   - status = PENDING if total_amount != null else NEEDS_MANUAL_REVIEW
3. services/expense_service.py 新增 get_expense_images(db, expense_id) -> list[ExpenseImage]
4. routers/expenses.py 新增 GET /api/v1/expenses/{id}/images 端點

⚠️ 地雷提醒：
- postmortem #003：Webhook 必須 < 500ms 回應，所有 OCR 操作在 BackgroundTask 中執行
- postmortem #004：所有 SQLAlchemy 操作全程 async
- pending_images JSON array append 需 SELECT FOR UPDATE 防止競態條件

第一步依序執行 /task-start T2-sprint2、/task-start T5-sprint2、/task-start T6-sprint2。
```

**Frontend Dev（frontend-dev）：**
```
請執行 Sprint 2 AcctAssist 前端開發任務 T7（在 T6 API schema 確定後執行）。

📄 計畫書：proposal/sprint2-dev-plan.md
📋 你負責的任務：T7（Dashboard 更新）
📋 前置條件：T6 已完成（後端 API 已確定返回 voucher_categories、user_description、image_count 欄位）

T7 說明：
1. frontend/src/stores/expenseStore.js：更新 mapExpense()
   - 新增 voucher_categories: item.voucher_categories ?? null
   - 更新 certificate_type：從 voucher_categories[0] 轉換為中文（INVOICE→發票、RECEIPT→收據、LABOR_SERVICE→勞報、TRANSPORTATION→交通、CREDIT_NOTE→退貨折讓）
   - 新增 user_description: item.user_description ?? null
   - 新增 image_count: item.image_count ?? 1
2. frontend/src/api/expenseApi.js：新增 fetchExpenseImages(expenseId) 方法（GET /api/v1/expenses/{id}/images）
3. frontend/src/components/AuditModal.vue：
   - certificate_type 輸入框改為唯讀顯示，顯示 voucher_categories 的中文名稱列表（以逗號分隔）
   - 新增子圖片清單區塊（image_url + voucher_category 標籤 + OCR 金額）
   - 新增 user_description 顯示欄位

規範參考：
- .knowledge/specs/api-design.md（API 格式）
- CLAUDE.md（Vue 3 Composition API + script setup，禁止 Options API）
- 禁止在元件中直接呼叫 axios，一律透過 expenseApi.js

第一步請先執行 /task-start T7-sprint2。
```

**QA Engineer（qa-engineer）：**
```
請執行 Sprint 2 AcctAssist 測試任務 T8（在 T2~T7 全部完成後執行）。

📄 計畫書：proposal/sprint2-dev-plan.md
📋 你負責的任務：T8（測試套件）

T8 說明：
1. tests/unit/test_ocr_classify.py（mock Gemini API）：
   - 各類別正確分類：INVOICE（含統編/課稅別）、RECEIPT（含免用統一發票章）、LABOR_SERVICE（含身分證/實領）、TRANSPORTATION（含起訖點）、CREDIT_NOTE（total_amount 為負數）
   - is_voucher=false 時 fields 為 null
   - Gemini API 失敗時優雅降級（success=False）

2. tests/unit/test_batch_expense.py：
   - 費用彙整規則：多財務憑證加總、CREDIT_NOTE 負數加總自動扣除
   - 部分 null 金額（有些憑證無法辨識）的加總行為
   - 全部 null → status=NEEDS_MANUAL_REVIEW
   - voucher_categories 去重正確
   - image_count 與 pending_images 數量一致

3. tests/integration/test_batch_flow.py（mock LINE SDK + mock Gemini）：
   - 首次 Onboarding E2E：新用戶傳訊息 → Quick Reply → 選部門 → 寫入 users.department
   - Onboarding 期間傳照片不丟失（存入 pending）
   - 日常批次流程 E2E：傳 3 張照片 → 按確認送出 → 500ms 內回應 → push 批次摘要
   - 空批次防護：pending 為空時按確認送出 → 回覆提示，不建立 Expense
   - 貼圖/語音防護：回覆提示，不破壞 pending 狀態

⚠️ 地雷提醒：
- postmortem #004：conftest.py 中 DB 使用 AsyncSession + SQLite in-memory
- serial_number 依賴 PG sequence，在 conftest.py 中 monkeypatch mock
- BackgroundTask 時序問題：使用 asyncio.sleep(0) 或直接 mock add_task

第一步請先執行 /task-start T8-sprint2。
```

**Tech Writer（tech-writer）：**
```
請執行 Sprint 2 AcctAssist 文件任務 T9（在 T8 G3 通過後執行）。

📄 計畫書：proposal/sprint2-dev-plan.md
📋 你負責的任務：T9（文件更新）
📋 前置條件：T8 通過 G3 審核

T9 說明：
1. 更新 .knowledge/specs/api-design.md：
   - 新增 GET /api/v1/expenses/{id}/images 端點說明
   - 更新 ExpenseRead schema 欄位表格（user_description、image_count、voucher_categories）
2. 更新 .knowledge/project-overview.md：
   - 更新「資料庫結構」章節（新增 expense_images 表）
   - 更新「LINE Bot 報帳流程」為批次收集流程
   - 更新 API 端點列表
3. 執行 /pitfall-resolve 將 .knowledge/postmortem-log.md #003 更新為 resolved（Sprint 2 已強制 BackgroundTask 解決此問題）

第一步請先執行 /task-start T9-sprint2。
```

### 共用檔案（需協調）

| 檔案 | 涉及任務 | 風險等級 | 協調說明 |
|------|---------|---------|---------|
| `routers/webhook.py` | T5、T8 | 高 | T5 完整重構；T8 需測試重構後邏輯；T5 先完成再由 T8 補整合測試 |
| `services/expense_service.py` | T6、T8 | 高 | T6 新增方法；T8 測試這些方法；T6 先完成 |
| `services/ocr_service.py` | T4、T8 | 中 | T4 新增方法（不改舊方法）；T8 補新方法的測試 |
| `models/expense.py` | T3、T5、T6 | 中 | T3 修改 ORM + relationship；T5/T6 依賴新 schema；T3 必須優先完成 |
| `services/line_service.py` | T2、T5 | 中 | T2 更新 setup_rich_menu()；T5 新增 push_batch_summary()；依序執行 |

---

## 7. 測試計畫

### 單元測試

| 測試檔案 | 覆蓋場景 |
|---------|---------|
| `tests/unit/test_ocr_classify.py` | `classify_and_extract()` 各類別（INVOICE 含統編/課稅別、RECEIPT 含免用章、LABOR_SERVICE 含身分證/實領、TRANSPORTATION 含起訖點、CREDIT_NOTE 負數）、is_voucher=false（品項照片/模糊）、Gemini 失敗降級 |
| `tests/unit/test_batch_expense.py` | `create_batch_expense()` 費用彙整規則：多憑證加總、CREDIT_NOTE 負數加總、部分 null 金額加總、全部 null→NEEDS_MANUAL_REVIEW、voucher_categories 去重、image_count 正確、主憑證欄位優先級（INVOICE>RECEIPT>...） |

### 整合測試

| 測試檔案 | 覆蓋場景 |
|---------|---------|
| `tests/integration/test_batch_flow.py` | 首次 Onboarding E2E（新用戶觸發 Quick Reply→選部門→department 寫入）、Onboarding 期間照片不丟失、日常批次流程 E2E（傳 3 張→確認送出→500ms 回應→push 摘要→pending 清空）、空批次防護（pending 空時按確認送出）、貼圖/語音防護 |

---

## 8. 風險與緩解

| 風險 | 影響 | 緩解措施 |
|------|------|---------|
| **多圖 OCR 超時（#003）**：5 張 × ~5 秒 = ~25 秒，遠超 LINE 5 秒限制 | 使用者收不到確認 | T5 強制 BackgroundTask；Postback 收到後立即 reply「⏳ 處理中」；OCR 完成後 push 摘要。**此解法同時解決 postmortem #003** |
| **SQLAlchemy async (#004)**：`create_batch_expense()` 涉及多表寫入 | 500 錯誤 | T6 全程 async/await；Code Review 時逐行確認 DB 操作 |
| **migration 順序錯誤** | `alembic upgrade head` 失敗 | 3 個 migration k→l→m 序列，每個 down_revision 正確；均實作 down() 函式 |
| **G1 阻斷導致 T5 延誤** | T5 等待設計稿，後續任務延遲 | T3/T4 提前並行開始（不等 G1）；G1 只阻斷 T5 中 Flex Message 格式設計，Webhook 骨架可先建立 |
| **pending_images 競態條件**：同一用戶快速傳多張 | 圖片遺失或重複 | T5 append 操作使用 `SELECT FOR UPDATE` DB transaction |
| **enable_user_binding 與 Onboarding 衝突** | 舊綁定流程與新 Onboarding 互相干擾 | T5 webhook.py 中分層處理：先判斷 `users.department IS NULL`（Sprint 2 Onboarding），與舊 `enable_user_binding` 邏輯獨立 |
| **Gemini RPM 限制（免費版）**：批次 OCR 觸發 429 | 大量 NEEDS_MANUAL_REVIEW | 序列執行（非並行）；失敗時記錄 error log，單張設 NEEDS_MANUAL_REVIEW 不中斷整批；通知使用者 |

---

## 9. 文件更新

完成後需同步更新的文件：

- [ ] `.knowledge/specs/api-design.md` — 新增 `/expenses/{id}/images` 端點；更新 ExpenseRead schema（T9 執行）
- [ ] `.knowledge/project-overview.md` — 更新批次報帳流程圖、資料表清單（T9 執行）
- [ ] `.knowledge/postmortem-log.md` — #003 更新為 `resolved`（T9 執行 `/pitfall-resolve`）
- [ ] `.knowledge/file-index.md` — Sprint 2 結束後更新文件索引
- [ ] `.env.example` — 新增 `DEPARTMENTS` key（T3/T5 執行時同步更新）

---

## 10. 任務與審核紀錄（備查）

> 每個任務完成後記錄結果，每次 Review/Gate 通過後記錄決策。本區作為 Sprint 完整稽核軌跡。

### 任務完成紀錄

| 任務 | 完成日期 | 結果 | 備註 |
|------|---------|------|------|
| T1（UI 設計圖稿） | 2026-04-10 | ✅ 通過 | Rich Menu 視覺稿 + Flex Message 設計稿完成，靜態 HTML mockup 存於 `static/mockup/sprint2/` |
| T2（Rich Menu 設定） | 2026-04-10 | ✅ 通過 | `setup_rich_menu()` 冪等實作，`scripts/setup_rich_menu.py` 獨立腳本 |
| T3（DB Migration） | 2026-04-10 | ✅ 通過 | 3 migrations (k/l/m)：expense_images 表、pending_images/description、WAITING_PHOTO→COLLECTING |
| T4（OCR 擴充） | 2026-04-10 | ✅ 通過 | `ImageOCRResult` dataclass + `classify_and_extract()`，CREDIT_NOTE 負數強制轉換，優雅降級 |
| T5（Webhook 重構） | 2026-04-10 | ✅ 通過 | Onboarding 偵測、SELECT FOR UPDATE 圖片累積、BackgroundTask 批次送出、防護規則 |
| T6（費用彙整服務） | 2026-04-10 | ✅ 通過 | `create_batch_expense()` 多憑證加總、CREDIT_NOTE 扣除、voucher_categories 去重、ExpenseImage 批次建立 |
| T7（Dashboard 更新） | 2026-04-10 | ✅ 通過 | ExpenseStore 映射更新、`GET /expenses/{id}/images` 新端點、AuditModal 子圖顯示 |
| T8（測試套件） | 2026-04-11 | ✅ 通過 | pytest 24/24 全綠：test_ocr_classify(8) + test_batch_expense(8) + test_batch_flow(8) |
| T9（文件更新） | 2026-04-11 | ✅ 通過 | api-design.md v1.1 + project-overview.md v1.2 + postmortem-log.md v1.1（#003 resolved + #006-#009 新增） |

### Review 紀錄

| Review 步驟 | 日期 | 結果 | Review 文件連結 |
|------------|------|------|---------------|
| G1 設計審核（T1） | 2026-04-10 | ✅ 通過 | Rich Menu 2500×843 單格、Flex Message 6 類型行、設計稿符合 LINE 官方規格 |
| G2 程式碼審查（T2~T7） | 2026-04-10 | ✅ 通過 | T2~T7 全數通過 L1 審查；補件流程保留、SELECT FOR UPDATE 防競態、500ms 機制符合規格 |
| G3 測試驗收（T8） | 2026-04-11 | ✅ 通過 | pytest 24/24 全綠；覆蓋率 classify≥80%；E2E Onboarding/批次/空批次/防護全通過 |
| G4 文件審查（T9） | 2026-04-11 | ✅ 通過 | 3 份文件全數更新；postmortem 解決率 100%（9/9）；Sprint 2 所有任務完成 |

### Gate 紀錄

| Gate | 日期 | 決策 | 審核意見 |
|------|------|------|---------|
| G0 | 2026-04-10 | ✅ 通過 | 提案書 `proposal/sprint2-proposal.md` v2 |
| G1 | 2026-04-10 | ✅ 通過 | T1 設計稿符合規格；Flex Message 結構完整；解除 T5 的 G1 阻斷 |
| G2 | 2026-04-10 | ✅ 通過 | T2~T7 程式碼全數通過；BackgroundTask、SELECT FOR UPDATE、serial OCR 均符合架構規範 |
| G3 | 2026-04-11 | ✅ 通過 | T8 pytest 24/24 全綠；classify_and_extract 覆蓋率≥80%；E2E 全通過；解除 T9 的 G3 阻斷 |
| G4 | 2026-04-11 | ✅ 通過 | T9 文件全數更新；api-design/project-overview/postmortem 三份文件完整；Sprint 2 正式封版 |

---

**確認**: [x] PM 確認 / [x] Tech Lead 確認（project-lead L1，2026-04-11）

---

> **Sprint 2 封版**：T1~T9 全數完成，G0→G4 全部通過，AcctAssist 批次報帳功能正式交付。
