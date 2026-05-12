# 後端測試套件

| 欄位 | 值 |
|------|-----|
| ID | T1 |
| 專案 | AcctAssist |
| Sprint | Sprint 1 |
| 指派給 | backend-dev |
| 優先級 | P0 |
| 狀態 | assigned |
| 依賴 | — |
| 預估 | 2d |
| 建立時間 | 2026-04-10T03:09:26.113Z |

---

## 任務描述

建立 `tests/` 完整結構，撰寫 unit + integration 測試，覆蓋 expense_service / ocr_service / line_service / webhook / expenses API。

**技術方案**：pytest + SQLite in-memory + mock
- `pytest-asyncio`：支援 async 測試函式
- `httpx.AsyncClient`：FastAPI TestClient 替代方案
- `unittest.mock`：mock Gemini API、LINE SDK
- SQLite in-memory：替代 PostgreSQL，無需 Docker

**新增檔案**：
- `tests/__init__.py`
- `tests/conftest.py`（SQLite in-memory DB、mock helper）
- `tests/unit/__init__.py`
- `tests/unit/test_expense_service.py`
- `tests/unit/test_ocr_service.py`
- `tests/unit/test_line_service.py`
- `tests/integration/__init__.py`
- `tests/integration/test_webhook.py`
- `tests/integration/test_expenses_api.py`

⚠️ `serial_number` 依賴 PostgreSQL sequence，需在 `conftest.py` 中 monkeypatch mock `_generate_serial_number`

## 驗收標準

- [ ] `pytest --cov` 覆蓋率 ≥ 80%
- [ ] 所有測試全部通過（全綠）
- [ ] 無 flaky test（重複執行結果穩定）
- [ ] 測試不依賴外部服務（Gemini / LINE / PostgreSQL 均 mock）
- [ ] `test_expense_service.py`：create PENDING / NEEDS_MANUAL_REVIEW、list 篩選/分頁、update、reject、get_or_create_user idempotent、serial_number 格式
- [ ] `test_ocr_service.py`：OCRResult 正常解析、欄位缺失、API 失敗
- [ ] `test_line_service.py`：set/get/delete_user_state、push_message mock
- [ ] `test_webhook.py`：完整報帳流程、簽章驗證失敗 → 400、非 WAITING_PHOTO 收圖 → 忽略、500ms 內回應
- [ ] `test_expenses_api.py`：GET 清單/單筆、PATCH 更新/reject、GET /health

---

## 事件紀錄

### 2026-04-10T03:09:26.113Z — 建立任務（assigned）
由 L1 透過 /task-delegation 建立
