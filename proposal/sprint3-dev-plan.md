# 開發計畫書: Sprint 3 — 員工名冊預綁定系統

> **撰寫者**: tech-lead (L1)
> **日期**: 2026-04-29
> **專案**: AcctAssist（LINE Bot 智能報帳系統）
> **狀態**: 🔄 進行中

---

## 1. 需求摘要

### 背景

劇組人員名單在開拍前已確定，現有「首次使用需手動輸入姓名 + 選擇組別」的 Onboarding 流程對劇組成員造成不必要的摩擦。

需求方向：
1. **管理員預先匯入名冊**（姓名、組別、員工編號）
2. **使用者首次使用只輸入一次員工編號**，系統自動完成綁定
3. **之後永遠不需要輸入任何資料**，直接進入報帳流程

### 解決方案

建立「員工名冊（Staff Roster）預綁定系統」：

- 管理員在 Dashboard 管理名冊（CSV 批次匯入 / 手動新增）
- 新 `staff_roster` DB 表儲存名冊資料
- 使用者第一次互動輸入員工編號 → 系統查名冊 → 自動填入姓名+組別 + 記錄 LINE ID
- 後續互動直接識別，零操作進入報帳

### 新舊流程對比

| | 舊流程 | 新流程 |
|--|--------|--------|
| 第一次 | 輸入姓名 → 選組別 | 輸入員工編號（一次） |
| 之後每次 | 直接報帳 | 直接報帳 |
| 管理員準備 | 無 | 匯入名冊 CSV |

---

## 2. 技術方案

### 2.1 架構決策

**選定方案：`staff_roster` 獨立表 + 單次員工編號綁定**

| 面向 | 說明 |
|------|------|
| 新增 DB 表 | `staff_roster`（不修改現有 `users` 表結構） |
| 綁定觸發 | 使用者輸入員工編號（`BINDING_EMPLOYEE_ID` step） |
| LINE ID 自動記錄 | 綁定成功時自動存入 roster 的 `line_user_id` |
| 功能開關 | `ENABLE_ROSTER_BINDING`（預設 False，不影響現有用戶） |
| 向後相容 | 已綁定舊用戶（有 real_name + department）直接跳過 Onboarding |

### 2.2 資料流

```
【管理員端】
CSV 上傳 → POST /api/v1/roster/import → 批次建立 StaffRoster 記錄

【使用者端 — 首次】
發任何訊息
    ↓
get_or_create_user(db, line_user_id)
    ↓
[ENABLE_ROSTER_BINDING=True]
    ├─ 已有 real_name + department → 直接進入報帳（舊用戶相容）
    ├─ state.step == BINDING_EMPLOYEE_ID + 輸入文字
    │   → 查 StaffRoster by employee_id
    │     Found  → 寫入 User.real_name / department
    │              寫入 Roster.line_user_id / is_bound=True
    │              → 回覆「✅ 歡迎，{name}！」
    │     Not Found → 回覆「找不到此編號，請確認後重試」
    └─ 其他（第一次） → set_state(BINDING_EMPLOYEE_ID) → 回覆「請輸入員工編號」

【使用者端 — 之後】
發任何訊息 → 已有 real_name + department → 直接進入報帳流程
```

---

## 3. 檔案變更清單

### 新增

| 檔案 | 說明 |
|------|------|
| `models/staff_roster.py` | StaffRoster ORM Model |
| `alembic/versions/r5s6t7u8v9w0_create_staff_roster.py` | DB Migration |
| `services/roster_service.py` | 名冊 CRUD + 綁定邏輯 |
| `routers/roster.py` | 名冊管理 API |
| `frontend/src/api/rosterApi.js` | 前端 API 封裝 |
| `frontend/src/views/RosterView.vue` | 名冊管理頁面 |

### 修改

| 檔案 | 修改範圍 | 侵入程度 |
|------|---------|---------|
| `core/config.py` | 新增 `enable_roster_binding` 旗標 | 極低（新增一行） |
| `routers/webhook.py` | Onboarding 區塊（Line 217–246）改寫，`ENABLE_ROSTER_BINDING=False` 時行為完全不變 | 低 |
| `main.py` | 掛載 roster router | 極低（新增兩行） |
| `.env.example` | 新增 `ENABLE_ROSTER_BINDING` 範例 | 極低 |

---

## 4. API 端點清單

| Method | Path | 說明 | 認證 |
|--------|------|------|------|
| `GET` | `/api/v1/roster` | 查詢名冊（支援 `is_bound` 過濾、分頁） | JWT |
| `POST` | `/api/v1/roster` | 新增單筆員工 | JWT |
| `PATCH` | `/api/v1/roster/{id}` | 修改員工資料 | JWT |
| `DELETE` | `/api/v1/roster/{id}` | 刪除員工 | JWT |
| `POST` | `/api/v1/roster/import` | CSV 批次匯入 | JWT |
| `POST` | `/api/v1/roster/{id}/unbind` | 解除 LINE 綁定 | JWT |

---

## 5. 驗收標準

- [ ] 管理員可透過 Dashboard 上傳 CSV 匯入員工名冊
- [ ] 管理員可手動新增/修改/刪除員工
- [ ] 管理員可解除員工的 LINE 綁定（例如人員離職）
- [ ] 使用者首次使用輸入正確員工編號後，系統自動填入姓名與組別
- [ ] 輸入錯誤員工編號時，系統回覆明確錯誤訊息並允許重試
- [ ] 已綁定使用者再次互動時，直接進入報帳流程（不再詢問）
- [ ] `ENABLE_ROSTER_BINDING=False` 時，現有流程完全不受影響
- [ ] Dashboard 名冊頁顯示綁定狀態（已綁定/未綁定）與綁定時間

---

## 6. 任務分解

| 任務 | 說明 | 負責 | 依賴 | 預估 |
|------|------|------|------|------|
| T1 | DB Model + Migration（staff_roster 表） | backend-architect | — | 1.5h |
| T2 | Roster Service（roster_service.py） | backend-architect | T1 | 2h |
| T3 | Roster Router（routers/roster.py） | backend-architect | T2 | 2h |
| T4 | Config 旗標（enable_roster_binding） + .env.example | backend-architect | — | 0.5h |
| T5 | Webhook Onboarding 改寫 | backend-architect | T1,T2,T4 | 2h |
| T6 | main.py 掛載 roster 路由 | backend-architect | T3 | 0.5h |
| T7 | 前端 API 封裝（rosterApi.js） | frontend-developer | T3 | 1h |
| T8 | 前端名冊管理頁面（RosterView.vue） | frontend-developer | T7 | 3h |

**總預估工時**：12.5h

---

## 7. 任務依賴圖

```
T4 (Config)
    │
    ▼
T1 (DB Model) ──────────────────┐
    │                           │
    ▼                           │
T2 (Service) ──────────────────►T5 (Webhook 改寫)
    │
    ▼
T3 (Router)
    │
    ├──► T6 (main.py 掛載)
    │
    └──► T7 (前端 API) ──► T8 (前端頁面)
```

---

## 8. 風險與緩解

| 風險 | 機率 | 影響 | 緩解方式 |
|------|------|------|---------|
| 員工重複輸入錯誤編號 | 中 | 低 | 允許無限重試，不鎖定 |
| CSV 格式不正確 | 中 | 低 | 匯入前驗證 + 明確錯誤回報 |
| 同一員工被多次綁定 | 低 | 中 | `employee_id` unique 約束 + is_bound 檢查 |
| 現有用戶受影響 | 極低 | 高 | Feature flag 預設關閉，已有 real_name 的用戶直接跳過 |

---

## 9. 設定說明

```env
# .env 新增設定
ENABLE_ROSTER_BINDING=true  # 開啟預綁定模式（預設 false）
```

CSV 匯入格式：
```csv
name,department,employee_id
王小明,製片組,EMP001
李大華,攝影組,EMP002
陳美玲,美術組,EMP003
```

---

## 10. Gate 審查紀錄

_（待填寫）_
