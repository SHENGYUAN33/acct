# main.py 掛載 roster 路由

| 欄位 | 值 |
|------|-----|
| ID | T6 |
| 專案 | AcctAssist |
| Sprint | Sprint 3 |
| 指派給 | backend-architect |
| 優先級 | P1 |
| 狀態 | done |
| 依賴 | T3 |
| 預估 | 0.5h |
| 建立時間 | 2026-04-29T04:03:03.613Z |

---

## 任務描述

在 `main.py` 中掛載 roster router，並確認新 Model 可被 SQLAlchemy 載入。

### 修改 `main.py`

1. **新增 import**：
```python
from routers.roster import router as roster_router
```

2. **掛載路由**（在現有 router 掛載的附近新增）：
```python
app.include_router(roster_router, prefix="/api/v1")
```

3. **確認 Model 可被載入**：
在 `main.py` 的 model import 區塊確認 `models.staff_roster` 被載入（讓 `Base.metadata.create_all()` 能建表）：
```python
from models import staff_roster  # 若尚未自動載入，手動加入
```

### 注意

- 不修改現有任何路由的 prefix 或順序
- 不修改 CORS 設定
- 確認 `/docs` 可看到新的 `/api/v1/roster` 端點群組

## 驗收標準

- [ ] 啟動 uvicorn 後無 import error
- [ ] 訪問 `/docs` 可看到 `roster` tag 下的所有端點
- [ ] `GET /api/v1/roster` 回傳 401（JWT 未提供），代表路由正確掛載

---

## 事件紀錄

### 2026-04-29T04:03:03.613Z — 建立任務（assigned）
由 L1 透過 /task-delegation 建立
