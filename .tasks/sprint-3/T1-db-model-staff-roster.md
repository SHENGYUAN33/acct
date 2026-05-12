# DB Model + Migration（staff_roster 表）

| 欄位 | 值 |
|------|-----|
| ID | T1 |
| 專案 | AcctAssist |
| Sprint | Sprint 3 |
| 指派給 | backend-architect |
| 優先級 | P0 |
| 狀態 | done |
| 依賴 | — |
| 預估 | 1.5h |
| 建立時間 | 2026-04-29T04:03:03.613Z |

---

## 任務描述

新增 `staff_roster` ORM Model 與對應的 Alembic Migration。

### 新增檔案：`models/staff_roster.py`

```python
"""員工名冊 ORM Model。"""
import uuid
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from core.database import Base

class StaffRoster(Base):
    __tablename__ = "staff_roster"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)           # 真實姓名
    department = Column(String(100), nullable=False)      # 所屬組別
    employee_id = Column(String(50), unique=True, nullable=True)   # 員工編號（使用者輸入匹配用）
    line_user_id = Column(String(100), unique=True, nullable=True) # LINE ID（綁定後自動填入）
    is_bound = Column(Boolean, default=False, nullable=False)      # 是否已完成綁定
    bound_at = Column(DateTime, nullable=True)            # 綁定時間
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
```

### 新增 Migration

- 檔名格式：`alembic/versions/r5s6t7u8v9w0_create_staff_roster.py`
- 建立 `staff_roster` 表，欄位同上
- `employee_id` 建立 unique index
- `line_user_id` 建立 unique index

### 注意事項

- 不修改任何現有 Model（users, expenses, user_states 等）
- Migration 的 `down_revision` 接在最新的現有 migration 之後
- 確認 `models/__init__.py`（若存在）或 `main.py` 中 `Base.metadata.create_all()` 能載入新 Model

## 驗收標準

- [ ] `models/staff_roster.py` 建立完成，可正確 import
- [ ] `alembic upgrade head` 執行成功，`staff_roster` 表存在於 DB
- [ ] `alembic downgrade -1` 執行成功（可回滾）
- [ ] `employee_id` 與 `line_user_id` unique constraint 已建立
- [ ] 現有所有 migration 仍可正常執行，無衝突

---

## 事件紀錄

### 2026-04-29T04:03:03.613Z — 建立任務（assigned）
由 L1 透過 /task-delegation 建立

### 2026-04-29T04:10:00.000Z — 開始執行（in_progress）
backend-architect 開始執行：建立 models/staff_roster.py 與 alembic migration

### 2026-04-29T04:11:17.269Z — L1 Code Review 通過（done）
審查結果：
- ✅ models/staff_roster.py 欄位完整、型別正確
- ✅ migration down_revision 正確接在 q4r5s6t7u8v9 之後
- ✅ employee_id / line_user_id unique index 均已建立
- ✅ downgrade() 完整實作（可回滾）
- ✅ StaffRoster 已加入 models/__init__.py
