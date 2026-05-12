# 前端名冊管理頁面（RosterView.vue）

| 欄位 | 值 |
|------|-----|
| ID | T8 |
| 專案 | AcctAssist |
| Sprint | Sprint 3 |
| 指派給 | frontend-developer |
| 優先級 | P1 |
| 狀態 | done |
| 依賴 | T7 |
| 預估 | 3h |
| 建立時間 | 2026-04-29T04:03:03.613Z |

---

## 任務描述

新增 `frontend/src/views/RosterView.vue`，提供管理員管理員工名冊的完整頁面。

**強制使用 Vue 3 Composition API + `<script setup>` + Tailwind CSS。禁止 Options API。**

### 頁面功能規格

#### 1. 頁面頂部工具列

```
[+ 新增員工] [📥 匯入 CSV] [📄 下載樣板]          搜尋框    [綁定狀態篩選▼]
```

#### 2. 員工名冊表格

| 欄位 | 說明 |
|------|------|
| 姓名 | `name` |
| 組別 | `department` |
| 員工編號 | `employee_id`（無則顯示「—」） |
| 綁定狀態 | 綠色「✅ 已綁定」/ 灰色「⏳ 未綁定」badge |
| 綁定時間 | `bound_at` 格式化（未綁定顯示「—」） |
| 操作 | [編輯] [解除綁定]（已綁定才顯示）[刪除] |

- 支援分頁（page / size）
- 支援依「綁定狀態」篩選（全部 / 已綁定 / 未綁定）

#### 3. 新增/編輯 Modal

```
員工姓名 *    [____________]
所屬組別 *    [____________] （可用下拉選單，選項同現有 DEPARTMENTS）
員工編號      [____________] （選填，提示：作為 LINE 使用者的識別碼）

[取消]  [儲存]
```

#### 4. CSV 匯入流程

1. 點「匯入 CSV」→ 開啟檔案選擇器（限 `.csv`）
2. 選擇後自動上傳
3. 顯示匯入結果 Toast：
   - 成功：「✅ 匯入完成：新增 N 筆，更新 M 筆」
   - 部分失敗：「⚠️ 匯入完成，但有 K 筆錯誤，請檢查格式」
   - 完全失敗：「❌ 匯入失敗，請確認 CSV 格式正確」

#### 5. 刪除確認

- 刪除時顯示確認 Dialog：「確定刪除 {name}？此操作不可復原。」
- 若員工已綁定，顯示警告：「此員工已與 LINE 帳號綁定，請先解除綁定後再刪除。」（實際阻擋由後端）

#### 6. 解除綁定確認

- 確認 Dialog：「確定解除 {name} 的 LINE 綁定嗎？對方下次互動時需重新輸入員工編號。」

#### 7. CSV 樣板格式（前端本地產生）

```
name,department,employee_id
王小明,製片組,EMP001
李大華,攝影組,EMP002
（請依此格式填寫，employee_id 可留空）
```

### 路由設定

在現有 `router/index.js`（或類似路由配置）新增：
```javascript
{
  path: '/roster',
  name: 'roster',
  component: () => import('@/views/RosterView.vue'),
  meta: { requiresAuth: true }
}
```

並在側邊欄/導覽列新增「員工名冊」入口連結。

### UI 風格要求

- 與現有 Dashboard 頁面（`ExpenseListView.vue`）風格一致
- 使用 Tailwind CSS，不新增自定義 CSS 類別
- 綁定狀態 badge：
  - 已綁定：`bg-green-100 text-green-800`
  - 未綁定：`bg-gray-100 text-gray-600`
- Loading state：表格載入中顯示 skeleton 或 spinner
- 空狀態：名冊為空時顯示提示「尚未匯入員工名冊，請點擊「匯入 CSV」開始」

## 驗收標準

- [ ] 使用 Vue 3 `<script setup>` Composition API，無 Options API
- [ ] 表格正確顯示名冊資料，支援分頁
- [ ] 綁定狀態 badge 顯示正確（顏色、文字）
- [ ] 篩選「已綁定/未綁定/全部」正確過濾
- [ ] 新增/編輯 Modal 可正常開啟、儲存、關閉
- [ ] CSV 匯入成功後表格自動刷新，並顯示結果 Toast
- [ ] 下載樣板按鈕可下載正確格式的 CSV
- [ ] 刪除與解除綁定有確認 Dialog
- [ ] 路由設定完成，可從側邊欄進入頁面
- [ ] 風格與現有 Dashboard 一致（Tailwind CSS）

---

## 事件紀錄

### 2026-04-29T04:03:03.613Z — 建立任務（assigned）
由 L1 透過 /task-delegation 建立
