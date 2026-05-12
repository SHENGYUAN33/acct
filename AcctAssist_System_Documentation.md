# AcctAssist 系統詳細說明書與安全檢測報告

## 壹、系統架構與功能總覽

AcctAssist 是一套基於 LINE Messaging API 與 Google Gemini OCR 的智慧報帳審核系統。員工可直接透過 LINE 上傳發票或收據，系統將自動進行辨識、分類並建立報帳記錄；財務或管理人員則可透過 Vue3 開發的 Dashboard 進行審核、退回或要求補件。

### 1. 核心技術棧
*   **後端框架**: Python 3.10+ / FastAPI
*   **資料庫**: PostgreSQL 16 (透過 SQLAlchemy 2.0 ORM 與 Alembic 進行版本控制)
*   **AI 引擎**: Google Gemini API (`gemini-2.5-flash`)，負責圖像辨識、場景推論與會計資料萃取
*   **通訊介面**: LINE Messaging API，提供使用者互動介面（上傳、查詢、修改個人資料）
*   **前端儀表板**: Vue 3 + TailwindCSS (位於 `frontend` 目錄)

### 2. 主要系統模組
系統主要劃分為以下幾個核心路由與服務 (`routers/` & `services/`)：

*   **Webhook 模組 (`routers/webhook.py`, `services/line_service.py`)**: 
    負責接收 LINE 平台的事件推送，包含使用者綁定（姓名、組別設定）、接收圖片上傳、指令互動（如「查詢進度」），並處理使用者的操作狀態（如 `COLLECTING`、`REUPLOADING` 等）。
*   **OCR 辨識模組 (`services/ocr_service.py`)**:
    核心業務邏輯，將使用者上傳的圖片送交 Gemini API 進行「三步驟推理」：場景推理（判斷是發票、收據、高鐵票等）、欄位萃取（發票號碼、金額、日期、統編等）、信心評分（評估辨識準確度，若過低則標記需人工審核）。
*   **費用管理模組 (`routers/expenses.py`, `services/expense_service.py`)**:
    提供 Dashboard 使用的 RESTful API，包含報帳單的 CRUD（建立、查詢、修改、刪除）、審核狀態變更、CSV 報表匯出、補件圖片處理與重新辨識 (ReOCR) 功能。
*   **認證授權模組 (`routers/auth.py`, `core/security.py`)**:
    使用 JWT (JSON Web Tokens) 與 bcrypt 雜湊，負責 Dashboard 管理員的註冊與登入驗證。

### 3. 報帳狀態機 (ExpenseStatus)
報帳單會在以下狀態之間流轉：
*   `PENDING`: 審核中（OCR 辨識成功，等待管理員確認）。
*   `NEEDS_MANUAL_REVIEW`: 需人工審核（OCR 信心分數低或無法萃取金額）。
*   `APPROVED`: 已核准。
*   `REJECTED`: 已退回（管理員輸入原因並透過 LINE 推播通知員工）。
*   `SUPPLEMENTED`: 已補件（員工針對被退回或有疑問的單據重新上傳照片）。
*   `WAITING_RETURN` / `COMPLETED`: 處理包含「物品照片」與「單據」分離的補件情境。
*   `REPLACED_VOID`: 已作廢（被換單或折讓單取代）。

---

## 貳、目前系統的安全漏洞與風險評估

經過針對後端程式碼（特別是 `routers` 與 `core` 目錄）的詳細審查，發現目前系統存在以下**高風險與中風險漏洞**，建議盡速修復：

### 🚨 1. 嚴重的越權漏洞：未受保護的管理員註冊端點（High / Critical）
**問題描述：**
在 `routers/auth.py` 中的 `POST /api/v1/auth/register` 端點，程式碼註解提到「⚠️ 此端點建議在正式環境部署後透過 config 關閉（enable_register=False）」，但**實際上程式碼中完全沒有實作任何 `enable_register` 的檢查邏輯**。

**影響：**
目前該端點處於完全公開狀態，任何人（攻擊者）都可以直接發送 HTTP POST 請求至該端點，隨意建立擁有最高權限的 Dashboard 管理員帳號。建立後即可獲取 JWT Token，登入後台並存取、篡改所有員工的報帳資料與個資。

**修復建議：**
在 `auth.py` 的 `register` 函式開頭加入環境變數檢查，若非開發環境或未明確開啟則拒絕請求，或直接在正式環境移除此路由：
```python
if getattr(settings, "enable_register", False) is False:
    raise HTTPException(status_code=403, detail="註冊功能未開放")
```

### 🚨 2. 阻斷服務攻擊 (DoS)：記憶體耗盡漏洞（Medium / High）
**問題描述：**
在 `routers/expenses.py` 中的圖片上傳端點（`upload_expense_image` 與 `replace_expense_image`），使用了以下邏輯讀取檔案：
```python
content = await file.read()
if len(content) > settings.max_upload_bytes:
    raise HTTPException(...)
```
**影響：**
`await file.read()` 會在判斷大小之前，**將整個檔案載入至系統記憶體 (RAM) 中**。如果惡意使用者上傳數個高達幾 GB 的偽造圖片檔案，伺服器的記憶體將瞬間被耗盡，導致 OOM (Out of Memory) 崩潰，讓系統停止服務。

**修復建議：**
應利用 FastAPI 的 `SpooledTemporaryFile` 特性，透過分塊讀取（Chunking）來檢查大小，或直接信任框架的限制設定：
```python
size = 0
async for chunk in file.iter_chunked(1024 * 1024):  # 每次讀取 1MB
    size += len(chunk)
    if size > settings.max_upload_bytes:
        raise HTTPException(status_code=400, detail="檔案超過大小限制")
```

### ⚠️ 3. 並發流水號生成可能的效能瓶頸 (Low)
**問題描述：**
在 `services/expense_service.py` 的 `_generate_serial_number` 中，使用了 `SELECT MAX(serial_number)` 來決定下一個序號，並透過 `for _attempt in range(5)` 捕捉 `IntegrityError` 來處理並發 (Race Condition)。
**影響：**
這在低併發下運作良好且安全，但若在月底報帳高峰期，多個 Worker 同時建單時會造成頻繁的 Transaction Rollback 與重試。
**修復建議：**
這是可接受的設計，但若未來規模擴大，建議改用 PostgreSQL 的 `Sequence` 或在 DB 建立一個獨立的計數器表 (Counter Table) 配合 `FOR UPDATE` 來發號。

### ⚠️ 4. CORS 設定潛在風險 (Low)
**問題描述：**
`main.py` 中的 `_cors_origins = ["*"] if settings.app_env == "development" else settings.cors_origins`。
**影響：**
若上線時未正確在 `.env` 中設定 `CORS_ORIGINS`，可能會因為預設為空陣列導致前端無法連線，或是開發者為了方便在正式環境依然保持 `*`，導致跨站請求偽造 (CSRF) 風險（雖然目前使用的是 JWT Bearer Token，不受傳統 Cookie CSRF 影響，但仍非最佳實踐）。

---

## 參、總結與建議行動清單
這是一套邏輯清晰、整合 AI 相當深入的報帳系統。OCR 的 Prompt 設計非常精良，涵蓋了台灣會計的各類複雜單據情境。

**首要待辦事項：**
1. **立即修補 `auth.py` 的 `register` 端點**，限制公開註冊管理員帳號。
2. **優化 `expenses.py` 內的檔案上傳邏輯**，防範大檔案造成的記憶體耗盡攻擊。
