# 測試套件（Sprint 2）

| 欄位 | 值 |
|------|-----|
| ID | T8 |
| 專案 | AcctAssist |
| Sprint | Sprint 2 |
| 指派給 | qa-engineer |
| 優先級 | P0 |
| 狀態 | done |
| 依賴 | T2,T3,T4,T5,T6,T7 |
| 預估 | 4h |
| 建立時間 | 2026-04-11T00:00:00.000Z |

---

## 任務描述

⚠️ **前置條件**：T2 + T3 + T4 + T5 + T6 + T7 全部完成

撰寫三組測試套件：

### 1. `tests/unit/test_ocr_classify.py`（mock Gemini API）

測試 `classify_and_extract()` 各場景：

| 測試案例 | 預期 |
|---------|------|
| INVOICE 圖片 | `is_voucher=True`，`voucher_category='INVOICE'`，含統編/課稅別 |
| RECEIPT 圖片 | `is_voucher=True`，`voucher_category='RECEIPT'`，含免用統一發票章 |
| LABOR_SERVICE 圖片 | `is_voucher=True`，`voucher_category='LABOR_SERVICE'`，含身分證/實領金額 |
| TRANSPORTATION 圖片 | `is_voucher=True`，`voucher_category='TRANSPORTATION'`，含起訖點 |
| CREDIT_NOTE 圖片 | `is_voucher=True`，`total_amount` 為負數 |
| 非憑證圖片 | `is_voucher=False`，`fields=None` |
| Gemini API 失敗 | `success=False`，不拋出例外，優雅降級 |

### 2. `tests/unit/test_batch_expense.py`

測試 `create_batch_expense()` 費用彙整規則：

| 測試案例 | 預期 |
|---------|------|
| 多憑證加總 | `total_amount` 正確累加 |
| CREDIT_NOTE 負數 | 自動扣除（負數直接加總） |
| 部分 null 金額 | 只加總非 null 部分，`status=PENDING` |
| 全部 null | `total_amount=null`，`status=NEEDS_MANUAL_REVIEW` |
| `voucher_categories` | 去重正確（不重複）|
| `image_count` | 等於 `len(pending_images)` |

### 3. `tests/integration/test_batch_flow.py`（mock LINE SDK + mock Gemini）

E2E 整合測試：

| 測試案例 | 預期 |
|---------|------|
| 首次 Onboarding E2E | 新用戶傳訊息 → Quick Reply → 選部門 → 寫入 `users.department` |
| Onboarding 期間傳照片 | 照片存入 pending，選定部門後繼續，不丟失 |
| 日常批次流程 E2E | 傳 3 張照片 → 按確認送出 → 500ms 內 reply → push 批次摘要 Flex Message |
| 空批次防護 | pending 為空時按確認送出 → 回覆提示，不建立 Expense |
| 貼圖/語音防護 | 回覆提示，`pending_images` 狀態不變 |

### 地雷提醒（postmortem）

- **#004**：conftest.py 中 DB 使用 `AsyncSession` + SQLite in-memory（避免依賴真實 PG）
- `serial_number` 依賴 PG sequence：在 conftest.py 中 monkeypatch mock
- `BackgroundTask` 時序問題：使用 `asyncio.sleep(0)` 或直接 mock `add_task`

## 驗收標準

- [ ] `pytest` 全綠（無 flaky test）
- [ ] `classify_and_extract` 覆蓋率 ≥ 80%
- [ ] `create_batch_expense` 費用彙整規則測試全數通過
- [ ] Onboarding E2E 通過
- [ ] 批次流程 E2E 通過（含 500ms 回應驗證）
- [ ] 空批次防護通過
- [ ] 貼圖/語音防護通過

---

## 事件紀錄

### 2026-04-11T00:00:00.000Z — 建立任務（assigned）
由 L1（project-lead）透過 /task-delegation 建立
⚠️ 等待 T2~T7 全部完成後解鎖

### 2026-04-10T18:36:39.000Z — 開始執行（in_progress）
T2~T7 全數通過 L1 審查，由 L1（project-lead）委派給 qa-engineer 啟動

### 2026-04-10T18:36:39.000Z — 完成交付（in_review）
撰寫完成三組測試套件，pytest 全數通過（24/24）：
- `tests/unit/test_ocr_classify.py`：8 tests，覆蓋 classify_and_extract() 所有分支
- `tests/unit/test_batch_expense.py`：8 tests，覆蓋 create_batch_expense() 費用彙整規則
- `tests/integration/test_batch_flow.py`：8 tests，覆蓋 Onboarding/批次/空批次/貼圖 E2E 流程
地雷紀錄：
- psycopg2 在測試環境未安裝，需在 test 頂層注入 sys.modules mock
- sqlalchemy.orm.with_for_update 在 SQLAlchemy 2.0.39 不存在，需 monkey-patch
- FastAPI startup 事件呼叫 Base.metadata.create_all，需 mock 避免連線 PG
- SQLAlchemy ORM identity map 與 raw SQL 混用導致 ObjectDeletedError，改用 mock User object
