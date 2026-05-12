# AcctAssist 開發指南與專案脈絡

## 1. 系統現有架構與流程 (System Architecture & Flow)

### 1.1 技術棧

| 層級 | 技術 |
|------|------|
| Backend | Python 3.10+, FastAPI |
| Database | PostgreSQL 16 (Docker) |
| ORM | SQLAlchemy 2.0, Alembic |
| AI/OCR | Google Gemini API (`google-genai`, 預設 gemini-2.5-flash) |
| Messaging | LINE Messaging API (`line-bot-sdk`) |
| Frontend (Dashboard) | Vue 3 + TailwindCSS |
| 設定管理 | pydantic-settings + `.env` |
| 測試 | pytest, pytest-asyncio |

### 1.2 專案檔案結構與功用

```
ocr/
├── main.py                   # FastAPI 入口；掛載路由、CORS、啟動時建立 DB 表
├── requirements.txt          # 依賴套件清單
├── .env.example              # 環境變數範本（不含真實金鑰）
├── alembic.ini               # Alembic 遷移設定
├── docker-compose.yml        # PostgreSQL 16 容器定義
│
├── core/
│   ├── config.py             # pydantic-settings；集中管理所有金鑰與參數，統一讀取 .env
│   ├── database.py           # SQLAlchemy engine/session 工廠；提供 get_db() FastAPI dependency
│   └── security.py           # JWT 工具：create_access_token / decode_access_token / hash_password / verify_password
│
├── models/
│   ├── user.py               # User ORM；以 line_user_id 唯一識別 LINE 使用者（含 real_name / employee_id）
│   ├── expense.py            # Expense ORM + ExpenseStatus Enum；報帳主表（核心）
│   ├── expense_image.py      # ExpenseImage ORM；每張圖片的 OCR 詳細結果（is_voucher / category / subtype）
│   ├── admin_user.py         # AdminUser ORM；Dashboard 登入帳號（username / hashed_password / employee_id）
│   └── user_state.py         # UserState ORM；LINE 對話狀態機（step / pending_images / pending_description）
│
├── schemas/
│   ├── user.py               # User 的 Pydantic Request/Response schema
│   ├── expense.py            # ExpenseRead、ExpenseCreate、ExpenseUpdate、ExpenseListResponse
│   ├── expense_image.py      # ExpenseImageRead schema
│   └── ocr.py                # VoucherOCRResult schema（classify_and_extract 回傳結構）
│
├── routers/
│   ├── webhook.py            # POST /webhook；接收 LINE 事件，驅動 Onboarding / 批次收集 / 補件流程
│   ├── expenses.py           # /api/v1/expenses；Dashboard 查詢、審核、CSV 匯出、重新辨識等 API（需 JWT）
│   ├── auth.py               # /api/v1/auth/login + /register；JWT 登入與管理員帳號建立
│   └── admin.py              # /api/v1/admin；系統管理操作（如 setup-rich-menu，需 JWT）
│
├── services/
│   ├── expense_service.py    # Expense CRUD + User get_or_create；封裝所有 DB 操作
│   ├── line_service.py       # LINE API 封裝；管理 UserState、回覆/推播訊息、下載圖片、設定 Rich Menu
│   ├── ocr_service.py        # Google Gemini OCR；classify_and_extract_with_retry（含 Semaphore 限速與指數退避）
│   ├── auto_split_service.py # 自動切割服務（Sprint 3）；Timer 觸發後依 is_voucher 斷點拆分多筆 Expense
│   └── auto_split_timer.py   # 滑動視窗 Timer 管理；schedule / cancel（單 Worker 模式適用）
│
├── scripts/
│   └── setup_rich_menu.py    # 一次性腳本：建立 LINE Bot Rich Menu
│
├── tests/
│   ├── conftest.py           # pytest fixtures（DB session、測試資料等）
│   ├── unit/                 # 單元測試：test_ocr_classify、test_batch_expense、test_auto_split
│   └── integration/          # 整合測試：test_batch_flow、test_auto_split_flow
│
├── alembic/versions/
│   ├── 24e8bd9d46f1_init...              # Migration 01：建立 users + expenses 基礎表
│   ├── 8bd1dbb125a7_add...               # Migration 02：新增 OCR 解析欄位（金額、稅號等）
│   ├── a3f2c1d0e5b8_add...               # Migration 03：新增 user_states 表
│   ├── b7c3e2f1a4d9_add_item_image...    # Migration 04：新增 item_image_url + image_url nullable
│   ├── d4e5f6a7b8c9_images_to_array...   # Migration 05：image_url 改為 ARRAY(String)
│   ├── e1f2a3b4c5d6_expand_user_state... # Migration 06：擴充 user_state.step 長度
│   ├── f3a4b5c6d7e8_add_user_real_name...# Migration 07：User 新增 real_name / employee_id
│   ├── g4b5c6d7e8f9_add_expense_serial...# Migration 08：Expense 新增 serial_number
│   ├── h5c6d7e8f9a0_create_expense_seq...# Migration 09：建立 serial_number PostgreSQL sequence
│   ├── i6d7e8f9a0b1_add_admin_user...    # Migration 10：建立 admin_users 表
│   ├── j7c8d9e0f1a2_add_supplemented...  # Migration 11：ExpenseStatus 新增 SUPPLEMENTED
│   ├── k8d9e0f1a2b3_add_expense_images...# Migration 12：建立 expense_images 表 + Expense 批次欄位
│   ├── l9e0f1a2b3c4_add_user_states_p... # Migration 13：UserState 新增 pending_images / pending_description
│   ├── m0f1a2b3c4d5_migrate_waiting_p... # Migration 14：將舊 WAITING_PHOTO step 遷移至 COLLECTING
│   ├── n1g2h3i4j5k6_add_trigger_by...    # Migration 15：Expense 新增 trigger_by 欄位
│   └── o2p3q4r5s6t7_add_voucher_subtype..# Migration 16：ExpenseImage 新增 voucher_subtype / confidence
│
└── uploads/                  # 發票 / 商品圖片本地暫存目錄（{uuid}.jpg）
```

### 1.3 資料庫欄位分類

#### User 表

| 欄位 | 類型 | 說明 |
|------|------|------|
| `id` | UUID (PK) | 系統主鍵 |
| `line_user_id` | str (unique, indexed) | LINE 平台識別碼 |
| `name` | str \| null | LINE 顯示名稱（暱稱） |
| `department` | str \| null | 部門（由 LINE 對話選擇後寫入） |
| `real_name` | str \| null | 真實姓名（Onboarding 身分綁定填入） |
| `employee_id` | str \| null | 工號（預留欄位，目前由管理員手動設定） |
| `created_at` | datetime | 首次登錄時間 |

#### Expense 表

**系統與 LINE 自動帶入（程式填寫，不依賴 OCR）：**

| 欄位 | 說明 |
|------|------|
| `id` | UUID 主鍵 |
| `user_id` | FK → users.id（SET NULL on delete） |
| `serial_number` | 案件流水號，格式 EXP-YYYYMM-NNNN（PostgreSQL sequence 自動產生，唯一） |
| `uploader_name` | 上傳者真實姓名（real_name 優先，fallback 暱稱） |
| `uploader_dept` | 上傳當下使用者選擇的部門 |
| `submitter_dept` | 費用提報者組別（OCR 或人工填寫） |
| `upload_date` | 上傳時間戳 (server_default=now()) |
| `image_url` | 費用憑證圖片路徑陣列 ARRAY(String)（原為單一字串，已改為陣列） |
| `item_image_url` | 商品照片路徑陣列 ARRAY(String) |
| `image_count` | 本次報帳圖片總數（default=1） |
| `user_description` | 使用者對本次報帳的文字備註說明 |
| `voucher_categories` | JSON array 字串；各圖片頂層憑證類型（如 INVOICE / RECEIPT） |
| `voucher_subtypes` | JSON array 字串；各圖片子類型（如 HSR_TICKET / PARKING） |
| `expense_categories` | JSON array 字串；各圖片費用科目（如 TRANSPORTATION / MEAL） |
| `trigger_by` | 觸發來源：`manual_button`（使用者按鈕）/ `auto_split`（60 秒自動切割）/ null（舊資料） |
| `status` | PENDING / APPROVED / REJECTED / NEEDS_MANUAL_REVIEW / SUPPLEMENTED |
| `reject_reason` | 退件原因（REJECTED 時填入） |
| `created_at` / `updated_at` | 建立/更新時間戳 |

**Gemini OCR 解析擷取（AI 辨識結果，可能為 null）：**

| 欄位 | 說明 |
|------|------|
| `submitter_name` | 發票上的申請人姓名 |
| `item_description` | 品項描述 |
| `expense_date` | 消費日期（date 型別） |
| `invoice_number` | 發票號碼 |
| `total_amount` | 總金額 (Decimal 12,2) |
| `net_amount` | 稅前金額 |
| `tax_amount` | 稅額 |
| `seller_tax_id` | 賣方統一編號 |
| `seller_name` | 賣方名稱 |

**Status 判斷規則：**
- OCR 成功且 `total_amount` 有值 → `PENDING`（等待人工審核）
- OCR 失敗或 `total_amount` 為 null → `NEEDS_MANUAL_REVIEW`
- 管理員退回後使用者補件 → `SUPPLEMENTED`

#### ExpenseImage 表（個別圖片 OCR 詳細結果）

| 欄位 | 說明 |
|------|------|
| `id` | UUID 主鍵 |
| `expense_id` | FK → expenses.id（CASCADE delete） |
| `image_url` | 圖片路徑（String 512） |
| `is_voucher` | 是否為正式憑證（True=發票/收據，False=商品照等） |
| `voucher_category` | 頂層文件類型（INVOICE / RECEIPT / TRANSPORTATION 等） |
| `voucher_subtype` | 子類型（HSR_TICKET / FUEL / EXEMPT_INVOICE 等） |
| `expense_category` | 費用科目（MEAL / STATIONERY / TRANSPORTATION 等） |
| `sequence_order` | 圖片在批次中的順序（從 1 開始） |
| `ocr_result` | JSON 字串；VoucherOCRResult.model_dump_json 完整結果 |
| `ocr_confidence` | Gemini overall_confidence 分數（0.000–1.000） |
| `created_at` | 建立時間戳 |

#### AdminUser 表（Dashboard 登入帳號）

| 欄位 | 說明 |
|------|------|
| `id` | UUID 主鍵 |
| `username` | 登入帳號（unique, indexed） |
| `hashed_password` | bcrypt 雜湊密碼 |
| `employee_id` | 工號（unique, nullable） |
| `display_name` | 顯示姓名（nullable） |
| `created_at` | 建立時間戳 |

#### UserState 表（LINE 對話狀態機）

| 欄位 | 說明 |
|------|------|
| `line_user_id` (PK) | LINE 使用者識別碼 |
| `step` | 當前步驟：`COLLECTING`（收集圖片中）/ `BINDING_REAL_NAME`（Onboarding 填姓名）/ `REUPLOADING_{expense_id}`（補件上傳） |
| `dept` | 此次對話選擇的部門 |
| `pending_images` | JSON array 字串；已累積的圖片佇列（含 path / timestamp / message_id） |
| `pending_description` | 使用者輸入的文字備註（COLLECTING 期間累積） |
| `updated_at` | 最後更新時間 |

### 1.4 端到端資料處理流程

**情境 A：首次使用者 Onboarding + 批次報帳**

```
Step 1  使用者傳送任意訊息（首次）
        ↓
Step 2  POST /webhook → webhook.py 驗證 X-Line-Signature，解析 MessageEvent
        expense_service.get_or_create_user() → 查詢/建立 users 記錄
        ↓
Step 3  [ENABLE_USER_BINDING=True] user.real_name 為空
        → line_service.set_user_state(step="BINDING_REAL_NAME")
        → 要求使用者輸入真實姓名
        ↓
Step 4  使用者輸入姓名 → expense_service.update_user_real_name()
        → 清除狀態，回應「綁定成功，請選擇組別」
        ↓
Step 5  [user.department 為空] → line_service.reply_with_dept_selection()
        LINE 回傳 QuickReply 部門選單（由 DEPARTMENTS 環境變數設定）
        ↓
Step 6  使用者點選部門 → expense_service.update_user_department()
        → 回應「組別已更新，請上傳照片」
        ↓
Step 7  使用者傳送發票圖片 → ImageMessageContent
        line_service.download_image() → 下載至 uploads/{uuid}.jpg
        ↓
Step 8  SELECT FOR UPDATE → 累積至 UserState.pending_images（JSON array）
        UserState.step = "COLLECTING"
        ↓
Step 9  [ENABLE_AUTO_SPLIT=True]
        → auto_split_timer.schedule(line_user_id, debounce_sec, callback)
          （每次收到圖片都重置 60 秒滑動視窗）
        （可繼續上傳更多圖片，步驟 7–9 循環）
        ↓
Step 10 [路徑 A] 使用者點選「確認送出」PostbackEvent (action=confirm_submit)
         auto_split_timer.cancel() → 取消自動計時
         取出 pending_images → 立即清空（防重複）
        [路徑 B] 60 秒未操作 → auto_split_timer 觸發 auto_split_service.auto_split_process()
        ↓
Step 11 BackgroundTask: _process_batch()
        並行 OCR（asyncio.gather + Semaphore 限速，最多 3 張同時）
        classify_and_extract_with_retry → 每張最多重試 3 次（指數退避）
        → 回傳 list[VoucherOCRResult]
        ↓
Step 12 [auto_split 路徑] auto_split_service 依 is_voucher=True 斷點拆分為多個群組
        每群組各自呼叫 create_batch_expense(trigger_by="auto_split")
        [confirm_submit 路徑] create_batch_expense(trigger_by="manual_button")
        ↓
Step 13 INSERT Expense + ExpenseImage（每張圖各一筆）至 PostgreSQL
        serial_number 由 PostgreSQL sequence 自動產生（EXP-YYYYMM-NNNN）
        ↓
Step 14 line_service.push_text() → 推播報帳完成摘要（含案件編號）給使用者
```

**情境 B：管理員退回 → 使用者補件**

```
Step 1  Dashboard: PATCH /api/v1/expenses/{id}/reject（reason）
        → DB status = REJECTED
        → [ENABLE_LINE_PUSH_REJECT=True] line_service.push_reject_notification()
          LINE 推播退件通知（含「重新上傳」Postback 按鈕）
        ↓
Step 2  使用者點選「重新上傳」→ PostbackEvent (action=reupload, expense_id=xxx)
        → set_user_state(step="REUPLOADING_{expense_id}")
        ↓
Step 3  使用者傳送新照片 → download_image()
        await ocr_service.extract_invoice_data()（單張 OCR）
        expense_service.reupload_expense() → 更新原始 Expense，status = SUPPLEMENTED
        line_service.delete_user_state() + reply 補件成功摘要
```

**情境 C：使用者查詢進度**

```
傳送「查詢進度」或「查詢」→ 回傳最近 3 筆報帳狀態
傳送「EXP-YYYYMM-NNNN」格式 → 查詢指定單號狀態
```

**Dashboard 審核 API（Vue3 前端對接點）：**

| Method | Path | 說明 |
|--------|------|------|
| `POST` | `/api/v1/auth/login` | 帳密登入，回傳 JWT access_token |
| `POST` | `/api/v1/auth/register` | 建立管理員帳號（含 display_name / employee_id） |
| `GET` | `/api/v1/expenses` | 報帳清單；支援 `status` / `date_from` / `date_to` 過濾 + 分頁 |
| `GET` | `/api/v1/expenses/export` | 匯出 CSV（支援相同過濾條件，附 BOM 供 Excel 使用） |
| `POST` | `/api/v1/expenses` | Dashboard 手動新增費用（不透過 LINE） |
| `GET` | `/api/v1/expenses/{id}` | 單筆報帳詳情 |
| `PATCH` | `/api/v1/expenses/{id}` | 部分更新 Expense 欄位（審核表單儲存） |
| `DELETE` | `/api/v1/expenses/{id}` | 刪除單筆費用紀錄 |
| `PATCH` | `/api/v1/expenses/{id}/reject` | 退回單據 + 可選 LINE 推播通知 |
| `POST` | `/api/v1/expenses/{id}/images` | 追加補件圖片（expense / item 類型） |
| `POST` | `/api/v1/expenses/{id}/images/replace` | 替換指定索引圖片 |
| `GET` | `/api/v1/expenses/{id}/images` | 查詢該費用所有 ExpenseImage（按 sequence_order ASC） |
| `POST` | `/api/v1/expenses/{id}/reocr` | 重新執行 OCR 並更新欄位 |
| `POST` | `/api/v1/admin/setup-rich-menu` | 建立 LINE Bot Rich Menu（需 JWT） |
| `POST` | `/webhook` | LINE Webhook（非 Dashboard 使用） |
| `GET` | `/health` | 健康檢查 |

> **認證**：所有 `/api/v1/expenses` 及 `/api/v1/admin` 端點需在 Header 帶入 `Authorization: Bearer <token>`（由 `/auth/login` 取得）。

所有 API 統一回傳格式：
```json
{ "status": "success" | "error", "data": { ... } | null, "message": "說明文字" }
```

---

## 2. 嚴格遵守的開發規範 (Strict Coding Rules)

### 2.1 通用原則 (General)

**命名語言：**
- 程式碼變數、函式、類別 → 全英文命名
  - Python：`snake_case`
  - JavaScript / TypeScript：`camelCase`，元件名稱用 `PascalCase`
- 程式碼註解、Commit Message、文件 → 正體中文

**不破壞現有邏輯：**
- 修改現有檔案時，除非明確要求重構，否則保留原有邏輯結構，僅針對目標需求進行增修
- 新增功能優先以新增模組/服務實現，避免侵入核心

**安全第一：**
- 絕對禁止在程式碼中硬寫（Hardcode）任何 API Keys、密碼或連線字串
- 所有機敏設定必須統一透過 `.env` 讀取，並在 `core/config.py` 集中管理
- `.env.example` 維護完整 key 清單（value 留空或假值）

**Git Commit 格式（Conventional Commits）：**
- `feat:` 新功能
- `fix:` 修復 bug
- `refactor:` 重構
- `docs:` 文件
- `test:` 測試
- `chore:` 建置/工具設定

---

### 2.2 後端規範 (Backend - FastAPI)

**強型別（Type Hints）：**
- 所有 Python 函式參數、回傳值必須包含完整的 Type Hints
- 符合 PEP8 規範（行寬 120）
- import 順序：stdlib → third-party → local

**非同步設計（Async/Await）：**
- 資料庫操作（SQLAlchemy）與外部 API 呼叫（httpx、Gemini、LINE SDK）必須全程使用 `async/await`
- 禁止在 async 函式中混用同步阻塞代碼

**職責分離（Clean Architecture）：**

| 層級 | 只負責 | 絕對不做 |
|------|--------|---------|
| `routers/` | 接收請求、參數驗證、呼叫 service、組裝回應 | 業務邏輯、LLM 呼叫、DB 查詢 |
| `services/` | 業務邏輯、LLM/API 呼叫、DB 操作封裝 | 路由綁定、回應格式化 |
| `models/` | ORM 資料結構定義 | 業務邏輯 |
| `schemas/` | 請求/回應資料驗證（Pydantic） | 資料庫操作 |
| `core/` | 全域設定、DB session 管理 | 業務邏輯 |

---

### 2.3 前端規範 (Frontend - Vue 3)

**框架標準：**
- 強制使用 Vue 3 **Composition API** 與 `<script setup>` 語法糖
- 禁止使用 Options API

**樣式管理：**
- 統一使用 **Tailwind CSS** 進行排版與樣式設計
- 減少自定義 CSS；若需自定義，限定在對應元件的 `<style scoped>` 區塊內

**API 串接：**
- 統一封裝 **Axios 實例**（baseURL、timeout、headers 集中設定）
- 實作統一的**錯誤攔截器（Interceptors）**，在 interceptor 層集中處理 HTTP 錯誤與 token 失效
- 禁止在元件中直接呼叫 `axios.get()` / `fetch()`，一律透過封裝的 API 模組

---

### 2.4 錯誤處理 (Error Handling)

**後端：**
- 遇到可預期的錯誤，拋出明確的 `FastAPI HTTPException`，附帶清楚的 `detail` 說明
- 與第三方服務（LINE、Gemini）互動時，必須包含 `try-except` 區塊
- 使用 Python 標準 `logging` 模組記錄例外，方便除錯（禁止用 `print` 代替 log）

```python
# 範例：正確的錯誤處理方式
import logging
logger = logging.getLogger(__name__)

try:
    result = await ocr_service.extract_invoice_data(image_path)
except Exception as e:
    logger.error(f"OCR 處理失敗：{e}", exc_info=True)
    raise HTTPException(status_code=500, detail="發票辨識服務異常，請稍後再試")
```

**前端：**
- API 呼叫一律在 `try-catch` 中處理，或透過 Axios interceptor 統一捕捉
- 錯誤狀態需反映在 UI 上（Toast 通知、錯誤訊息區塊），禁止靜默失敗

---

## 3. 共用開發規則

> 以下兩份文件包含所有 Agent 必須遵循的共用規則，執行任務前**必須先閱讀**。

| 文件 | 內容 |
|------|------|
| `.knowledge/company-rules.md` | 文件治理、命名規範、Commit 紀律、依賴變更規則 |
| `.knowledge/team-workflow.md` | 指揮鏈、Sprint 流程、Gate、Review、上線/回滾 |

---

## 4. 可用指令（Slash Commands）— 強制使用

> **強制規則**：遇到下列「使用時機」描述的場景時，必須執行對應指令，不得跳過或手動替代。

| 指令 | 使用時機 |
|------|---------|
| `/sop-plan` | L1 收到任務，開始規劃前 |
| `/sop-execute` | L2 開始執行任務時 |
| `/sop-review` | L1 審查任務時 |
| `/sprint-proposal` | Sprint 規劃階段 |
| `/dev-plan` | G0 通過後，L1 產出開發計畫 |
| `/task-delegation` | L1 拆解任務到計畫書第 6 節 |
| `/task-start` | Agent 開始執行任務時 |
| `/task-done` | 任務交付 L1 審查時 |
| `/task-approve` | L1 審核通過後 |
| `/review` | 程式碼完成後送審 |
| `/gate-record` | Gate 審查結果出爐時 |
| `/pm-review` | L1 提交 Gate 後，PM 核對 |
| `/pre-deploy` | 部署前最後確認（G5） |
| `/pitfall-record` | 發現新問題/踩坑時立即記錄 |
| `/sprint-retro` | Sprint 結束時 |

---

## 5. 專案文件索引

| 文件 | 說明 |
|------|------|
| `.knowledge/company-rules.md` | 共用開發規則（必讀） |
| `.knowledge/team-workflow.md` | 共用工作流程（必讀） |
| `.knowledge/postmortem-log.md` | 踩坑紀錄（Python/FastAPI/LINE Bot 相關） |
| `.knowledge/project-overview.md` | 專案概述 |
| `.knowledge/file-index.md` | Sprint 紀錄與歷史文件索引 |
