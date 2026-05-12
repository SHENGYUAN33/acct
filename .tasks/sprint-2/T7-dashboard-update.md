# Dashboard 更新（前端）

| 欄位 | 值 |
|------|-----|
| ID | T7 |
| 專案 | AcctAssist |
| Sprint | Sprint 2 |
| 指派給 | frontend-dev |
| 優先級 | P1 |
| 狀態 | done |
| 依賴 | T6 |
| 預估 | 3h |
| 建立時間 | 2026-04-11T00:00:00.000Z |

---

## 任務描述

⚠️ **前置條件**：T6 完成（後端 API 已確定返回 `voucher_categories`、`user_description`、`image_count`）

### `frontend/src/stores/expenseStore.js` — 更新 `mapExpense()`

```javascript
const CATEGORY_LABEL = {
  INVOICE: '發票',
  RECEIPT: '收據',
  LABOR_SERVICE: '勞報',
  TRANSPORTATION: '交通',
  CREDIT_NOTE: '退貨折讓',
}

// 在 mapExpense() 中新增：
voucher_categories: item.voucher_categories ?? null,
certificate_type: item.voucher_categories?.[0]
  ? (CATEGORY_LABEL[item.voucher_categories[0]] ?? item.voucher_categories[0])
  : (item.certificate_type ?? null),
user_description: item.user_description ?? null,
image_count: item.image_count ?? 1,
```

### `frontend/src/api/expenseApi.js` — 新增方法

```javascript
// 新增：取得某筆報帳的子圖片清單
fetchExpenseImages(expenseId) {
  return axiosInstance.get(`/api/v1/expenses/${expenseId}/images`)
}
```

> ⚠️ 禁止在元件中直接呼叫 axios，一律透過 `expenseApi.js`

### `frontend/src/components/AuditModal.vue` — 更新

1. **`certificate_type` 輸入框**：改為唯讀顯示（`readonly` + 移除 `v-model` 雙向綁定）
   - 顯示 `voucher_categories` 中文名稱列表（逗號分隔）
2. **新增子圖片清單區塊**：
   - 呼叫 `fetchExpenseImages(expense.id)` 取得清單
   - 每項顯示：縮圖（`image_url`） + `voucher_category` 標籤 + OCR 金額摘要
3. **新增 `user_description` 顯示欄位**（唯讀）

### 規範遵守

- Vue 3 Composition API + `<script setup>`（禁止 Options API）
- Tailwind CSS 排版
- API 呼叫一律透過封裝的 `expenseApi.js`

## 驗收標準

- [ ] `ExpenseTable` 中 `certificate_type` 欄位正確顯示中文類別名稱（如「發票」、「交通」）
- [ ] `AuditModal` 詳情頁 `certificate_type` 改為唯讀，顯示 `voucher_categories` 中文列表
- [ ] `AuditModal` 詳情頁顯示所有子圖片清單（含類型標籤與 OCR 金額摘要）
- [ ] `user_description` 欄位正確顯示（為 null 時不顯示或顯示「無備註」）
- [ ] `image_count` 可在詳情頁看到（如「共 3 張照片」）
- [ ] 使用 `<script setup>` Composition API
- [ ] 無直接 axios 呼叫（全透過 expenseApi.js）

---

## 事件紀錄

### 2026-04-11T00:00:00.000Z — 建立任務（assigned）
由 L1（project-lead）透過 /task-delegation 建立
⚠️ 等待 T6 完成（API schema 確定）後解鎖

### 2026-04-10T18:36:39.000Z — 開始執行（in_progress）
T6 已完成（API schema 確定），由 L1（project-lead）委派給 frontend-dev 啟動

### 2026-04-10T18:36:39.000Z — 完成交付（in_review）
mapExpense 四個新欄位、fetchExpenseImages、AuditModal 唯讀 + 子圖片清單 + user_description

### 2026-04-10T18:36:39.000Z — L1 審核通過（done）
審核者：project-lead。Composition API 正確、apiClient 封裝正確、OCR 金額安全解析、spinner 狀態正確。待辦：BACKEND_BASE_URL 硬寫需改環境變數（Backlog，非本 Sprint 範疇）。
完成以下三項交付：
1. `expenseStore.js` mapExpense() 新增 voucher_categories / certificate_type（中文化）/ user_description / image_count 四個欄位
2. `expenseApi.js` 新增 fetchExpenseImages(expenseId) → GET /api/v1/expenses/{id}/images
3. `AuditModal.vue` 更新：certificate_type 改為唯讀並顯示 voucher_categories 中文列表；新增子圖片清單區塊（含縮圖、類型標籤、OCR 金額摘要、載入 spinner）；新增 user_description 唯讀顯示欄位
