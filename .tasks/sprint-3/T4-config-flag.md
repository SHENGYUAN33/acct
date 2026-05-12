# Config 旗標（enable_roster_binding）+ .env.example

| 欄位 | 值 |
|------|-----|
| ID | T4 |
| 專案 | AcctAssist |
| Sprint | Sprint 3 |
| 指派給 | backend-architect |
| 優先級 | P0 |
| 狀態 | done |
| 依賴 | — |
| 預估 | 0.5h |
| 建立時間 | 2026-04-29T04:03:03.613Z |

---

## 任務描述

在 `core/config.py` 新增功能開關，並同步更新 `.env.example`。

### 修改 `core/config.py`

在現有 `enable_auto_split` 附近新增：

```python
# 功能開關：員工名冊預綁定模式
# 啟用後，首次使用的 LINE 使用者需輸入員工編號完成綁定（由管理員預先匯入名冊）
# 關閉時，維持原有 Onboarding 流程（手動輸入姓名 + 選擇組別）
enable_roster_binding: bool = False
```

### 修改 `.env.example`

在對應區塊新增：

```env
# 功能開關：員工名冊預綁定（true=啟用，false=維持舊流程）
ENABLE_ROSTER_BINDING=false
```

### 不得修改

- 現有任何欄位
- `enable_user_binding` 邏輯（仍保留，roster binding 是獨立開關）
- `departments` 等其他設定

## 驗收標準

- [ ] `settings.enable_roster_binding` 可正確讀取（預設 `False`）
- [ ] `.env.example` 有對應說明與範例值
- [ ] `ENABLE_ROSTER_BINDING=true` 在 `.env` 設定後可正確反映
- [ ] 未設定時不影響任何現有功能

---

## 事件紀錄

### 2026-04-29T04:03:03.613Z — 建立任務（assigned）
由 L1 透過 /task-delegation 建立

### 2026-04-29T04:15:00.000Z — L1 Code Review 通過（done）
- ✅ enable_roster_binding: bool = False 加在 enable_user_binding 之後
- ✅ .env.example 第 38-39 行有中文說明與範例值
- ✅ 現有欄位零改動
