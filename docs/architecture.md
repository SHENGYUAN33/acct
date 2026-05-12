# AcctAssist 技術架構與資料流文檔

> **版本**：v1.0 ｜ **更新日期**：2026-04-16  
> **適用對象**：後端維護工程師、新成員、PM  
> **文件目的**：描述系統各元件協作關係，以及一筆發票資料從上傳到歸檔的完整生命週期。

---

## 目錄

1. [系統整體技術架構](#1-系統整體技術架構)
2. [單筆資料生命週期](#2-單筆資料生命週期)
3. [GenAI 多模態解析詳解](#3-genai-多模態解析詳解)
4. [Auto-Split 分組演算法](#4-auto-split-分組演算法)
5. [狀態機與關鍵欄位速查](#5-狀態機與關鍵欄位速查)

---

## 1. 系統整體技術架構

### 1.1 高層元件協作圖

```mermaid
flowchart TB
    subgraph 接入層["接入層 (Entry Layer)"]
        LINE[LINE App\n使用者介面]
        DASH[Vue 3 Dashboard\n審核介面]
    end

    subgraph 應用層["應用層 (Application Layer — FastAPI)"]
        WH["/webhook\nrouters/webhook.py"]
        EXP_API["/api/v1/expenses\nrouters/expenses.py"]
        AUTH_API["/api/v1/auth\nrouters/auth.py"]
        ADMIN_API["/admin\nrouters/admin.py"]
        STATIC["/uploads/{uuid}.jpg\nStatic File Serving"]
    end

    subgraph 業務層["業務層 (Service Layer)"]
        LS[line_service.py\n狀態機 + 訊息回覆]
        ES[expense_service.py\nCRUD + 批次建立]
        OCR[ocr_service.py\nGemini OCR 封裝]
        AS[auto_split_service.py\n多張分組邏輯]
        TIMER[auto_split_timer.py\nDebounce Timer\n⚠️ in-memory, 單 worker]
    end

    subgraph 持久化層["持久化層 (Persistence Layer)"]
        PG[(PostgreSQL 16\nDocker)]
        FS[本地檔案系統\nuploads/]
    end

    subgraph 外部服務["外部服務 (External Services)"]
        GEMINI[Google Gemini API\ngemini-2.5-flash]
        LINE_API[LINE Messaging API\n訊息推播 + 圖片下載]
    end

    LINE -->|POST /webhook\nX-Line-Signature| WH
    DASH -->|REST API\nBearer JWT| EXP_API
    DASH -->|Bearer JWT| AUTH_API
    DASH -->|Bearer JWT| ADMIN_API
    DASH -->|圖片載入| STATIC

    WH --> LS
    WH --> ES
    WH --> OCR
    WH --> TIMER
    EXP_API --> ES

    LS -->|reply / push| LINE_API
    LS -->|下載圖片| LINE_API
    OCR -->|Structured Output| GEMINI
    AS --> ES
    AS --> OCR
    TIMER -->|觸發回呼| AS

    ES --> PG
    LS --> PG
    OCR -.->|暫存圖片| FS
    STATIC --- FS

    PG -->|4 張核心資料表| PG
```

### 1.2 四張核心資料表關係

```mermaid
erDiagram
    users {
        uuid id PK
        string line_user_id UK
        string name
        string real_name
        string employee_id
        string department
        datetime created_at
    }

    user_states {
        string line_user_id PK
        string step
        string dept
        text pending_images "JSON Array — 批次圖片 buffer"
        text pending_description
        datetime updated_at
    }

    expenses {
        uuid id PK
        uuid user_id FK
        string serial_number UK "EXP-YYYYMM-NNNN"
        array image_url "PostgreSQL ARRAY"
        array item_image_url "PostgreSQL ARRAY"
        string uploader_name
        string uploader_dept
        string submitter_name
        date expense_date
        string invoice_number
        decimal total_amount
        string seller_tax_id
        string seller_name
        string status "PENDING/APPROVED/REJECTED/NEEDS_MANUAL_REVIEW/SUPPLEMENTED"
        string trigger_by "manual_button / auto_split"
        int image_count
        text voucher_categories "JSON Array"
        text voucher_subtypes "JSON Array"
        text expense_categories "JSON Array"
        datetime created_at
    }

    expense_images {
        uuid id PK
        uuid expense_id FK
        string image_url
        bool is_voucher
        string voucher_category
        string voucher_subtype
        string expense_category
        int sequence_order
        text ocr_result "完整 VoucherOCRResult JSON"
        float ocr_confidence "0.000–1.000"
        datetime created_at
    }

    users ||--o{ expenses : "has"
    expenses ||--o{ expense_images : "contains"
```

### 1.3 兩種任務派發機制對比

| 機制 | 觸發條件 | 程式路徑 | `trigger_by` 值 | 備註 |
|------|---------|---------|----------------|------|
| **手動點擊提交** | 使用者點選「確認送出」Flex Button | `PostbackEvent` → `cancel()` timer → `create_task(_process_batch())` | `"manual_button"` | 即時取消 debounce |
| **計時器自動觸發** | 最後一張圖片後 N 秒無動作（預設 60s） | `schedule()` → `asyncio.sleep()` → `auto_split_service.process()` | `"auto_split"` | 需 `enable_auto_split=True`；僅支援單 worker |

---

## 2. 單筆資料生命週期

### 完整序列圖

```mermaid
sequenceDiagram
    actor User as 使用者 (LINE)
    participant WH as webhook.py
    participant LS as line_service.py
    participant DB as PostgreSQL
    participant FS as uploads/ (本地)
    participant TIMER as auto_split_timer.py
    participant AS as auto_split_service.py
    participant OCR as ocr_service.py
    participant ES as expense_service.py
    participant GEMINI as Google Gemini API
    participant DASH as Vue3 Dashboard

    %% ── 第一階段：接收與預處理 ──
    Note over User,FS: 第一階段：接收與預處理

    User->>WH: 傳送發票圖片 (ImageMessageContent)
    WH->>LS: confirm step == "COLLECTING"
    LS->>DB: SELECT user_states WHERE line_user_id=...
    DB-->>LS: UserState {step="COLLECTING", pending_images=[...]}
    WH->>LS: download_image(message_id)
    LS->>GEMINI: GET content API (LINE Binary)
    Note right of LS: 實際透過 LINE API 下載
    LS-->>WH: image bytes
    WH->>FS: 寫入 uploads/{uuid}.jpg
    WH->>DB: UPDATE user_states SET pending_images = append({path, timestamp, message_id})
    WH->>WH: 靜默收集（不回覆使用者）

    alt enable_auto_split == True
        WH->>TIMER: schedule(user_id, delay=60s, callback)
        Note right of TIMER: 滑動視窗：新圖片重置計時器
    end

    %% ── 第二階段：提交與派發 ──
    Note over User,TIMER: 第二階段：提交與派發

    alt 手動提交（trigger_by = "manual_button"）
        User->>WH: 點選「確認送出」(PostbackEvent action=confirm_submit)
        WH->>TIMER: cancel(user_id)
        WH->>DB: 讀取 pending_images buffer
        WH->>DB: 清空 pending_images（防重複提交）
        WH->>WH: asyncio.create_task(_process_batch(images))
        WH-->>User: 「處理中，請稍候...」
    else 計時器自動觸發（trigger_by = "auto_split"）
        TIMER->>AS: callback(user_id)
        AS->>DB: 讀取 pending_images buffer
        AS->>DB: 立即清空 buffer（防競態）
    end

    %% ── 第三階段：GenAI 多模態解析 ──
    Note over OCR,GEMINI: 第三階段：GenAI 多模態解析（核心）

    par 並行 OCR（Semaphore limit=3）
        WH->>OCR: classify_and_extract_with_retry(image_path_1)
        OCR->>GEMINI: upload image + MULTI_TASK_PROMPT\n(Structured Output: VoucherOCRResult)
        GEMINI-->>OCR: VoucherOCRResult JSON
        OCR-->>WH: VoucherOCRResult #1

        WH->>OCR: classify_and_extract_with_retry(image_path_2)
        OCR->>GEMINI: upload image + MULTI_TASK_PROMPT
        GEMINI-->>OCR: VoucherOCRResult JSON
        OCR-->>WH: VoucherOCRResult #2
    end

    Note over OCR: 失敗時 Exponential Backoff\n1s → 2s → 拋出例外

    alt enable_auto_split == True
        WH->>AS: multi_split_logic(ocr_results)
        Note right of AS: is_voucher=True → 新群組\nis_voucher=False → 補充照片
        AS-->>WH: [[group_1_images], [group_2_images], ...]
    else 單次批次
        Note over WH: 所有圖片視為同一群組
    end

    %% ── 第四階段：結構化寫入 ──
    Note over ES,DASH: 第四階段：結構化寫入與 Dashboard 呈現

    loop 每個 expense group
        WH->>ES: create_batch_expense(user_id, group_images, ocr_results, trigger_by)
        Note right of ES: 主欄位優先級：\nINVOICE > RECEIPT > LABOR_SERVICE\n> INSURANCE > RENTAL > ACCOMMODATION\n> UTILITY > POSTAGE > TRANSPORTATION
        ES->>ES: 加總所有 is_voucher=True 的 total_amount
        ES->>ES: 判斷 PENDING / NEEDS_MANUAL_REVIEW\n(KEY_AUDIT_FIELDS 信心 < 0.8)
        ES->>DB: INSERT INTO expenses (serial=EXP-YYYYMM-NNNN, ...)
        ES->>DB: INSERT INTO expense_images × N\n(ocr_result JSON, ocr_confidence, sequence_order)
        DB-->>ES: expense record
        ES-->>WH: ExpenseRead
    end

    WH-->>User: 回傳辨識摘要\n（金額、賣家名、案件編號）

    DASH->>WH: GET /api/v1/expenses?status=PENDING
    WH-->>DASH: ExpenseListResponse (含 images[])
    DASH->>DASH: 渲染審核介面（圖片燈箱 + 欄位編輯）
```

---

## 3. GenAI 多模態解析詳解

### 3.1 Prompt 策略：三步驟推理鏈

`ocr_service.py` 使用單一 `MULTI_TASK_PROMPT`，要求 Gemini 依序完成三個任務：

#### Step 1 — Scene Reasoning（場景推理）

> 目標：在提取任何欄位之前，先透過視覺線索建立整體理解。

Gemini 分析的視覺要素：
- 商店名稱與 Logo 辨識
- 文件格式與排版特徵（電子發票格式 vs 手寫收據）
- 印章顏色與位置（免稅印章、統一發票專用章）
- 紙張特徵與質感推斷

輸出存入 `scene_reasoning: str`，作為後續提取的語義背景。

#### Step 2 — Field Extraction & Rationalization（欄位提取與合理化）

> 目標：提取所有可見欄位，並以「會計常識」補推不可見欄位。

**補推範例：**
- 若 `net_amount` + `tax_amount` 可見但 `total_amount` 不清晰 → 計算推論，標記 `total_amount` 進入 `inferred_fields[]`
- 民國年轉西元年（e.g., 114/04/16 → 2025-04-16）
- CREDIT_NOTE 金額強制轉為負數（後端 post-process）

#### Step 3 — Confidence Scoring & Audit Review（信心評分與審計）

> 目標：為每個關鍵欄位提供信心分數，並生成人工審核建議。

每個欄位有對應的 `{field}_confidence: float (0.0–1.0)` 分數：

```
invoice_number_confidence    → 發票號碼辨識可信度
seller_tax_id_confidence     → 統一編號辨識可信度
total_amount_confidence      → 金額辨識可信度
id_number_confidence         → 勞務所得身分證字號
```

**信心評分路由規則：**

```
KEY_AUDIT_FIELDS = {invoice_number, seller_tax_id, total_amount, id_number}
KEY_FIELD_THRESHOLD = 0.8

IF 任一 KEY_AUDIT_FIELD.confidence < 0.8
    → status = NEEDS_MANUAL_REVIEW
ELSE IF total_amount IS NULL
    → status = NEEDS_MANUAL_REVIEW
ELSE
    → status = PENDING
```

### 3.2 語義歸類體系

Gemini 回傳的語義分類欄位形成三層巢狀結構：

```
is_voucher (bool)
    └── voucher_category (10 種)
            └── voucher_subtype (細分)
                    expense_category (消費類別，獨立維度)
```

#### 憑證類別（voucher_category）與細分（voucher_subtype）

| voucher_category | voucher_subtype 範例 | 語義觸發條件 |
|-----------------|---------------------|------------|
| `INVOICE` | `ELECTRONIC`, `PAPER`, `EXEMPT_INVOICE` | 有統一編號格式、發票專用章 |
| `RECEIPT` | `WITH_STAMP`, `WITHOUT_STAMP` | 收銀機收據、手寫收據、無稅務格式 |
| `TRANSPORTATION` | `HSR_TICKET`, `TAXI`, `PARKING`, `FUEL`, `TOLL_ETC`, `TRAIN`, `BUS` | 交通工具票根、油站收據 |
| `LABOR_SERVICE` | — | 有身分證字號、勞務報酬單 |
| `INSURANCE` | `WORK_INJURY`, `LIFE`, `VEHICLE` | 保單、保費收據 |
| `UTILITY` | `ELECTRICITY`, `WATER`, `GAS`, `TELECOM` | 公用事業帳單 |
| `RENTAL` | `OFFICE`, `VENUE`, `EQUIPMENT` | 房租、場地費用 |
| `ACCOMMODATION` | — | 飯店住宿收據、訂房確認單 |
| `POSTAGE` | `EXPRESS`, `REGISTERED` | 郵資、快遞費用 |
| `CREDIT_NOTE` | — | 折讓單（金額強制為負） |

#### 消費類別（expense_category）

| expense_category | 說明 |
|-----------------|------|
| `MEAL` | 餐飲消費（從 RECEIPT 之店名/品項推斷） |
| `TRANSPORTATION` | 交通費（高鐵票、計程車、停車費） |
| `STATIONERY` | 文具辦公用品 |
| `INSURANCE` | 保險費 |
| `UTILITY` | 水電瓦斯費 |
| `ACCOMMODATION` | 住宿費 |
| `VENUE_RENTAL` | 場地租借費 |
| `OFFICE_RENTAL` | 辦公室租金 |
| `LABOR` | 勞務報酬 |
| `POSTAGE` | 郵資快遞 |

> **推論示例**：RECEIPT 類型圖片，若 `seller_name` 包含「全家」、「7-11」，Gemini 會將 `expense_category` 設為 `MEAL` 或 `STATIONERY`，依品項內容決定。

### 3.3 技術實作亮點

| 亮點 | 實作細節 |
|------|---------|
| **Structured Output** | `response_schema=VoucherOCRResult`，直接對應 Pydantic 模型，零 JSON 解析錯誤 |
| **並發控制** | `asyncio.Semaphore(3)`，避免 Gemini API rate limit 429 |
| **重試機制** | Exponential backoff：1s → 2s，最多 3 次，失敗後回傳 `success=False` |
| **補推透明度** | `inferred_fields: list[str]` 明確標記所有推斷欄位，審計可追溯 |
| **後處理修正** | CREDIT_NOTE 金額強制負數（Gemini 有時回傳正值） |

---

## 4. Auto-Split 分組演算法

### 4.1 設計目標

當使用者一次上傳多張圖片（如：三張發票 + 各自的明細照片）時，系統自動判斷應建立幾筆報帳記錄。

### 4.2 分組邏輯（multi_split_logic）

```mermaid
flowchart TD
    START([開始處理圖片序列]) --> LOOP[取下一張 OCR 結果]

    LOOP --> CHECK{is_voucher?}

    CHECK -->|True\n正式憑證| FINALIZE[結束前一個群組\n若存在]
    FINALIZE --> NEWGROUP[建立新群組\n以此圖片為主]
    NEWGROUP --> LOOP

    CHECK -->|False\n補充照片| HASGROUP{有活躍群組?}
    HASGROUP -->|Yes| APPEND[加入當前群組\n作為 item_image]
    APPEND --> LOOP
    HASGROUP -->|No| SINGLEGROUP[建立獨立單張群組]
    SINGLEGROUP --> LOOP

    LOOP -->|序列結束| OUTPUT([輸出 N 個 expense groups])
```

### 4.3 範例說明

| 輸入序列 | 分組結果 |
|---------|---------|
| `[INVOICE, photo, photo]` | 1 筆：INVOICE + 2 張 item_image |
| `[INVOICE, photo, INVOICE, photo]` | 2 筆：各自含 1 張 item_image |
| `[photo, INVOICE]` | 2 筆：photo 獨立，INVOICE 獨立 |
| `[RECEIPT, RECEIPT]` | 2 筆：各自獨立 |

### 4.4 部署限制

> ⚠️ **重要**：`auto_split_timer.py` 使用 Python 字典（`_timers: dict[str, asyncio.Task]`）管理計時器。此為**程式記憶體內**狀態，不持久化至資料庫。
>
> **限制**：`enable_auto_split=True` 時，**必須使用單 worker 部署**：
> ```bash
> uvicorn main:app --workers 1
> ```
> 多 worker 或多容器環境下，計時器狀態不跨 process 同步，會導致 timer 遺失或重複觸發。

---

## 5. 狀態機與關鍵欄位速查

### 5.1 LINE 對話狀態機

```mermaid
stateDiagram-v2
    [*] --> INIT : 首次互動

    INIT --> BINDING_REAL_NAME : enable_user_binding=True\n提示輸入真實姓名
    BINDING_REAL_NAME --> DEPT_SELECTION : 收到文字訊息\n儲存 real_name

    INIT --> DEPT_SELECTION : enable_user_binding=False

    DEPT_SELECTION --> COLLECTING : 點選部門 QuickReply\nstep="COLLECTING"

    COLLECTING --> COLLECTING : 傳送圖片\n→ append pending_images\n→ 重置 debounce timer

    COLLECTING --> PROCESSING : 點選「確認送出」\ntrigger_by="manual_button"
    COLLECTING --> PROCESSING : Timer 到期（60s）\ntrigger_by="auto_split"

    PROCESSING --> DONE : OCR + 建立 Expense 完成

    DONE --> DEPT_SELECTION : 使用者發起新一輪報帳

    REUPLOADING --> DONE : 使用者重新上傳圖片後\nOCR + 更新 Expense 完成
    DONE --> REUPLOADING : 審核退件後\n推播「重新上傳」按鈕
```

### 5.2 Expense 狀態流轉

```mermaid
stateDiagram-v2
    [*] --> PENDING : OCR 成功\ntotal_amount 有值\n且 KEY_FIELDS confidence ≥ 0.8

    [*] --> NEEDS_MANUAL_REVIEW : OCR 失敗\n或 total_amount IS NULL\n或 任一 KEY_FIELD confidence < 0.8

    PENDING --> APPROVED : 審核人員批准
    PENDING --> REJECTED : 審核人員退件 (+ reject_reason)
    NEEDS_MANUAL_REVIEW --> APPROVED : 人工補填後批准
    NEEDS_MANUAL_REVIEW --> REJECTED : 退件

    REJECTED --> SUPPLEMENTED : 使用者重新上傳圖片
    SUPPLEMENTED --> APPROVED : 再次審核通過
    SUPPLEMENTED --> REJECTED : 再次退件
```

### 5.3 快速設定查詢

| 功能開關 | 環境變數 / 設定 | 預設值 | 說明 |
|---------|--------------|--------|------|
| 自動提交（計時器） | `ENABLE_AUTO_SPLIT` | `False` | True 時需單 worker |
| Debounce 時長 | `AUTO_SPLIT_DEBOUNCE_SECONDS` | `60` | 單位：秒 |
| 真實姓名綁定 | `ENABLE_USER_BINDING` | `True` | 首次互動強制填寫 |
| 退件 LINE 推播 | `ENABLE_LINE_PUSH_REJECT` | `True` | 關閉後靜默退件 |
| Gemini 模型 | `GEMINI_MODEL` | `gemini-2.5-flash` | 可替換為其他版本 |
| 信心閾值 | `KEY_FIELD_THRESHOLD`（程式碼常數） | `0.8` | 需改 `schemas/ocr.py` |

---

*文件由工程團隊維護，如有架構變更請同步更新本文件。*
