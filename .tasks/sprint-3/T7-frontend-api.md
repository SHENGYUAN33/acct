# 前端 API 封裝（rosterApi.js）

| 欄位 | 值 |
|------|-----|
| ID | T7 |
| 專案 | AcctAssist |
| Sprint | Sprint 3 |
| 指派給 | frontend-developer |
| 優先級 | P1 |
| 狀態 | done |
| 依賴 | T3 |
| 預估 | 1h |
| 建立時間 | 2026-04-29T04:03:03.613Z |

---

## 任務描述

新增 `frontend/src/api/rosterApi.js`，封裝所有名冊管理的 API 呼叫。

### 參考現有 API 封裝方式

先閱讀 `frontend/src/api/expenseApi.js` 了解現有封裝風格，保持一致。

### 需實作的函式

```javascript
// 查詢名冊清單（支援分頁與綁定狀態過濾）
export const getRosterList = (params = {}) => { ... }
// params: { page, size, is_bound }

// 新增單筆員工
export const createRosterEntry = (data) => { ... }
// data: { name, department, employee_id }

// 修改員工資料
export const updateRosterEntry = (id, data) => { ... }

// 刪除員工
export const deleteRosterEntry = (id) => { ... }

// CSV 批次匯入（FormData）
export const importRosterCSV = (file) => { ... }
// 注意：使用 multipart/form-data，Content-Type 讓 axios 自動設定

// 下載 CSV 樣板
export const downloadRosterTemplate = () => { ... }
// 前端本地產生 CSV 樣板，不需後端 API

// 解除 LINE 綁定
export const unbindRosterEntry = (id) => { ... }
```

### 注意事項

- 所有呼叫透過現有 Axios 實例（帶 JWT Authorization header）
- 禁止直接使用 `axios.get()` / `fetch()`
- `importRosterCSV` 需用 `FormData` 包裝：
  ```javascript
  const formData = new FormData()
  formData.append('file', file)
  return apiClient.post('/roster/import', formData)
  ```

## 驗收標準

- [ ] 所有函式可正確呼叫並回傳 response
- [ ] `importRosterCSV` 使用 FormData，不手動設定 Content-Type header
- [ ] JWT 自動帶入（透過現有 Axios interceptor）
- [ ] 風格與 `expenseApi.js` 一致

---

## 事件紀錄

### 2026-04-29T04:03:03.613Z — 建立任務（assigned）
由 L1 透過 /task-delegation 建立
