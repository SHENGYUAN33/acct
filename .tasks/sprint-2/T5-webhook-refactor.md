# Webhook 重構（批次收集流程）

| 欄位 | 值 |
|------|-----|
| ID | T5 |
| 專案 | AcctAssist |
| Sprint | Sprint 2 |
| 指派給 | backend-dev |
| 優先級 | P0 |
| 狀態 | done |
| 依賴 | T1（G1 通過後）,T3,T4 |
| 預估 | 4h |
| 建立時間 | 2026-04-11T00:00:00.000Z |

---

## 任務描述

⚠️ **前置條件**：T1 通過 G1 + T3 完成 + T4 完成

重構 `routers/webhook.py`，實作批次收集流程與 Onboarding：

### 移除

- ❌ TextMessage 中的「我要報帳」觸發邏輯（啟動 WAITING_PHOTO）
- ❌ 「查看審核結果」Rich Menu Postback 觸發
- ⚠️ **保留**：查詢功能相關邏輯

### 新增 — Onboarding 偵測

- 所有 MessageEvent 進入時：先查詢 `users.department IS NULL`
- 是 → `line_service.reply_with_dept_selection()`（Quick Reply 部門選單）
- 部門選定 Postback → 寫入 `users.department`（永久記錄）

### 新增 — 圖片累積流程（COLLECTING 模式）

- ImageMessage（部門已設定）：
  - `SELECT FOR UPDATE` 取得 `UserState`（防競態條件）
  - `append image_path` 至 `UserState.pending_images`（JSON array）
  - `push` 即時計數回饋：「已收到第 N 張 📸」
- ImageMessage（Onboarding 進行中）：
  - 暫存圖片，等部門選定後繼續（不丟失）

### 新增 — 文字備註累積

- TextMessage（非指令文字）：
  - `append` 至 `UserState.pending_description`
  - `push` 回饋：「備註已記錄 📝」

### 新增 — Postback `action=confirm_submit`

- `pending_images` 為空 → `reply「尚未收到任何照片，請先傳送發票照片」`（不建立 Expense）
- 否則：
  1. `reply「⏳ 處理中，請稍候...」`（必須在 500ms 內）
  2. `BackgroundTask`：
     - 序列呼叫 `classify_and_extract()` 逐張處理
     - 呼叫 `create_batch_expense()`
     - 呼叫 `push_batch_summary()`（Flex Message）
  3. 清空 `UserState.pending_images` + `pending_description`

### 新增 — `services/line_service.py`

- 新增 `push_batch_summary(user_id, expense, ocr_results)`：
  - 依照 T1 設計稿的 Flex Message 格式
  - 各憑證類型行 × 數量 × 金額 + 合計 + 組別 + 備註 + 案件編號
  - ⚠️ **G1 阻斷**：Flex Message 結構需等 G1 通過後才能實作

### 防護規則

- 貼圖/語音訊息 → `push「此功能僅支援照片，請傳送發票圖片 📷」`
- 不破壞 `UserState.pending_images` 狀態

## 驗收標準

- [ ] 新用戶傳任意訊息 → Onboarding Quick Reply 部門選單
- [ ] 已設定部門使用者傳照片 → 累積至 pending，push「已收到第 N 張」
- [ ] Onboarding 期間傳照片 → 暫存不丟失
- [ ] 非指令文字 → 累積備註，push「備註已記錄」
- [ ] 按「確認送出」：500ms 內 reply「⏳ 處理中」
- [ ] 批次 OCR 完成後 push Flex Message 摘要
- [ ] 空批次防護：pending 為空時回覆提示，不建立 Expense
- [ ] 貼圖/語音 → 回覆提示，不破壞 pending
- [ ] 所有 DB 操作使用 async/await

---

## 事件紀錄

### 2026-04-11T00:00:00.000Z — 建立任務（assigned）
由 L1（project-lead）透過 /task-delegation 建立
⚠️ 等待 T1（G1）+ T3 + T4 全部完成後解鎖

### 2026-04-10T18:36:39.000Z — 開始執行（in_progress）
G1 通過 + T3 + T4 均已完成，由 L1（project-lead）委派給 backend-dev 啟動

### 2026-04-10T18:36:39.000Z — 完成交付（in_review）
Onboarding/累積/confirm_submit/背景任務/Flex Message 全部實作

### 2026-04-10T18:36:39.000Z — L1 審核通過（done）
審核者：project-lead。補件流程完整保留、SELECT FOR UPDATE 防競態正確、500ms 回應機制符合規格、序列 OCR 防 429、獨立 SessionLocal、Flex Message 依設計稿實作。全數通過。
重構 routers/webhook.py 完成：Onboarding 偵測、圖片累積（SELECT FOR UPDATE 防競態）、備註累積、confirm_submit Postback 批次送出（BackgroundTask）、edit_batch 取消、不支援訊息類型防護。新增 services/line_service.py 的 push_text() 與 push_batch_summary()（Flex Message 依 G1 設計稿實作）。
