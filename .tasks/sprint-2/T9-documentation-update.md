# 文件更新（Sprint 2）

| 欄位 | 值 |
|------|-----|
| ID | T9 |
| 專案 | AcctAssist |
| Sprint | Sprint 2 |
| 指派給 | tech-writer |
| 優先級 | P1 |
| 狀態 | done |
| 依賴 | T8（G3 通過後） |
| 預估 | 2h |
| 建立時間 | 2026-04-11T00:00:00.000Z |

---

## 任務描述

⚠️ **前置條件**：T8 通過 G3 測試驗收

### `.knowledge/specs/api-design.md` — 更新

1. **新增端點**：`GET /api/v1/expenses/{id}/images`
   - 說明、請求格式、回應格式（完整 JSON 範例）
   - 認證方式（JWT）
   - 錯誤情境（404）

2. **更新 `ExpenseRead` schema 欄位表格**，新增以下三欄：

   | 欄位 | 類型 | 說明 |
   |------|------|------|
   | `user_description` | `str \| null` | 使用者附加備註 |
   | `image_count` | `int` | 本筆報帳包含的照片數量（預設 1） |
   | `voucher_categories` | `list[str] \| null` | 憑證類別清單（JSON array） |

### `.knowledge/project-overview.md` — 更新

1. **「資料庫結構」章節**：
   - 新增 `expense_images` 表欄位說明
   - 更新 `expenses` 表（新增 3 欄位）
   - 更新 `user_states` 表（新增 2 欄位）

2. **「LINE Bot 報帳流程」章節**：
   - 更新流程圖為批次收集流程（含 Onboarding 分支、COLLECTING 模式、Postback 觸發）
   - 移除舊的「我要報帳」觸發描述

### `postmortem-log.md` — 解除地雷

- 執行 `/pitfall-resolve` 將 `postmortem #003` 更新為 `resolved`
  - #003 內容：Webhook < 500ms 限制（已在 Sprint 2 透過 BackgroundTask 架構解決）

## 驗收標準

- [ ] `api-design.md` 含新端點 `GET /api/v1/expenses/{id}/images` 完整說明
- [ ] `api-design.md` `ExpenseRead` schema 欄位表格已更新（含 3 個新欄位）
- [ ] `project-overview.md` 「資料庫結構」章節反映 Sprint 2 新增表格與欄位
- [ ] `project-overview.md` 流程圖更新為批次報帳流程
- [ ] `postmortem #003` 狀態更新為 `resolved`

---

## 事件紀錄

### 2026-04-11T00:00:00.000Z — 建立任務（assigned）
由 L1（project-lead）透過 /task-delegation 建立
⚠️ 等待 T8 通過 G3 後解鎖（G3 阻斷）

### 2026-04-11T00:00:00.000Z — 開始執行（in_progress）
G3 通過（T8 pytest 24/24 全綠），由 L1（project-lead）委派給 tech-writer 啟動

### 2026-04-11T00:00:00.000Z — 完成交付 + L1 審核通過（done）
審核者：project-lead。驗收清單全數通過：
- api-design.md 含新端點完整說明 ✅
- api-design.md ExpenseRead 3 個新欄位 ✅
- project-overview.md DB 結構反映 Sprint 2 ✅
- project-overview.md 流程圖更新為批次報帳流程 ✅
- postmortem #003 更新為 resolved ✅
- 新增 #006-#009 踩坑紀錄 ✅

文件更新完成：
- `api-design.md` v1.1：新增 `GET /api/v1/expenses/{id}/images` 完整說明（含 ExpenseImage 回應欄位表）；ExpenseRead schema 新增 `user_description`/`image_count`/`voucher_categories` 三欄
- `project-overview.md` v1.2：批次報帳流程圖（含 Onboarding 分支、COLLECTING、BackgroundTask）；DB 結構新增 `expense_images` 表說明 + `expenses`/`user_states` 新欄位；4.1 功能清單更新為批次報帳版；Dashboard API 端點清單更新
- `postmortem-log.md` v1.1：#003 狀態從 `monitoring` 更新為 `resolved`（Sprint 2 BackgroundTask 解決方案確認有效）；新增 #006-#009（T8 測試套件發現的 4 個踩坑）；解決率從 80% 提升至 100%
