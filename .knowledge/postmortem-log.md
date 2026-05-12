# AcctAssist 踩坑紀錄 (Postmortem Log)

> **用途**: 記錄開發過程中遇到的問題、解法、預防措施
> **更新規則**: 發現新問題立即執行 `/pitfall-record`，解決後執行 `/pitfall-resolve`
> **版本**: v1.1 (Sprint 2)
> **最後更新**: 2026-04-11

---

## 使用說明

### 何時記錄？
- ✅ 發現新的技術陷阱或限制
- ✅ 遇到非預期的錯誤或行為
- ✅ 文件未記載的關鍵細節
- ✅ 重複出現的問題
- ✅ 需要特殊處理的邊界條件

### 分類定義

| 分類 | 說明 | 範例 |
|------|------|------|
| `config` | 設定檔、環境變數相關 | `.env` 缺少必要參數 |
| `database` | 資料庫操作、ORM 問題 | SQLAlchemy N+1 查詢 |
| `api` | 外部 API 呼叫問題 | LINE/Gemini API 限制 |
| `async` | 非同步程式設計問題 | 混用同步/非同步函式 |
| `deployment` | 部署、Docker 問題 | PostgreSQL 連線失敗 |
| `security` | 安全性漏洞或風險 | API Key 外洩風險 |
| `performance` | 效能問題 | OCR 辨識超時 |
| `dependency` | 套件相依性問題 | 版本衝突 |
| `logic` | 業務邏輯錯誤 | 狀態轉換規則錯誤 |
| `integration` | 系統整合問題 | LINE Webhook 驗證失敗 |

### 狀態定義

| 狀態 | 說明 |
|------|------|
| `open` | 問題已記錄，尚未解決 |
| `resolved` | 已找到解法並實作 |
| `monitoring` | 已解決但需持續觀察 |
| `wontfix` | 已知問題但暫不處理 |

---

## 踩坑記錄表

| # | 分類 | 問題 | 原因 | 解法 | 預防 | 狀態 | 發現日期 | 解決日期 |
|---|------|------|------|------|------|------|---------|---------|
| 001 | `config` | FastAPI 啟動時 `DATABASE_URL` 未定義 | `.env` 檔案未建立或未載入 | 1. 複製 `.env.example` → `.env`<br>2. 確認 `pydantic-settings` 正確讀取 | 在 `config.py` 加入啟動檢查，缺少必要參數時 raise Exception | `resolved` | 2026-04-08 | 2026-04-08 |
| 002 | `database` | Alembic 遷移後欄位未出現 | Docker PostgreSQL volume 快取舊 schema | `docker-compose down -v` 清除 volume 後重新 `up -d` | 每次重大 schema 變更後重啟容器 | `resolved` | 2026-04-08 | 2026-04-08 |
| 003 | `api` | LINE Webhook 回應超時 (5秒限制) | Gemini OCR 辨識耗時過長 | Sprint 2 使用 FastAPI `BackgroundTask`：立即 reply「⏳ 處理中」（< 500ms），OCR + DB 在背景執行完成後 push Flex Message | confirm_submit Postback 固定用 BackgroundTask 架構，reply 必須在 BackgroundTask 啟動前執行 | `resolved` | 2026-04-08 | 2026-04-11 |
| 006 | `dependency` | 測試環境缺少 psycopg2，SQLAlchemy PostgreSQL dialect import 失敗 | pytest 跑測試時未安裝 psycopg2（測試只需 SQLite），但 `core/database.py` 在 module level 就 create_engine | 在每個測試檔頂端（所有 import 之前）注入假的 psycopg2 至 `sys.modules`：`sys.modules.setdefault("psycopg2", _fake_psycopg2)` | conftest.py 中統一注入，或測試環境 requirements-test.txt 加入 psycopg2 | `resolved` | 2026-04-11 | 2026-04-11 |
| 007 | `dependency` | SQLAlchemy 2.0.39 中 `with_for_update` 不在 `sqlalchemy.orm` 頂層 | 版本變動，`with_for_update()` 已移至 `sqlalchemy.orm.strategy_options` 或需從 `sqlalchemy` 直接 import | 測試中 monkey-patch：`import sqlalchemy.orm as _sa_orm; _sa_orm.with_for_update = lambda **kw: None`，或改從 `sqlalchemy` 直接 import | 生產程式碼改用 `from sqlalchemy import select` + `with_for_update()` option 方式調用 | `resolved` | 2026-04-11 | 2026-04-11 |
| 008 | `async` | FastAPI startup 事件呼叫 `Base.metadata.create_all()` 在測試時嘗試連接真實 PG | `main.py` 的 `startup` event 在 import application 時觸發，測試中沒有真實 PG | 在 conftest.py 中 patch：`mocker.patch("core.database.Base.metadata.create_all")` | 測試設定改用 `create_all(bind=engine)` 使用 SQLite in-memory engine | `resolved` | 2026-04-11 | 2026-04-11 |
| 009 | `database` | SQLAlchemy ORM identity map 與 raw SQL 混用導致 `ObjectDeletedError` | 測試中先用 ORM 寫入 User，再用 raw SQL INSERT，ORM session 的 identity map 認為物件已過期 | 改用 MagicMock User 物件取代真實 ORM 物件，避免 identity map 追蹤 | 整合測試中統一使用 ORM 或 raw SQL，不要混用；或用 `db.expunge_all()` 清除 identity map | `resolved` | 2026-04-11 | 2026-04-11 |
| 004 | `async` | SQLAlchemy 查詢報錯 `greenlet_spawn` | 在 async 函式中使用同步 session | 統一使用 `AsyncSession` + `await` | Code Review 時檢查 DB 操作是否為 async | `resolved` | 2026-04-08 | 2026-04-08 |
| 005 | `integration` | X-Line-Signature 驗證失敗 | Request Body 被 FastAPI 自動解析，無法重新讀取 raw body | 使用 `Request.body()` 取得原始 bytes，在 middleware 層驗證 | 敏感驗證邏輯統一在 middleware 處理 | `resolved` | 2026-04-08 | 2026-04-08 |
| 010 | `database` | Alembic `op.create_table` 使用 `sa.false()` 作為 server_default 導致 migration 失敗 | `sa.false()` 是 SQLAlchemy clause element，Alembic DDL 序列化時無法正確渲染為 SQL 字串 | 改用 `sa.text("false")` 或字串 `"false"` 作為 server_default；`sa.func.now()` 同樣改用 `sa.text("now()")` | Migration 檔中 server_default 一律使用字串或 `sa.text()`，禁止使用 clause element | `resolved` | 2026-04-12 | 2026-04-12 |
| 011 | `database` | FastAPI startup `create_all` 建立 ORM 表格後再跑 Alembic migration 出現 `DuplicateTable` | `main.py` 的 `Base.metadata.create_all()` 在 server 啟動時建立所有 ORM 對應的表格，但不更新 `alembic_version`；之後執行 `alembic upgrade head` 發現表格已存在即報錯 | 將 migration 所有 DDL 改為冪等寫法：`CREATE TABLE IF NOT EXISTS`、`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`（透過 `op.get_bind()` 執行 raw SQL） | 開發環境中只允許其中一種方式管理 schema：要嘛全用 Alembic，要嘛全用 `create_all`，**不可混用**；生產環境應移除 startup 的 `create_all` | `resolved` | 2026-04-12 | 2026-04-12 |
| 012 | `api` | Pydantic `ExpenseRead` schema 缺少新欄位導致 API 不回傳、前端顯示空白 | 在 ORM Model 新增欄位後，忘記同步更新對應的 Pydantic response schema（`ExpenseRead`）；FastAPI 序列化時只輸出 schema 定義的欄位，新欄位完全不出現在 API response | 在 `schemas/expense.py` 的 `ExpenseRead` 補上 `voucher_categories`、`user_description`、`image_count` 三個欄位 | **Model 新增欄位的 Checklist**：① ORM model ② Alembic migration ③ Pydantic schema ④ 前端 store mapExpense() ⑤ 前端元件顯示，缺任一步驟都會造成靜默失敗 | `resolved` | 2026-04-12 | 2026-04-12 |

---

## 詳細問題記錄

### #001 - DATABASE_URL 未定義導致啟動失敗

**問題描述**:
FastAPI 啟動時拋出 `ValidationError: DATABASE_URL field required`，無法連接資料庫。

**完整錯誤訊息**:
```
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
DATABASE_URL
  Field required [type=missing, input_value={...}, input_type=dict]
```

**根因分析**:
1. 首次部署未建立 `.env` 檔案
2. `.env.example` 僅為範本，未自動複製

**解決方案**:
```bash
# Step 1: 複製範本
cp .env.example .env

# Step 2: 填入真實金鑰
vim .env  # 填寫 DATABASE_URL, LINE_CHANNEL_SECRET, GEMINI_API_KEY
```

**預防措施**:
- 在 `config.py` 加入啟動檢查：
  ```python
  class Settings(BaseSettings):
      DATABASE_URL: str

      @validator('DATABASE_URL')
      def check_database_url(cls, v):
          if not v:
              raise ValueError("DATABASE_URL 必須設定在 .env 中")
          return v
  ```
- 在 `README.md` 強調首次部署步驟

**狀態**: `resolved` (2026-04-08)

---

### #003 - LINE Webhook 回應超時

**問題描述**:
使用者上傳發票後，LINE Bot 無回應，後端 log 顯示 OCR 辨識成功但 LINE API 回報 `Request timeout (5000ms exceeded)`。

**根因分析**:
1. LINE Webhook 要求 5 秒內回應 HTTP 200
2. Gemini OCR 辨識平均耗時 3-8 秒（圖片品質影響）
3. 原實作為同步流程：Webhook → OCR → Reply → 200

**解決方案**:
```python
# 改為非同步處理架構
@router.post("/webhook")
async def webhook(request: Request):
    # 1. 驗證簽章
    # 2. 解析事件
    # 3. 立即回應 200

    # 4. 背景任務處理 OCR
    background_tasks.add_task(process_ocr_and_reply, event)

    return Response(status_code=200)

async def process_ocr_and_reply(event):
    # OCR 辨識
    result = await ocr_service.extract_invoice_data(image_path)
    # 主動推送訊息（非 Reply）
    await line_service.push_message(user_id, result)
```

**效能數據**:
- 改善前：5-10 秒（經常超時）
- 改善後：< 500ms（立即回應）

**預防措施**:
- 所有外部 API 呼叫設定 `timeout=5`
- 超過 3 秒的操作改用背景任務或佇列

**Sprint 2 最終解決方案**：
```python
@router.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    # ... 解析事件 ...
    elif action == "confirm_submit":
        if not pending_images:
            line_api.reply_message(reply_token, TextMessage(text="尚未收到任何照片"))
            return Response(status_code=200)
        # 1. 立即 reply（< 500ms）
        line_api.reply_message(reply_token, TextMessage(text="⏳ 處理中，請稍候..."))
        # 2. 清空 pending（防重複送出）
        state.pending_images = "[]"
        db.commit()
        # 3. 背景執行 OCR + 建立 Expense + push Flex Message
        background_tasks.add_task(_process_batch, ...)
    return Response(status_code=200)
```

**狀態**: `resolved` (2026-04-11, Sprint 2 BackgroundTask 架構確認有效)

---

## 常見問題 FAQ

### Q1: 為什麼 Alembic 遷移後資料表沒變化？
**A**: Docker volume 快取問題，執行 `docker-compose down -v && docker-compose up -d` 清除舊資料。

### Q2: LINE Bot 無回應但後端無錯誤？
**A**: 檢查 Webhook URL 是否正確、ngrok 是否過期、X-Line-Signature 驗證是否通過。

### Q3: Gemini API 403 Forbidden？
**A**: 確認 `.env` 中 `GEMINI_API_KEY` 正確，檢查 API 配額是否用完。

### Q4: SQLAlchemy `DetachedInstanceError`？
**A**: 在 async context 外存取關聯物件，需在 query 時使用 `selectinload()` 或 `joinedload()`。

---

---

### #006 - 測試環境缺少 psycopg2 導致 SQLAlchemy PostgreSQL dialect import 失敗

**問題描述**：
pytest 執行時，SQLAlchemy 嘗試 import PostgreSQL dialect 需要 psycopg2，但測試環境未安裝（測試只需 SQLite in-memory）。

**完整錯誤訊息**：
```
ModuleNotFoundError: No module named 'psycopg2'
```

**根因分析**：
`core/database.py` 在 module level 就呼叫 `create_engine(settings.DATABASE_URL)`（PostgreSQL URL），Python import 時即觸發 psycopg2 import。

**解決方案**：
```python
# 在每個測試檔頂端（所有 import 之前）
import sys
from unittest.mock import MagicMock

_fake_psycopg2 = MagicMock()
_fake_psycopg2.__version__ = "2.9.9"
sys.modules.setdefault("psycopg2", _fake_psycopg2)
sys.modules.setdefault("psycopg2.extensions", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())
```

**狀態**: `resolved` (2026-04-11)

---

### #007 - SQLAlchemy 2.0.39 `with_for_update` 位置變動

**問題描述**：
`from sqlalchemy.orm import with_for_update` 在 SQLAlchemy 2.0.39 找不到該名稱。

**根因分析**：
SQLAlchemy 2.0 版本中 `with_for_update()` 已整合為 Select statement 的方法（`.with_for_update()`），不再是獨立函式。

**解決方案**：
```python
# 生產程式碼：使用 db.get() + begin_nested() + with_for_update
with db.begin_nested():
    state = db.get(UserState, line_user_id)
    # 透過 session.execute(select(...).with_for_update()) 方式
    from sqlalchemy import select
    stmt = select(UserState).where(UserState.line_user_id == line_user_id).with_for_update()
    state = db.execute(stmt).scalar_one()
```

**狀態**: `resolved` (2026-04-11)

---

### #008 - FastAPI startup event 在測試時連接真實 PG

**問題描述**：
整合測試 import `main.app` 時，FastAPI 的 `@app.on_event("startup")` 觸發 `Base.metadata.create_all()`，嘗試連接真實 PostgreSQL。

**解決方案**：
```python
# conftest.py
from unittest.mock import patch, MagicMock

@pytest.fixture(autouse=True)
def mock_pg_startup(monkeypatch):
    with patch("core.database.Base.metadata.create_all"):
        yield
```

**狀態**: `resolved` (2026-04-11)

---

### #009 - ORM identity map 與 raw SQL 混用導致 ObjectDeletedError

**問題描述**：
測試中先用 ORM 寫入 User，再用 raw SQL INSERT ExpenseImage，ORM session 的 identity map 認為物件已過期，存取時拋出 `ObjectDeletedError`。

**解決方案**：
```python
# 改用 MagicMock 替代真實 ORM User 物件，避免 identity map 追蹤
mock_user = MagicMock()
mock_user.id = user_uuid
mock_user.department = "攝影組"
```

**狀態**: `resolved` (2026-04-11)

---

---

### #010 - Alembic `op.create_table` 使用 `sa.false()` 作為 server_default 導致 migration 失敗

**問題描述**：
`alembic upgrade head` 時 migration 報錯，`CREATE TABLE` SQL 無法正確生成 boolean 預設值。

**完整錯誤訊息**：
```
sqlalchemy.exc.CompileError: ... cannot render element of type <class 'sqlalchemy.sql.elements.False_'>
```

**根因分析**：
`sa.false()` 是 SQLAlchemy clause element 物件，Alembic 的 DDL 序列化層無法將其直接渲染為 SQL server_default 字串。同樣問題也存在於 `sa.func.now()` 在某些版本中的行為。

**解決方案**：
```python
# ❌ 錯誤
sa.Column("is_voucher", sa.Boolean, server_default=sa.false())
sa.Column("created_at", sa.DateTime, server_default=sa.func.now())

# ✅ 正確
sa.Column("is_voucher", sa.Boolean, server_default=sa.text("false"))
sa.Column("created_at", sa.DateTime, server_default=sa.text("now()"))
# 或使用字串
sa.Column("is_voucher", sa.Boolean, server_default="false")
```

**預防措施**：
Migration 檔 server_default 一律使用 `sa.text("...")` 或純字串，禁止使用 clause element（`sa.false()`、`sa.true()`、`sa.func.*`）。

**狀態**: `resolved` (2026-04-12)

---

### #011 - FastAPI startup `create_all` 與 Alembic migration 混用導致 `DuplicateTable`

**問題描述**：
執行 `alembic upgrade head` 時報錯 `psycopg2.errors.DuplicateTable: relation "expense_images" already exists`。

**根因分析**：
`main.py` 的 startup event 呼叫 `Base.metadata.create_all(bind=engine)`，這會根據 ORM model 建立所有尚未存在的表格（包含新增的 `expense_images`），但**不更新 `alembic_version` 表**。之後執行 `alembic upgrade head` 時，Alembic 認為 migration 尚未跑，再次嘗試 `CREATE TABLE expense_images` → 衝突報錯。

注意：`create_all` 對**已存在的表格**不會新增欄位，所以 `user_states.pending_images` 仍然缺失（migration `l` 的工作）。這造成一個矛盾狀態：部分表格靠 `create_all` 建立，部分欄位靠 migration 新增，兩者版本記錄不一致。

**解決方案**：
```python
# 將 migration 中的 DDL 全部改為冪等寫法
def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("CREATE TABLE IF NOT EXISTS expense_images (...)"))
    conn.execute(text("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS user_description TEXT"))
    conn.execute(text("ALTER TABLE user_states ADD COLUMN IF NOT EXISTS pending_images TEXT NOT NULL DEFAULT '[]'"))
```

**根本預防措施**：
- **開發環境**：只選一種 schema 管理方式，不可混用
  - 全用 Alembic → 移除 startup 的 `create_all`
  - 全用 `create_all` → 不跑 Alembic（prototype 階段可行，不建議）
- **新增表格/欄位後**：同時寫 Alembic migration，不依賴 `create_all` 補洞

**狀態**: `resolved` (2026-04-12)

---

### #012 - Pydantic `ExpenseRead` schema 缺少新欄位，API 靜默不回傳

**問題描述**：
前端「憑證類別」欄位永遠顯示 `-`，即使後端 DB 已有 `voucher_categories` 資料。

**根因分析**：
FastAPI 使用 Pydantic schema（`ExpenseRead`）序列化 API response。ORM model `Expense` 新增了 `voucher_categories`、`user_description`、`image_count` 三個欄位，但 `ExpenseRead` 忘記同步更新。FastAPI 序列化時只輸出 schema 定義的欄位，多餘的 ORM 屬性完全不出現在 JSON response 中，不報任何錯誤（靜默失敗）。

前端 `mapExpense()` 收到 `item.voucher_categories === undefined`，解析後為 `null`，表格顯示 `-`。

**解決方案**：
```python
# schemas/expense.py — ExpenseRead 補上三個欄位
class ExpenseRead(BaseModel):
    ...
    user_description: str | None = None
    image_count: int = 1
    voucher_categories: str | None = None  # JSON 陣列字串
```

**新欄位完整 Checklist（缺任一步驟都會靜默失敗）**：
1. ✅ ORM Model（`models/expense.py`）
2. ✅ Alembic Migration（`alembic/versions/`）
3. ✅ Pydantic Schema（`schemas/expense.py`）← **本次遺漏點**
4. ✅ 前端 store `mapExpense()`（`expenseStore.js`）
5. ✅ 前端元件顯示（`ExpenseTable.vue` / `AuditModal.vue`）

**狀態**: `resolved` (2026-04-12)

---

### #013 - asyncio.create_task() Timer 僅支援單 Worker，多 Worker 環境下 Timer 失效

**問題描述**：
Sprint 3 自動切割功能使用 `asyncio.create_task()` + 模組級 `_timers: dict` 實作每用戶的 60 秒滑動視窗 Timer。此方案在 **單 Worker** 模式下運作正常，但多 Worker 時每個 Worker 各自持有獨立的 `_timers` dict，同一用戶的請求可能分散到不同 Worker，導致 Timer 無法正確取消，產生重複送出。

**根因分析**：
`asyncio.create_task()` 綁定至 Worker 進程的 event loop，進程間無法共享記憶體物件。

**限制條件**：
- `ENABLE_AUTO_SPLIT=true` 時，**必須以單 Worker 啟動**：`uvicorn main:app --workers 1`
- 多 Worker 需求時需改用 Redis TTL + Celery Beat 等外部 Queue（Sprint 3 不實作，待日後評估）

**預防措施**：
1. `.env.example` 加入明確警告注釋
2. `services/auto_split_timer.py` 模組頂層 docstring 加入 ⚠️ WARNING
3. 部署 SOP 中明確記錄此限制

**狀態**: `monitoring` (2026-04-13) — 目前僅在單 Worker 環境使用，多 Worker 場景需額外評估

---

## 統計資料

| 分類 | Open | Resolved | Monitoring | Won't Fix | 總計 |
|------|------|----------|------------|-----------|------|
| config | 0 | 1 | 0 | 0 | 1 |
| database | 0 | 4 | 0 | 0 | 4 |
| api | 0 | 2 | 0 | 0 | 2 |
| async | 0 | 2 | 1 | 0 | 3 |
| integration | 0 | 1 | 0 | 0 | 1 |
| dependency | 0 | 2 | 0 | 0 | 2 |
| **總計** | **0** | **12** | **1** | **0** | **13** |

**解決率**: 92% (12/13)

---

**維護規則**:
- 每週五 Review 所有 `monitoring` 狀態的問題
- 每月初更新統計資料與常見問題 FAQ
- 重大問題立即同步至 `company-rules.md` 或 `team-workflow.md`

**維護者**: 全體開發 Agent
**最後審查**: 2026-04-13
