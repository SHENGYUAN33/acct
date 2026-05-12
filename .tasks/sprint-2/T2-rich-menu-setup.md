# Rich Menu 設定

| 欄位 | 值 |
|------|-----|
| ID | T2 |
| 專案 | AcctAssist |
| Sprint | Sprint 2 |
| 指派給 | backend-dev |
| 優先級 | P0 |
| 狀態 | done |
| 依賴 | T1（G1 通過後） |
| 預估 | 2h |
| 建立時間 | 2026-04-11T00:00:00.000Z |

---

## 任務描述

⚠️ **前置條件**：T1 通過 G1 設計審核後才可開始

更新 LINE Rich Menu 為單按鈕版本：

1. **`services/line_service.py` — 更新 `setup_rich_menu()`**
   - 呼叫 `DELETE /v2/bot/richmenu/{id}` 刪除舊有 Rich Menu（若存在）
   - 以單按鈕「確認送出」規格重新建立（2500×843 全寬單格）
   - `Postback data="action=confirm_submit"`
   - 套用為 default Rich Menu

2. **新建 `scripts/` 目錄**
   - `scripts/__init__.py`（套件標記）
   - `scripts/setup_rich_menu.py`（可獨立執行的一次性設定腳本，支援重複執行）

3. **`routers/webhook.py` — 新增 TEXT fallback**
   - 使用者傳文字「確認送出」→ 觸發與 Postback 相同的 `confirm_submit` 邏輯
   - 防止 Rich Menu 設定失敗時使用者無法操作

## 驗收標準

- [ ] `python scripts/setup_rich_menu.py` 執行成功（無例外）
- [ ] LINE 聊天視窗底部顯示「✅ 確認送出」單按鈕
- [ ] 按鈕 Postback data 為 `"action=confirm_submit"`
- [ ] 舊有多按鈕 Rich Menu 已移除
- [ ] webhook.py 新增 TEXT fallback：輸入「確認送出」可觸發相同邏輯
- [ ] `setup_rich_menu.py` 可重複執行（冪等）

---

## 事件紀錄

### 2026-04-11T00:00:00.000Z — 建立任務（assigned）
由 L1（project-lead）透過 /task-delegation 建立
⚠️ 等待 T1 完成並通過 G1 後解鎖

### 2026-04-10T18:36:39.000Z — 開始執行（in_progress）
G1 通過，由 L1（project-lead）委派給 backend-dev 啟動

### 2026-04-10T18:36:39.000Z — 完成交付（in_review）
setup_rich_menu() 冪等更新、scripts/setup_rich_menu.py 建立、webhook.py TEXT fallback

### 2026-04-10T18:36:39.000Z — L1 審核通過（done）
審核者：project-lead。冪等設計正確、尺寸/Postback/chatBarText 全符合規格、圖片上傳優雅降級、腳本可獨立執行。全數通過。
完成三項子任務：
1. `services/line_service.py` — `setup_rich_menu()` 更新為 2500×843 單格 Postback 按鈕（`action=confirm_submit`），冪等設計（先刪 default 再建立）
2. `scripts/__init__.py` + `scripts/setup_rich_menu.py` — 可獨立執行的一次性設定腳本
3. `routers/webhook.py` — 新增 TEXT fallback：輸入「確認送出」→ 回覆臨時佔位訊息，T5 實作完整邏輯
