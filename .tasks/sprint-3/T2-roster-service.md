# Roster Service（roster_service.py）

| 欄位 | 值 |
|------|-----|
| ID | T2 |
| 專案 | AcctAssist |
| Sprint | Sprint 3 |
| 指派給 | backend-architect |
| 優先級 | P0 |
| 狀態 | done |
| 依賴 | T1 |
| 預估 | 2h |
| 建立時間 | 2026-04-29T04:03:03.613Z |

---

## 任務描述

新增 `services/roster_service.py`，封裝所有員工名冊的業務邏輯與 DB 操作。

### 需實作的函式

```python
# 1. 查詢名冊
def get_all_roster(db, is_bound: bool | None = None, page: int = 0, size: int = 20) -> tuple[list[StaffRoster], int]

# 2. 查詢單筆
def get_roster_by_id(db, roster_id: UUID) -> StaffRoster | None
def get_roster_by_employee_id(db, employee_id: str) -> StaffRoster | None
def get_roster_by_line_user_id(db, line_user_id: str) -> StaffRoster | None

# 3. 新增單筆
def create_roster_entry(db, name: str, department: str, employee_id: str | None) -> StaffRoster

# 4. 修改
def update_roster_entry(db, roster_id: UUID, **kwargs) -> StaffRoster | None

# 5. 刪除
def delete_roster_entry(db, roster_id: UUID) -> bool

# 6. 核心：綁定 LINE 使用者（Webhook 呼叫）
def bind_line_user(db, employee_id: str, line_user_id: str) -> StaffRoster | None
    """
    查詢 employee_id 對應的名冊 → 
    設定 line_user_id / is_bound=True / bound_at=now() →
    回傳 StaffRoster（成功）或 None（找不到編號）
    """

# 7. 解除綁定（管理員操作）
def unbind_roster_entry(db, roster_id: UUID) -> StaffRoster | None
    """
    清空 line_user_id / is_bound=False / bound_at=None
    """

# 8. CSV 批次匯入
def import_from_csv(db, csv_content: str) -> dict
    """
    解析 CSV（欄位：name, department, employee_id）
    逐筆 upsert（employee_id 相同則更新 name/department，不重置綁定狀態）
    回傳 {"created": N, "updated": N, "errors": [...]}
    """
```

### 重要業務規則

1. **`bind_line_user`**：若 `employee_id` 找不到 → 回傳 `None`（不拋例外，由 Webhook 層決定回覆訊息）
2. **`import_from_csv`**：
   - 必要欄位：`name`, `department`（`employee_id` 可選）
   - `employee_id` 相同時 upsert（更新名字/組別），不重置 `is_bound`
   - 每筆錯誤單獨記錄，不中斷整批匯入
3. **`unbind_roster_entry`**：解除後對應的 `users` 表 `real_name` / `department` **不清除**（保留歷史記錄）

## 驗收標準

- [ ] 所有函式有完整 Type Hints 與 Google style docstring
- [ ] `bind_line_user` 找不到 employee_id 時回傳 `None`（非 exception）
- [ ] `import_from_csv` 支援欄位含空白、大小寫不敏感的 CSV
- [ ] `import_from_csv` 錯誤單筆不中斷整批處理
- [ ] 無 `print` 語句，錯誤用 `logger.error()` 記錄

---

## 事件紀錄

### 2026-04-29T04:03:03.613Z — 建立任務（assigned）
由 L1 透過 /task-delegation 建立
