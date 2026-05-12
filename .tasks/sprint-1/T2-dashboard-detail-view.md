# Dashboard 詳情頁

| 欄位 | 值 |
|------|-----|
| ID | T2 |
| 專案 | AcctAssist |
| Sprint | Sprint 1 |
| 指派給 | frontend-dev |
| 優先級 | P0 |
| 狀態 | assigned |
| 依賴 | — |
| 預估 | 2d |
| 建立時間 | 2026-04-10T03:09:26.113Z |

---

## 任務描述

新增 `ExpenseDetailView.vue`，更新 router 加入 `/expenses/:id`，在 `ExpenseTable` 顯示 `serial_number` 欄位，驗證核可/退件/補件 E2E 流程。

**新增檔案**：
- `frontend/src/views/ExpenseDetailView.vue`（發票詳情 + OCR 資料 + 審核操作）

**修改檔案**：
- `frontend/src/router/index.js`：新增 `/expenses/:id` 路由
- `frontend/src/components/ExpenseTable.vue`：新增 `serial_number` 欄位

**規範參考**：
- `.knowledge/specs/api-design.md`（API 格式）
- `.knowledge/specs/feature-spec.md`（功能規格 F2）

⚠️ **禁止修改** `expenseStore.js` 的 API 呼叫邏輯（後端 API 契約不可動）

## 驗收標準

- [ ] `/expenses/:id` 路由可正常訪問
- [ ] `ExpenseDetailView.vue` 顯示完整 OCR 資料（金額、發票號碼、賣方等）
- [ ] `ExpenseDetailView.vue` 顯示發票圖片
- [ ] `ExpenseTable` 正確顯示 `serial_number` 欄位
- [ ] 核可操作可正確更新狀態為 APPROVED
- [ ] 退件操作可正確填入原因並更新狀態為 REJECTED
- [ ] 使用 Vue 3 Composition API + `<script setup>` 語法
- [ ] 樣式沿用 Tailwind CSS，與 `ExpenseListView` 風格一致

---

## 事件紀錄

### 2026-04-10T03:09:26.113Z — 建立任務（assigned）
由 L1 透過 /task-delegation 建立
