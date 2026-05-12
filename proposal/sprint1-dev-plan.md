# 開發計畫書: Sprint 1 — AcctAssist MVP 驗收與生產就緒

> **撰寫者**: product-manager (PM / L1)
> **日期**: 2026-04-08
> **專案**: AcctAssist（LINE Bot 智能報帳系統）
> **Sprint 提案書**: `proposal/sprint1-proposal.md`
> **狀態**: G0 通過，執行中

---

> 本文件在 G0 通過後由 PM 撰寫，依據提案書中勾選的步驟展開技術細節。

## 1. 需求摘要

### 背景

AcctAssist 核心後端與前端 Dashboard 已完成初步開發（含員工實名制、案件流水號、審核 API），但存在三個阻斷發布的缺口：
1. **測試空白**：無任何自動化測試，核心邏輯未驗收
2. **Dashboard 缺口**：前端 `ExpenseDetailView` 缺失，流水號顯示待整合
3. **Webhook 超時**：Postmortem #003 為 `monitoring` 狀態，正式環境有超時風險

Sprint 1 目標：補齊測試、完善 Dashboard、修復 Webhook 超時，並產出部署文件，使系統達到可交付 Staging 的標準。

### 確認的流程

```
G0（需求確認）✅ → 實作（T1/T2/T3 並行）→ G2（程式碼審查）
    → 測試（T1 含測試）→ G3（測試驗收）
    → 文件（T4）→ G4（文件審查）
    → 部署（T5）→ G5（部署就緒）
```

**關卡序列**：G0 → G2 → G3 → G4 → G5
**阻斷規則**：
- G3 阻斷：測試覆蓋率 < 80% 不得進入文件階段
- G5 阻斷：G3 + G4 未通過不得進行部署

---

## 2. 技術方案

### 2.1 後端測試方案

**選定方案：pytest + SQLite in-memory + mock**

- **pytest-asyncio**：支援 async 測試函式
- **httpx.AsyncClient**：FastAPI TestClient 替代方案（支援 async）
- **unittest.mock**：mock Gemini API、LINE SDK（不產生真實 API 呼叫）
- **SQLite in-memory**：替代 PostgreSQL，測試環境無需 Docker

> ⚠️ `serial_number` 依賴 PostgreSQL sequence，需在 conftest.py 中 mock `_generate_serial_number`

| 方案 | 優點 | 缺點 | 結論 |
|------|------|------|------|
| A: SQLite in-memory + mock | 無外部依賴、CI 友善、快速 | 不測試 PG-specific 語法 | ✅ 選定 |
| B: 真實 PostgreSQL（Docker） | 測試環境最接近生產 | CI 需 Docker、慢、依賴外部服務 | ❌ 排除 |

### 2.2 Dashboard 完善方案

**選定方案：AuditModal 整合詳情（不新增獨立路由）**

現有 `AuditModal.vue` 已承擔「詳情檢視 + 審核操作」功能，符合現有 UX 設計。
Sprint 1 的工作聚焦在：
- 新增 `ExpenseDetailView.vue`（獨立詳情頁，供直接訪問 `/expenses/:id`）
- 更新 `router/index.js` 加入 `/expenses/:id` 路由
- 在 `ExpenseTable` 顯示 `serial_number` 欄位
- 驗證核可 / 退件 / 補件操作的完整 E2E 流程

| 方案 | 優點 | 缺點 | 結論 |
|------|------|------|------|
| A: 新增 Detail 路由 + 保留 Modal | 可直連 URL、符合提案書規格 | 需新增元件與路由 | ✅ 選定 |
| B: 僅 Modal 不加路由 | 工作量小 | 無法直接 URL 分享個案 | ❌ 排除 |

### 2.3 Webhook 超時修正方案

**選定方案：FastAPI BackgroundTasks + push_message**

```python
@router.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # 驗證 + 解析（< 20ms）
    background_tasks.add_task(process_image_event, event, db_session)
    return Response(status_code=200)  # 立即回應
```

- 圖片事件：後台執行 OCR → create_expense → push_message
- 需在 `.env` 新增 `LINE_CHANNEL_ACCESS_TOKEN`

---

## 3. UI 圖稿

本 Sprint 不需要新 UI 設計（提案書 G1 未勾選）。
新增的 `ExpenseDetailView.vue` 沿用現有 Tailwind CSS 風格，與 `ExpenseListView` 保持一致。

---

## 4. 檔案變更清單

### 新增

| 檔案 | 用途 |
|------|------|
| `tests/__init__.py` | 測試套件根目錄 |
| `tests/conftest.py` | pytest fixtures（SQLite in-memory DB、mock helper） |
| `tests/unit/__init__.py` | 單元測試模組 |
| `tests/unit/test_expense_service.py` | expense_service CRUD + 狀態轉換測試 |
| `tests/unit/test_ocr_service.py` | OCR 結果解析測試（mock Gemini） |
| `tests/unit/test_line_service.py` | LINE 狀態機操作測試（mock LINE SDK） |
| `tests/integration/__init__.py` | 整合測試模組 |
| `tests/integration/test_webhook.py` | Webhook 流程整合測試 |
| `tests/integration/test_expenses_api.py` | Dashboard API E2E 測試 |
| `frontend/src/views/ExpenseDetailView.vue` | 報帳詳情頁（獨立路由） |
| `.knowledge/deployment-guide.md` | 部署指南（本地 / Staging / Production） |

### 修改

| 檔案 | 變更內容 |
|------|---------|
| `routers/webhook.py` | 加入 BackgroundTasks，圖片事件改為後台處理 |
| `services/line_service.py` | 新增 `push_message` / `push_reject_notification` 方法 |
| `frontend/src/router/index.js` | 新增 `/expenses/:id` 路由 → `ExpenseDetailView` |
| `frontend/src/components/ExpenseTable.vue` | 新增 `serial_number` 欄位顯示 |
| `core/config.py` | 新增 `LINE_CHANNEL_ACCESS_TOKEN` 設定項 |
| `.env.example` | 新增 `LINE_CHANNEL_ACCESS_TOKEN` key |
| `.knowledge/postmortem-log.md` | 更新 #003 狀態為 `resolved` |

### 刪除

無（不刪除任何現有檔案）

---

## 5. 規範文件索引

| 規範文件 | 路徑 | 內容 | 狀態 |
|---------|------|------|------|
| API 設計規範 | `.knowledge/specs/api-design.md` | 端點清單、請求/回應格式、狀態碼 | ✅ 已存在 |
| 資料模型規範 | `.knowledge/specs/data-model.md` | 資料表定義、欄位型別、索引 | ✅ 已建立 |
| 功能規格書 | `.knowledge/specs/feature-spec.md` | 功能流程、邊界條件、驗收標準 | ✅ 已建立 |

> Code Review 時必須對照以上規範文件逐項驗收。

---

## 6. 任務定義與分配

> L1 讀取本節後按依賴順序執行。第一步先執行 `/task-delegation` 建立 `.tasks/` 檔案，系統自動追蹤進度。

### 任務清單

| # | 任務名稱 | 說明 | 負責 Agent | 依賴 | 對應步驟 | 驗收標準 |
|---|---------|------|-----------|------|---------|---------|
| T1 | 後端測試套件 | 建立 `tests/` 完整結構，撰寫 unit + integration 測試，覆蓋 expense_service / ocr_service / line_service / webhook / expenses API | backend-dev | 無 | 實作 + 測試 | 覆蓋率 ≥ 80%，`pytest` 全綠，無 flaky test |
| T2 | Dashboard 詳情頁 | 新增 `ExpenseDetailView.vue`，更新 router 加入 `/expenses/:id`，在 ExpenseTable 顯示 `serial_number` 欄位，驗證核可/退件/補件 E2E 流程 | frontend-dev | 無 | 實作 | 詳情頁可訪問，serial_number 顯示正確，審核操作可完整執行 |
| T3 | Webhook 超時修正 | 改用 BackgroundTasks 處理圖片事件，新增 push_message 推送功能，更新 `.env.example` + `config.py` | backend-dev | 無 | 實作 | Webhook 回應 < 500ms，OCR 完成後 push 正確訊息 |
| T4 | 技術文件 | 建立 `.knowledge/deployment-guide.md`（本地/Staging/Production SOP），更新 postmortem #003 為 resolved | tech-writer | T1, T2, T3 | 文件 | deployment-guide 完成，#003 狀態更新為 resolved |
| T5 | 部署驗證 | Staging 環境部署並驗證：`GET /health` 回 200，LINE Webhook 可接收事件，Dashboard 可正常存取 | devops | T4 | 部署 | Staging 部署成功，3 項驗收指標通過 |

### 依賴圖

```
T1（後端測試）──┐
T2（Dashboard）──┤──→ T4（技術文件）──→ T5（部署驗證）
T3（Webhook 修正）──┘
```

> T1、T2、T3 可並行執行，T4 等三者完成後啟動，T5 等 T4 完成後啟動。

### L1 執行指令

> Tech Lead 複製貼入對應 Agent session 即可啟動。

**Backend Dev（backend-dev）：**
```
請執行 Sprint 1 AcctAssist 開發任務 T1 和 T3。

📄 計畫書：proposal/sprint1-dev-plan.md
📋 你負責的任務：T1（後端測試套件）、T3（Webhook 超時修正）

T1 說明：
- 建立 tests/ 目錄結構（unit/ + integration/ + conftest.py）
- 撰寫 pytest 測試：expense_service / ocr_service / line_service / webhook / expenses API
- 使用 SQLite in-memory，mock Gemini 和 LINE SDK
- 目標：`pytest --cov` 覆蓋率 ≥ 80%，全部通過

T3 說明：
- 修改 routers/webhook.py 改用 BackgroundTasks 處理圖片事件
- 在 services/line_service.py 新增 push_message 方法
- 更新 core/config.py 新增 LINE_CHANNEL_ACCESS_TOKEN
- 更新 .env.example

⚠️ 阻斷規則：T1 和 T3 完成後，需通知 Tech Lead 進行 G2 Code Review。

第一步請先執行 /task-start T1。
```

**Frontend Dev（frontend-dev）：**
```
請執行 Sprint 1 AcctAssist 開發任務 T2。

📄 計畫書：proposal/sprint1-dev-plan.md
📋 你負責的任務：T2（Dashboard 詳情頁）

T2 說明：
- 新增 frontend/src/views/ExpenseDetailView.vue（發票詳情 + OCR 資料 + 審核操作）
- 更新 frontend/src/router/index.js 加入 /expenses/:id 路由
- 更新 frontend/src/components/ExpenseTable.vue 加入 serial_number 欄位
- 驗證核可 / 退件 / 補件操作完整 E2E 流程

規範參考：
- .knowledge/specs/api-design.md（API 格式）
- .knowledge/specs/feature-spec.md（功能規格 F2）

⚠️ 禁止修改：expenseStore.js 的 API 呼叫邏輯（後端 API 契約不可動）

第一步請先執行 /task-start T2。
```

**Tech Writer（tech-writer）：**
```
請執行 Sprint 1 AcctAssist 開發任務 T4（在 T1/T2/T3 完成後執行）。

📄 計畫書：proposal/sprint1-dev-plan.md
📋 你負責的任務：T4（技術文件）

T4 說明：
1. 建立 .knowledge/deployment-guide.md，內容包含：
   - 環境需求（Python 3.10+、Docker、Node.js）
   - 本地開發設定 SOP（.env、Docker Compose、Alembic、前後端啟動）
   - Staging 部署步驟（VM、Nginx、SSL、LINE Webhook URL 設定）
   - 環境變數說明表（含新增的 LINE_CHANNEL_ACCESS_TOKEN）
   - 常見問題（引用 .knowledge/postmortem-log.md）
2. 執行 /pitfall-resolve 將 postmortem-log.md #003 更新為 resolved

參考：
- .knowledge/specs/api-design.md
- .knowledge/postmortem-log.md
- .env.example

第一步請先執行 /task-start T4。
```

**DevOps（devops）：**
```
請執行 Sprint 1 AcctAssist 開發任務 T5（在 T4 完成後執行）。

📄 計畫書：proposal/sprint1-dev-plan.md
📋 你負責的任務：T5（部署驗證）

T5 說明：
- 依照 .knowledge/deployment-guide.md 執行 Staging 部署
- 驗證三項指標：
  1. GET /health → 200 OK
  2. LINE Webhook 可接收測試事件（驗簽通過）
  3. Dashboard 可存取（GET /api/v1/expenses 回傳正確格式）
- 記錄部署結果

第一步請先執行 /task-start T5。
```

### 共用檔案（需協調）

| 檔案 | 涉及任務 | 風險等級 | 說明 |
|------|---------|---------|------|
| `routers/webhook.py` | T1, T3 | 高 | T3 修改主體，T1 需測試它；T3 先完成後 T1 補測試 |
| `services/line_service.py` | T1, T3 | 中 | T3 新增 push_message，T1 需 mock 它 |
| `.env.example` | T3, T4 | 低 | T3 新增 key，T4 文件說明；按順序執行即可 |

---

## 7. 測試計畫

### 單元測試

| 測試檔案 | 覆蓋場景 |
|---------|---------|
| `tests/unit/test_expense_service.py` | create（PENDING/NEEDS_MANUAL_REVIEW）、list（篩選/分頁）、update、delete、reject、get_or_create_user（idempotent）、serial_number 格式 |
| `tests/unit/test_ocr_service.py` | OCRResult 解析（正常/欄位缺失/API 失敗） |
| `tests/unit/test_line_service.py` | set_user_state、get_user_state、delete_user_state、push_message（mock SDK） |

### 整合測試

| 測試檔案 | 覆蓋場景 |
|---------|---------|
| `tests/integration/test_webhook.py` | 完整報帳流程（Text→QuickReply→Image→push）、簽章驗證失敗→400、非 WAITING_PHOTO 狀態收圖→忽略、Webhook 500ms 內回應 |
| `tests/integration/test_expenses_api.py` | GET 清單（分頁/篩選）、GET 單筆、POST 手動建立、PATCH 更新、PATCH /reject、DELETE、GET /export CSV、GET /health |

---

## 8. 風險與緩解

| 風險 | 影響 | 緩解措施 |
|------|------|---------|
| `serial_number` 依賴 PG sequence，SQLite 無法直接使用 | T1 測試環境報錯 | conftest.py 中 `monkeypatch` mock `_generate_serial_number`，回傳固定值 |
| BackgroundTasks 測試難以驗證時序 | T1 Webhook 測試不穩定 | 使用 `asyncio.sleep(0)` 讓後台任務執行，或直接 mock `add_task` 捕獲呼叫 |
| Vue3 詳情頁若重複 AuditModal 邏輯 | T2 程式碼重複 | 提取共用 `ExpenseFields.vue` 元件，Modal 和 DetailView 共用 |
| LINE_CHANNEL_ACCESS_TOKEN 缺失 | T3 push 失敗 | push_message 包 try-except，失敗 log 但不中斷流程；test 用 mock |
| Staging 部署環境未知 | T5 延遲 | T4 先產出完整部署指南，DevOps 依指南執行 |

---

## 9. 文件更新

完成後需同步更新的文件：

- [x] `.knowledge/specs/api-design.md` — 已存在，確認與現行 API 一致
- [x] `.knowledge/specs/data-model.md` — 已建立（Sprint 1）
- [x] `.knowledge/specs/feature-spec.md` — 已建立（Sprint 1）
- [ ] `.knowledge/deployment-guide.md` — T4 產出
- [ ] `.knowledge/postmortem-log.md` — T4 更新 #003 → resolved
- [ ] `.knowledge/file-index.md` — Sprint 結束後更新索引

---

## 10. 任務與審核紀錄（備查）

> 每個任務完成後記錄結果，每次 Review/Gate 通過後記錄決策。本區作為 Sprint 完整稽核軌跡。

### 任務完成紀錄

| 任務 | 完成日期 | 結果 | 備註 |
|------|---------|------|------|
| T1 | | | |
| T2 | | | |
| T3 | | | |
| T4 | | | |
| T5 | | | |

### Review 紀錄

| Review 步驟 | 日期 | 結果 | Review 文件連結 |
|------------|------|------|---------------|
| 實作 Review（T1+T2+T3） | | | |
| 測試 Review（T1） | | | |
| 文件 Review（T4） | | | |

### Gate 紀錄

| Gate | 日期 | 決策 | 審核意見 |
|------|------|------|---------|
| G0 | 2026-04-08 | ✅ 通過 | 提案書 proposal/sprint1-proposal.md |
| G2 | | | |
| G3 | | | |
| G4 | | | |
| G5 | | | |

---

**確認**: [x] PM 確認 / [ ] Tech Lead 確認
