# AcctAssist 系統測試報告

**報告日期：** 2026-05-19  
**測試執行者：** Claude Code（資深工程師視角審視）  
**測試範圍：** 全系統壓力、邊界值、安全性、並發與網路韌性  
**最終結果：** 81 tests passed, 0 failed, 3 warnings（風險記錄）

---

## 1. 測試背景與目的

### 1.1 背景

AcctAssist 是一套 LINE Bot 報帳系統，使用者透過 LINE 上傳發票圖片，系統以 Google Gemini AI 自動辨識後送交人工審核。核心流程涵蓋圖片下載、OCR 辨識、批次建立費用記錄、自動切割等多個異步操作。

本次測試的觸發原因：系統目前在正常流量下功能正確，但尚未評估過以下情境：
- 多使用者同時上傳圖片的並發安全性
- 一次上傳大量（50-100 張）圖片的系統行為
- 網路不穩或第三方 API 失敗時的韌性
- 邊界輸入值與資安防護

### 1.2 測試目標

| 目標 | 說明 |
|------|------|
| 找出潛在 Bug | 在功能測試未能覆蓋的情境下找出缺陷 |
| 量化風險 | 以嚴重程度分級，幫助決定修復優先順序 |
| 建立回歸基線 | 後續修復後，用測試驗證問題已解決 |
| 記錄系統行為 | 部分「有 bug」的行為以 Warning 記錄，不強制失敗 |

---

## 2. 測試方法

### 2.1 測試策略

**黑箱 + 白箱混合法**：
- 從服務層（Service Layer）直接呼叫函式（白箱），繞過 HTTP 層以精確驗證業務邏輯
- 對外部依賴（Gemini API、LINE API）全部 mock，確保測試穩定性與速度
- 並發測試使用 `asyncio.gather` 模擬真實的非同步並發情境

**測試隔離**：
- 每個測試使用獨立的 SQLite in-memory DB，測試間互不汙染
- 全部 mock 外部 API，無需真實 API Key
- Race Condition 測試刻意「不修復 bug」，僅記錄現有行為

### 2.2 測試分層

```
tests/
├── unit/               # 純函式 / 單一模組，無 DB 依賴
│   ├── test_boundary.py           # 模組 E：邊界值
│   ├── test_security.py           # 模組 F：安全性
│   ├── test_ocr_service_stress.py # 模組 A：OCR 壓力
│   └── test_network_resilience.py # 模組 D：網路韌性
└── integration/        # 跨模組互動，含 SQLite in-memory DB
    ├── test_concurrent_state.py   # 模組 B：並發狀態機
    └── test_large_batch.py        # 模組 C：大量圖片批次
```

### 2.3 工具與環境

| 項目 | 版本 / 說明 |
|------|------------|
| Python | 3.12 |
| pytest | 8.x |
| pytest-asyncio | 0.24.x |
| SQLite | in-memory（繞過 PostgreSQL 型別限制） |
| OS | Windows 11 Enterprise |
| 外部 API | 全部 mock（Gemini、LINE SDK） |

---

## 3. 測試執行結果總覽

```
============================= test session starts =============================
收集測試：81 items

81 passed, 0 failed, 3 warnings in 4.80s
```

| 模組 | 測試數 | 通過 | 失敗 | 風險 Warning |
|------|--------|------|------|-------------|
| E — 邊界值與輸入驗證 | 19 | 19 | 0 | 0 |
| F — 安全性 | 14 | 14 | 0 | 0 |
| A — OCR 壓力 | 12 | 12 | 0 | 0 |
| D — 網路韌性 | 11 | 11 | 0 | 1 |
| B — 並發 Race Condition | 8 | 8 | 0 | 1 |
| C — 大量圖片批次 | 17 | 17 | 0 | 1 |
| **合計** | **81** | **81** | **0** | **3** |

> **注意**：3 個 Warning 是刻意設計的「風險記錄」，代表測試已成功偵測到系統缺陷，並以 `warnings.warn` 記錄，供後續追蹤修復。

---

## 4. 已發現問題清單

### 4.1 CRITICAL（必須修復，可能導致資料遺失）

---

#### C1 — pending_images 並發 read-modify-write 競爭條件

**位置：** [routers/webhook.py:474-495](routers/webhook.py)  
**測試：** `test_concurrent_state.py::TestPendingImagesAppend::test_concurrent_append_race_condition_documented`

**問題描述：**  
當同一使用者在短時間內快速傳送多張圖片（如連拍），LINE 可能同時觸發多個 Webhook 事件。兩個並發請求都會讀取 `UserState.pending_images`，各自 append 自己的圖片後寫回，**後者覆蓋前者**，導致圖片遺失。

**測試重現步驟：**
```python
# 兩個協程同時讀取 pending_images=[]
# A 讀到 []，B 讀到 []
# A append img_a → []→ [img_a] → 寫回
# B append img_b → []→ [img_b] → 寫回（覆蓋 A）
# 最終只有 [img_b]，img_a 遺失
```

**實際測試輸出：**
```
UserWarning: ⚠️ C1 Race Condition 已確認：並發 read-modify-write 導致圖片遺失！
最終只有 1 張，應有 2 張。
```

**根本原因：**  
`SELECT FOR UPDATE` 寫在 `db.begin_nested()`（Savepoint）內，鎖在 Savepoint 結束時就釋放，而非等到外層 `db.commit()`，鎖保護範圍不足。

**建議修復方案：**
```python
# 錯誤做法：SELECT FOR UPDATE 在 savepoint 中無效
with db.begin_nested():
    db_state = db.execute(select(UserState).with_for_update()).scalar_one_or_none()

# 正確做法：使用外層 session 的 for_update，或改用 PostgreSQL 的 atomic append
db_state = db.execute(
    select(UserState).where(...).with_for_update()
).scalar_one_or_none()
# 確保在 db.commit() 前保持鎖
```

---

#### C2 — Flow B 重複發票更新無鎖

**位置：** [services/expense_service.py:613-630](services/expense_service.py)  
**測試：** 未實作自動測試（需要真實 PostgreSQL）

**問題描述：**  
當使用者上傳商品照片（配合已存在的 WAITING_RETURN 發票），系統先 `SELECT` 找到對應的 Expense，再直接 `UPDATE item_image_url`。中間沒有 `FOR UPDATE` 鎖，兩個並發請求可能都找到同一筆 Expense，各自更新，後者覆蓋前者的商品照片。

**建議修復方案：**
```python
# 加入 with_for_update()
stmt = select(Expense).where(
    Expense.invoice_number == primary_invoice,
    Expense.status == ExpenseStatus.WAITING_RETURN
).with_for_update()
existing_waiting = db.scalar(stmt)
```

---

#### C3 — Global `_timers` dict 並發寫入無鎖

**位置：** [services/auto_split_timer.py:42-55](services/auto_split_timer.py)  
**測試：** `test_concurrent_state.py::TestAutoSplitTimerConcurrency::test_concurrent_schedule_from_multiple_coroutines`

**問題描述：**  
`_timers` 是模組級別的全域 dict，`schedule()` 和 `cancel()` 在同步程式碼中讀寫，但在 asyncio 環境下，多個協程可同時執行 `schedule()`，造成舊 task 未被正確取消，多個 auto_split 定時器同時觸發，同一批圖片建出多筆 Expense。

**建議修復方案：**
```python
# 加入 asyncio.Lock 保護
_timers_lock = asyncio.Lock()

async def schedule(line_user_id: str, ...) -> None:
    async with _timers_lock:
        cancel(line_user_id)
        task = asyncio.create_task(...)
        _timers[line_user_id] = task
```

---

### 4.2 HIGH（應盡快修復，影響系統穩定性）

---

#### H1 — Gemini API 呼叫無 Timeout

**位置：** [services/ocr_service.py:258-264](services/ocr_service.py)  
**測試：** `test_ocr_service_stress.py::TestOcrApiTimeout::test_api_hang_returns_failure_result`

**問題描述：**  
`_client.aio.models.generate_content()` 沒有設定 timeout，若 Gemini API 因網路問題或服務異常而永久掛起，佔用一個 `_OCR_SEMAPHORE` 槽位。系統上限為 3 個並發 OCR，三個請求都掛起時，所有後續 OCR 請求將永久等待（佔滿 Semaphore）。

**測試驗證：**
```python
# 外部 asyncio.wait_for(timeout=0.5) 可以截斷掛起的請求
# 但系統內部目前沒有此保護
with pytest.raises(asyncio.TimeoutError):
    await asyncio.wait_for(classify_and_extract(img), timeout=0.5)
```

**建議修復方案：**
```python
# 在 core/config.py 新增：
ocr_api_timeout_seconds: int = 30

# 在 ocr_service.py 的 classify_and_extract 中：
async with asyncio.timeout(settings.ocr_api_timeout_seconds):
    response = await _client.aio.models.generate_content(...)
```

---

#### H2 — pending_images 無最大數量限制

**位置：** `webhook.py`（累積邏輯）、`core/config.py`（無此設定）  
**測試：** `test_large_batch.py::TestExtremelyLargeBatch::test_100_images_does_not_crash`

**問題描述：**  
`UserState.pending_images` 沒有上限，使用者理論上可以上傳 100 張甚至更多圖片。100 張圖片觸發 `asyncio.gather(100 OCR tasks)`，即使 Semaphore 限制了並發，仍會同時建立 100 個 asyncio Task，消耗大量記憶體，且 Gemini API RPM（每分鐘請求數）限制可能觸發大量 429 錯誤。

**測試結果：**
- 100 張圖片在 mock 環境下可跑完，不崩潰
- 100 筆 pending_images JSON 大小約 12KB（合理範圍）
- **生產環境風險**：Gemini API RPM 限制未知，大批次可能觸發 429 並耗盡 retry

**建議修復方案：**
```python
# 在 core/config.py 新增：
max_images_per_batch: int = 30

# 在 webhook.py 累積圖片前檢查：
if len(current_images) >= settings.max_images_per_batch:
    await line_service.push_text(user_id, f"一次最多上傳 {settings.max_images_per_batch} 張，請先送出再繼續上傳。")
    return
```

---

#### H3 — 圖片下載後無大小驗證

**位置：** [services/line_service.py:564](services/line_service.py)  
**測試：** `test_large_batch.py::TestLargeImageDownload::test_download_15mb_image_no_size_check`

**問題描述：**  
`download_image()` 取得 LINE 圖片內容（`bytes`）後，直接寫入磁碟，沒有檢查 `len(content)` 是否超過 `settings.max_upload_bytes`（設定值 10MB）。`max_upload_bytes` 設定存在但從未被實際使用。

**測試結果：**
```
UserWarning: ⚠️ H3 風險確認：15MB 圖片無大小防護直接寫入磁碟。
建議在 download_image 中加入：if len(content) > settings.max_upload_bytes: raise ValueError
```

**建議修復方案：**
```python
def download_image(message_id: str, save_path: Path) -> Path:
    with ApiClient(_line_config) as api_client:
        blob_api = MessagingApiBlob(api_client)
        content: bytes = blob_api.get_message_content(message_id)

    # 新增大小驗證
    if len(content) > settings.max_upload_bytes:
        raise ValueError(
            f"圖片大小 {len(content) / 1024 / 1024:.1f}MB 超過限制 "
            f"{settings.max_upload_bytes / 1024 / 1024:.0f}MB"
        )

    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(content)
    return save_path
```

---

#### H4 — 圖片下載無 Retry

**位置：** [services/line_service.py:562-568](services/line_service.py)  
**測試：** `test_network_resilience.py::TestOrphanFileOnDownloadFailure::test_download_failure_leaves_no_file`

**問題描述：**  
`download_image()` 對 LINE Content API 的呼叫沒有 retry 機制。LINE CDN 可能因短暫網路波動返回錯誤，一次失敗即整批報帳失敗，使用者需要重新操作。

**建議修復方案：**  
加入簡單的 retry（最多 3 次，退避 1-2 秒），對常見的 `ConnectionError` / `TimeoutError` 重試。

---

#### H5 — DB 連線池無 pool_recycle 設定

**位置：** [core/database.py](core/database.py)  
**測試：** `test_network_resilience.py::TestDatabaseConnectionResilience::test_database_pool_size_is_reasonable`

**問題描述：**  
`create_engine()` 沒有設定 `pool_recycle`，長時間閒置後，DB 連線可能被 PostgreSQL 的 `idle_in_transaction_session_timeout` 或防火牆強制中斷，`pool_pre_ping=True` 雖然可以偵測並重建，但若 DB 重啟時剛好有多個請求，可能同時觸發多個重建，造成短暫連線失敗。

**建議修復方案：**
```python
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,  # 每 30 分鐘強制回收，主動清除 stale 連線
)
```

---

### 4.3 MEDIUM（需要關注，影響運維或安全）

---

#### M1 — `asyncio.Semaphore` 在 Module Import 時建立

**位置：** [services/ocr_service.py:20](services/ocr_service.py)  
**測試：** 測試中以 `patch("services.ocr_service._OCR_SEMAPHORE", fresh_semaphore)` 迴避

**問題描述：**
```python
# 在 module import 時執行，綁定到 import 當下的 event loop
_OCR_SEMAPHORE = asyncio.Semaphore(3)
```
在 pytest 環境（每個 test function 有新的 event loop）或未來若改為多 Worker，Semaphore 會拋出 `RuntimeError: bound to a different event loop`。目前靠「單 Worker 模式」迴避，但沒有強制機制。

**建議修復方案：**
```python
_OCR_SEMAPHORE: asyncio.Semaphore | None = None

def _get_semaphore() -> asyncio.Semaphore:
    global _OCR_SEMAPHORE
    if _OCR_SEMAPHORE is None:
        _OCR_SEMAPHORE = asyncio.Semaphore(3)
    return _OCR_SEMAPHORE
```

---

#### M2 — 圖片下載後 DB Commit 失敗留下孤兒檔案

**位置：** `webhook.py`（圖片下載 → DB commit 兩步驟無 rollback 清理）  
**測試：** `test_network_resilience.py::TestOrphanFileOnDownloadFailure::test_partial_write_orphan_scenario`

**問題描述：**  
若圖片已寫入 `uploads/` 目錄，但後續 DB commit 失敗，檔案不會被清理，長期累積可能耗盡磁碟空間。

**測試結果：**
```
UserWarning: ⚠️ M2 孤兒檔案風險確認：download_image 成功但 DB commit 失敗時，磁碟上會殘留孤兒檔案。
```

**建議修復方案：**  
在 DB 操作的 `except` 或 `finally` 中，若 commit 失敗則刪除已下載的檔案：
```python
try:
    save_path = line_service.download_image(message_id, img_path)
    # ... DB 操作 ...
    db.commit()
except Exception:
    if save_path.exists():
        save_path.unlink(missing_ok=True)
    raise
```

---

#### M3 — OCR 重試退避時間遠短於 API 實際 Timeout

**位置：** [services/ocr_service.py:308-323](services/ocr_service.py)  
**測試：** `test_ocr_service_stress.py::TestOcrRetryBackoff::test_backoff_sleep_is_called_with_correct_values`

**問題描述：**  
退避等待：第 1 次失敗等 1 秒，第 2 次等 2 秒，共 3 秒。但如果 Gemini API 本身因負載過重需要 30 秒才能恢復，三次重試在 3+API_hang 秒內就耗完，無法等到服務恢復。

**測試結果：** 退避計時正確（1s, 2s），但最大等待時間與實際恢復時間不匹配。

---

#### M4 — JWT_SECRET 預設值為弱值

**位置：** [core/config.py:18](core/config.py)  
**測試：** `test_security.py::TestNoHardcodedSecrets::test_jwt_secret_uses_settings`（間接確認）

**問題描述：**  
`JWT_SECRET` 的預設值為 `"change-this-secret-in-production"`。若部署時未設定 `.env`，生產環境使用此弱值，任何人都可以偽造有效的 JWT Token，繞過管理員認證。

**建議：**  
在 `core/config.py` 的 validator 中加入保護：
```python
@validator("jwt_secret")
def jwt_secret_must_be_strong(cls, v):
    if v == "change-this-secret-in-production":
        raise ValueError("JWT_SECRET 不可使用預設值，請在 .env 中設定強密鑰")
    if len(v) < 32:
        raise ValueError("JWT_SECRET 長度不足，建議使用 openssl rand -hex 32 生成")
    return v
```

---

#### M5 — push_text 靜默失敗，呼叫方無法感知

**位置：** [services/line_service.py:301-311](services/line_service.py)  
**測試：** `test_network_resilience.py::TestLineApiTimeout::test_push_text_exception_is_swallowed`

**問題描述：**  
`push_text()` 有 `try-except Exception` 吞掉所有例外，只 log error。呼叫方無法知道推播是否成功，使用者可能沒有收到報帳完成通知，但系統顯示成功。

**現有行為（已測試確認）：**
```python
line_service.push_text("fake_user_id", "訊息")
# 即使 LINE API 失敗，函式也正常返回，不拋例外
```

**建議：**  
對關鍵通知（報帳完成、退件通知）改用 raise，由呼叫方決定是否重試；對非關鍵通知（如提示訊息）保留靜默失敗。

---

### 4.4 LOW（可接受的風險或已知限制）

| 問題 | 位置 | 說明 |
|------|------|------|
| CORS 在 dev 模式下 `*` + credentials | `main.py:33-39` | 開發環境 XSS 風險，生產需確認 CORS_ORIGINS 有正確設定 |
| 序號 5-retry 無退避 | `expense_service.py:111-142` | 高並發下 5 次都 conflict 機率極低，但應加 backoff |
| 圖片路徑陣列無 append 原子操作 | `expense_service.py:300-318` | image_url array 的 mutate 模式在高並發下有 lost update 風險 |

---

## 5. 安全性測試結果

| 測試項目 | 結果 | 說明 |
|---------|------|------|
| LINE Webhook 簽章驗證 | ✅ 正常 | 篡改 body / 錯誤 secret / 空簽章 全部正確拒絕 |
| JWT 過期 token | ✅ 正常 | 過期 token 回傳 None，不拋例外 |
| JWT 竄改 token | ✅ 正常 | Payload 被竄改的 token 回傳 None |
| JWT 錯誤 secret | ✅ 正常 | 用錯誤 secret 解碼回傳 None |
| SQL Injection（Enum 過濾） | ✅ 正常 | Pydantic Enum 驗證拒絕注入字串 |
| SQL Injection（ORM 查詢） | ✅ 正常 | 參數化查詢阻擋注入，表未被 DROP |
| Hardcoded Google API Key | ✅ 無 | 後端代碼無 AIza… 格式字串 |
| Hardcoded Bearer Token | ✅ 無 | 後端代碼無明文 Token |
| Hardcoded 密碼 | ✅ 無 | password= 均為函式呼叫，非明文 |
| JWT Secret 來源 | ✅ 正常 | 使用 settings.jwt_secret，非 hardcoded |
| Gemini API Key 來源 | ✅ 正常 | 使用 settings.gemini_api_key，非 hardcoded |

---

## 6. 邊界值測試結果

| 測試場景 | 結果 | 說明 |
|---------|------|------|
| `pending_images = "[]"` | ✅ 回傳空清單 | 正常處理 |
| `pending_images = None` | ✅ 回傳空清單 | `or "[]"` 兜底生效 |
| `pending_images = ""` | ✅ 回傳空清單 | 同上 |
| `pending_images = "invalid json"` | ✅ 拋出 JSONDecodeError | 由呼叫方負責處理 |
| 混合新舊格式 entry | ✅ 正確解析 | 向後相容機制生效 |
| `total_amount = 0` | ✅ 正確（非 None） | 0 元發票不誤判 NEEDS_MANUAL_REVIEW |
| `total_amount = None`（全部） | ✅ NEEDS_MANUAL_REVIEW | 狀態判斷正確 |
| CREDIT_NOTE 正值自動轉負 | ✅ 正確 | `classify_and_extract` 強制轉負 |
| 序號跨月重置為 0001 | ✅ 正確 | 月份切換時序號正確重置 |
| `user_description` 5000 字 | ✅ 完整儲存 | Text 欄位無長度限制 |
| `uploader_name` 剛好 128 字元 | ✅ 完整儲存 | String(128) 上限內 |

---

## 7. 大量圖片測試結果

| 場景 | 結果 | 備註 |
|------|------|------|
| 50 張圖片並行 OCR | ✅ 全部成功 | 峰值並發 ≤ 3（Semaphore 生效） |
| 50 張圖片結果完整性 | ✅ 50 筆結果無遺失 | asyncio.gather 正確收集 |
| 100 張圖片不崩潰 | ✅ 系統可跑完 | 目前無上限防護（已記錄風險） |
| 100 筆 pending JSON 大小 | ✅ 約 12KB | 遠低於記憶體危險值 |
| `_parse_buffer` 100 筆排序 | ✅ 依 timestamp ASC | 排序邏輯正確 |
| 15MB 圖片下載 | ⚠️ 直接寫入磁碟 | 無大小防護（已記錄為 H3） |
| 5MB 圖片 OCR 不崩潰 | ✅ 正常 | mock PIL.Image.open 成功 |
| 10MB 圖片 OCR 不崩潰 | ✅ 正常 | mock PIL.Image.open 成功 |
| 不存在圖片路徑 | ✅ 回傳 success=False | 不拋例外，優雅失敗 |
| 10 張發票金額加總 | ✅ 正確（1000×10=10000） | 加總邏輯正確 |
| 憑證類型去重 | ✅ 正確 | 20 張 INVOICE → 只有 1 個 "INVOICE" |

---

## 8. 網路韌性測試結果

| 場景 | 結果 | 說明 |
|------|------|------|
| LINE API reply 拋出例外 | ✅ 例外向上傳遞 | `reply_text` 無 try-except |
| LINE API push 拋出例外 | ✅ 靜默失敗（有 try-except） | 已記錄為 M5 |
| 外部 timeout 可截斷掛起 | ✅ TimeoutError 可觸發 | 但系統內部無此保護 |
| Gemini 503 前兩次/第三次成功 | ✅ 正確重試成功 | 退避機制生效 |
| Gemini 三次全失敗 | ✅ 回傳 success=False | 不拋例外，優雅失敗 |
| OCR 失敗 → NEEDS_MANUAL_REVIEW | ✅ 狀態判斷正確 | 業務邏輯正確 |
| 圖片下載失敗不留殘留 | ✅ 無孤兒檔案 | 下載在 write_bytes 前失敗時正常 |
| 下載成功 DB 失敗的孤兒檔案 | ⚠️ 磁碟有殘留 | 已記錄為 M2 |
| DB pool_pre_ping 已啟用 | ✅ 確認 | 可自動偵測 stale 連線 |
| DB pool_size 在合理範圍 | ✅ 確認（10） | 5-20 合理範圍內 |
| DB URL 無 hardcode | ✅ 確認 | 使用 settings.database_url |

---

## 9. 並發測試結果

| 場景 | 結果 | 說明 |
|------|------|------|
| 同步 schedule 10 次只觸發 1 次 | ✅ 通過 | 滑動視窗機制正確 |
| cancel 後 callback 不觸發 | ✅ 通過 | 取消邏輯正確 |
| 並發 schedule 最終火一次 | ✅（但有警示） | 已記錄 C3 風險 |
| 不同 user 的 Timer 互相獨立 | ✅ 通過 | cancel A 不影響 B |
| 20 個並發序號全部唯一 | ✅ 通過 | retry 機制保護有效 |
| 序號格式一致性 | ✅ 通過 | EXP-YYYYMM-NNNN 格式正確 |
| 順序 append 兩張圖片 | ✅ 兩張都保留 | 正常行為確認 |
| 並發 append（模擬 race） | ⚠️ 只剩 1 張 | C1 Bug 已確認 |

---

## 10. 問題優先級與修復建議

### 建議修復順序

```
Phase 1（立即修復，影響資料完整性）
  1. C1 — SELECT FOR UPDATE 在 Savepoint 中失效 → 圖片遺失
  2. H1 — Gemini API 無 timeout → Semaphore 永久卡死
  3. H3 — 圖片下載無大小驗證 → 磁碟耗盡風險

Phase 2（近期修復，影響系統穩定性）
  4. C2 — Flow B 更新無鎖 → 商品照片遺失
  5. H2 — pending_images 無上限 → API Rate Limit 風險
  6. M2 — 孤兒檔案問題 → 磁碟洩漏
  7. M4 — JWT Secret 弱值 → 生產環境前必須設定

Phase 3（後續優化，影響運維品質）
  8. C3 — Timer dict 無鎖 → 加 asyncio.Lock
  9. H4 — 圖片下載無 Retry → 提升韌性
  10. M1 — Semaphore 在 import 建立 → 改為 lazy init
  11. M3 — OCR 退避時間偏短 → 增加最大等待時間
```

### 預估修復工時

| 問題 | 難度 | 預估時間 | 需要測試更新 |
|------|------|---------|-------------|
| C1 SELECT FOR UPDATE 修復 | 中 | 2h | 是（需 PostgreSQL） |
| H1 Gemini timeout | 低 | 0.5h | 否（現有測試已覆蓋） |
| H3 圖片大小驗證 | 低 | 0.5h | 否（現有測試已覆蓋） |
| C2 Flow B 加鎖 | 中 | 1h | 是 |
| H2 批次上限 | 低 | 1h | 否 |
| M2 孤兒檔案清理 | 低 | 1h | 否（現有測試已覆蓋） |
| M4 JWT Secret 驗證 | 低 | 0.5h | 否 |
| C3 Timer dict 加鎖 | 中 | 2h | 否（現有測試會抓到） |

---

## 11. 測試覆蓋率評估

### 已覆蓋的高風險場景

- [x] OCR Semaphore 並發控制
- [x] 重試退避機制（時間、次數）
- [x] 大圖片 OCR 行為
- [x] 空值與無效 JSON 輸入
- [x] 跨月序號重置
- [x] 長字串儲存邊界
- [x] JWT token 各種異常狀態
- [x] LINE 簽章驗證
- [x] SQL Injection 防護
- [x] Hardcoded 機敏資訊掃描
- [x] Race Condition 行為記錄（C1）
- [x] Timer 滑動視窗機制
- [x] 大批次（100 張）行為
- [x] 網路失敗的 graceful degradation

### 尚未覆蓋（Phase 2 建議）

- [ ] 真實 PostgreSQL 的 SELECT FOR UPDATE 並發測試（需要真實 DB）
- [ ] Webhook 端對端壓力測試（需要真實 LINE 簽章環境）
- [ ] DB 連線池耗盡的實際行為（需要控制 pool_size）
- [ ] Gemini API Rate Limit（429）的真實回應解析
- [ ] 多 Worker 環境下的 Semaphore 問題驗證

---

## 12. 附錄：測試檔案索引

| 檔案 | 模組 | 測試數 |
|------|------|--------|
| [tests/unit/test_boundary.py](tests/unit/test_boundary.py) | E — 邊界值 | 19 |
| [tests/unit/test_security.py](tests/unit/test_security.py) | F — 安全性 | 14 |
| [tests/unit/test_ocr_service_stress.py](tests/unit/test_ocr_service_stress.py) | A — OCR 壓力 | 12 |
| [tests/unit/test_network_resilience.py](tests/unit/test_network_resilience.py) | D — 網路韌性 | 11 |
| [tests/integration/test_concurrent_state.py](tests/integration/test_concurrent_state.py) | B — 並發 Race | 8 |
| [tests/integration/test_large_batch.py](tests/integration/test_large_batch.py) | C — 大量圖片 | 17 |

**執行指令：**
```bash
# 執行所有新增測試
python -m pytest tests/unit/test_boundary.py tests/unit/test_security.py \
  tests/unit/test_ocr_service_stress.py tests/unit/test_network_resilience.py \
  tests/integration/test_concurrent_state.py tests/integration/test_large_batch.py \
  -v --tb=short

# 執行全套測試（含既有測試）
python -m pytest tests/ -v --tb=short
```
