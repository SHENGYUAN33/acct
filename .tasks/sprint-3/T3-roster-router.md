# Roster Router（routers/roster.py）

| 欄位 | 值 |
|------|-----|
| ID | T3 |
| 專案 | AcctAssist |
| Sprint | Sprint 3 |
| 指派給 | backend-architect |
| 優先級 | P0 |
| 狀態 | done |
| 依賴 | T2 |
| 預估 | 2h |
| 建立時間 | 2026-04-29T04:03:03.613Z |

---

## 任務描述

新增 `routers/roster.py`，提供員工名冊管理的 REST API。所有端點需要 JWT 認證。

### 端點清單

```
GET    /api/v1/roster              查詢名冊清單（分頁 + is_bound 過濾）
POST   /api/v1/roster              新增單筆員工
PATCH  /api/v1/roster/{id}         修改員工資料
DELETE /api/v1/roster/{id}         刪除員工
POST   /api/v1/roster/import       CSV 批次匯入
POST   /api/v1/roster/{id}/unbind  解除 LINE 綁定
```

### 回應格式（統一遵守 api-standards）

```json
// GET /api/v1/roster
{
  "status": "success",
  "data": {
    "content": [
      {
        "id": "uuid",
        "name": "王小明",
        "department": "製片組",
        "employee_id": "EMP001",
        "line_user_id": "Uxxxxxxxxxx",
        "is_bound": true,
        "bound_at": "2026-04-29T10:00:00+08:00",
        "created_at": "2026-04-29T08:00:00+08:00"
      }
    ],
    "page": 0,
    "size": 20,
    "total_elements": 50,
    "total_pages": 3
  },
  "message": "查詢成功"
}

// POST /api/v1/roster/import 回應
{
  "status": "success",
  "data": {
    "created": 10,
    "updated": 2,
    "errors": [
      {"row": 5, "reason": "缺少必要欄位 name"}
    ]
  },
  "message": "匯入完成"
}
```

### Pydantic Schemas（需同步新增至 schemas/roster.py）

```python
class RosterCreate(BaseModel):
    name: str
    department: str
    employee_id: str | None = None

class RosterUpdate(BaseModel):
    name: str | None = None
    department: str | None = None
    employee_id: str | None = None

class RosterRead(BaseModel):
    id: UUID
    name: str
    department: str
    employee_id: str | None
    line_user_id: str | None
    is_bound: bool
    bound_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True
```

### CSV 匯入端點（`POST /api/v1/roster/import`）

- 接受 `multipart/form-data`，檔案欄位名 `file`
- 支援 `.csv` 格式，UTF-8 或 UTF-8 with BOM
- 必要欄位：`name`, `department`
- 可選欄位：`employee_id`
- 回傳 created / updated / errors 統計

### 注意

- `POST /api/v1/roster/import` 路由必須在 `POST /api/v1/roster/{id}/unbind` 之前定義，避免路由衝突
- 刪除員工時，若已綁定（`is_bound=True`），回傳 400 並提示「請先解除綁定再刪除」
- 認證方式：`Authorization: Bearer <token>`，使用現有 `core/security.py` 的 `decode_access_token`

## 驗收標準

- [ ] 所有端點可透過 Swagger UI（`/docs`）測試
- [ ] JWT 未提供時所有端點回傳 401
- [ ] `GET /api/v1/roster?is_bound=false` 正確過濾未綁定員工
- [ ] `POST /api/v1/roster/import` 可上傳 CSV 並回傳統計結果
- [ ] 刪除已綁定員工時回傳 400
- [ ] 回應格式符合 api-standards（`status/data/message`）
- [ ] 新增 `schemas/roster.py`，Pydantic model 完整

---

## 事件紀錄

### 2026-04-29T04:03:03.613Z — 建立任務（assigned）
由 L1 透過 /task-delegation 建立
