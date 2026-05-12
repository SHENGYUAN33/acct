# Sprint 提案書：Sprint 1 — AcctAssist MVP 驗收與生產就緒

> **專案**: AcctAssist（LINE Bot 智能報帳系統）
> **提案人**: product-manager
> **日期**: 2026-04-08
> **Sprint 編號**: S1
> **狀態**: 待 G0 審核

---

## 1. Sprint 背景與目標

### 1.1 背景

AcctAssist 核心功能已完成初步開發，包含：
- LINE Bot 報帳對話流程（部門選擇 → 發票上傳）
- Gemini OCR 自動辨識發票資訊
- 員工實名制與案件流水號（最新提交）
- Dashboard 審核 API（CRUD 端點）

目前系統尚未進行系統性測試，Vue3 Dashboard 前端尚未完善，且無部署文件。**Sprint 1 目標：將現有功能驗收完畢，補齊測試與文件，使系統達到可交付生產的標準。**

### 1.2 Sprint 目標

| # | 目標 | 衡量標準 |
|---|------|---------|
| 1 | 後端功能驗收完整 | 核心 API 測試覆蓋率 ≥ 80% |
| 2 | Vue3 Dashboard 可用 | 審核操作流程可端對端執行 |
| 3 | 生產環境就緒 | 可成功部署至 staging 環境 |
| 4 | 技術文件完備 | API 規格書與部署指南完成 |

---

## 2. 目標用戶

| 角色 | 使用情境 |
|------|---------|
| **報帳人員（影視製作團隊成員）** | 透過 LINE 上傳發票、選擇部門、追蹤審核狀態 |
| **財務審核人員** | 透過 Dashboard 審核報帳、核可或退件 |
| **系統管理員** | 部署、監控、管理使用者與資料 |

---

## 3. 核心功能範圍

### P0 — 必須完成（阻斷發布）

| 功能 | 說明 | 現狀 |
|------|------|------|
| 後端單元測試 | `services/`、`routers/` 核心邏輯測試 | 缺少 |
| LINE Bot E2E 測試 | Webhook 流程模擬測試 | 缺少 |
| Vue3 Dashboard UI | 報帳清單、詳情頁、審核操作 | 待確認 |
| 案件流水號顯示 | Dashboard 顯示流水號、支援查詢 | 已後端，前端待整合 |
| 員工實名制驗證 | LINE User ID ↔ 員工身份綁定完整測試 | 已開發，待測試 |

### P1 — 應完成（品質提升）

| 功能 | 說明 | 現狀 |
|------|------|------|
| API 規格書 | RESTful 端點文件（`.knowledge/api-spec.md`） | 缺少 |
| 部署指南 | Staging/Prod 部署 SOP（`.knowledge/deployment-guide.md`） | 缺少 |
| LINE Webhook 超時防護 | 背景任務處理 OCR，Webhook 立即回 200 | monitoring 狀態 |
| 錯誤處理強化 | OCR 失敗時給使用者明確提示 | 基本實作 |

### P2 — 可延後（未來 Sprint）

| 功能 | 說明 |
|------|------|
| LINE Rich Menu | 底部快捷選單（報帳/查詢/說明） |
| Email 通知 | 審核結果 Email 通知報帳人員 |
| 批次匯出 | Excel/CSV 匯出功能 |
| 重複發票偵測 | 發票號碼去重邏輯 |

---

## 4. 範圍界定

### 做（Sprint 1 範圍內）
- 後端測試：`expense_service`、`ocr_service`、`line_service`、Webhook 路由
- Vue3 Dashboard：報帳清單 + 詳情頁 + 審核操作（通過/退件）
- 技術文件：API 規格書、部署指南
- 修復已知問題：LINE Webhook 超時（#003 postmortem）
- Staging 環境驗證

### 不做（明確排除）
- LINE Rich Menu（Phase 2）
- Email 通知（Phase 2）
- 批次匯出（Phase 2）
- 多專案支援（Phase 3）
- 行動版 RWD（Phase 3）
- 後台帳號管理系統

---

## 5. 技術路線

### 5.1 測試策略

```
pytest (後端)
├── tests/unit/
│   ├── test_expense_service.py   # CRUD + 狀態轉換
│   ├── test_ocr_service.py       # OCR 結果解析
│   └── test_line_service.py      # 狀態機操作
├── tests/integration/
│   ├── test_webhook.py           # Webhook 流程（mock LINE API）
│   └── test_expenses_api.py      # Dashboard API
└── conftest.py                   # DB fixtures（in-memory SQLite）
```

### 5.2 Dashboard 功能頁面

```
Vue3 SPA
├── /expenses                    # 報帳清單（支援 status/日期過濾）
├── /expenses/:id                # 報帳詳情（發票圖片 + OCR 資料）
└── /expenses/:id/review         # 審核操作（通過/退件+原因）
```

### 5.3 LINE Webhook 超時修正

- 採用 FastAPI `BackgroundTasks` 非同步處理 OCR
- Webhook 收到圖片後立即回 200，OCR 完成後 `push_message` 推送結果
- 需在 `.env` 新增 `LINE_CHANNEL_ACCESS_TOKEN`（用於 push）

---

## 6. 風險評估

| 風險 | 影響 | 可能性 | 緩解方式 |
|------|------|--------|---------|
| Gemini OCR API 配額不足 | 測試無法跑完 | 中 | 測試用 mock，生產用真實 API |
| LINE Bot SDK 版本相容性 | 測試框架整合困難 | 低 | 使用官方 mock 工具 |
| Vue3 Dashboard 狀態不明 | P0 功能無法完成 | 中 | Sprint 開始前先確認現有程度 |
| PostgreSQL Docker 版本衝突 | 本地測試環境不穩 | 低 | 統一 Docker Compose 版本 |
| LINE Webhook 超時修正引入新 Bug | 推送訊息時序問題 | 中 | 保留原 reply 作為 fallback |

---

## 7. 步驟與關卡規劃

### 勾選的步驟

- [x] 需求分析（G0）
- [ ] UI 圖稿（G1）— **不需要**（Dashboard 無新 UI 設計，沿用現有）
- [x] 實作（G2）
- [x] 測試（G3）
- [x] 文件（G4）
- [x] 部署（G5）
- [ ] 發佈（G6）— **不需要**（Staging 驗證即可，正式上線另排 Sprint）

### 阻斷規則

- **G3 阻斷**：測試覆蓋率 < 80% 時不得進入文件階段
- **G5 阻斷**：G3 + G4 未通過不得進行部署

### 關卡序列

```
G0（需求確認）→ G2（程式碼審查）→ G3（測試驗收）→ G4（文件審查）→ G5（部署就緒）
```

---

## 8. 初步時程

| 階段 | 工作內容 | 預估時間 | 交付物 |
|------|---------|---------|--------|
| G0 規劃 | 開發計畫書、任務拆解 | 0.5 天 | `sprint1-dev-plan.md` |
| 後端測試（T1） | 撰寫 pytest 測試套件 | 2 天 | `tests/` 目錄 |
| Dashboard UI（T2） | Vue3 完整頁面 | 2 天 | `frontend/` 更新 |
| Webhook 修正（T3） | 背景任務 + push | 0.5 天 | `routers/webhook.py` |
| 技術文件（T4） | API 規格 + 部署指南 | 1 天 | `.knowledge/` 文件 |
| 部署驗證（T5） | Staging 環境測試 | 0.5 天 | 部署記錄 |
| **總計** | | **約 6.5 天** | |

---

## 9. 團隊組成

| 角色 | Agent | 負責任務 |
|------|-------|---------|
| Product Manager (L1) | product-manager | G0 規劃、PM Review、Gate 審核呈報 |
| Tech Lead (L1) | tech-lead | 開發計畫書、任務拆解、Code Review |
| Backend Dev (L2) | backend-dev | T1（測試）、T3（Webhook 修正） |
| Frontend Dev (L2) | frontend-dev | T2（Dashboard UI） |
| Tech Writer (L2) | tech-writer | T4（文件） |
| DevOps (L2) | devops | T5（部署驗證） |

---

## 10. 驗收標準（G0 Checklist）

### 功能驗收
- [ ] LINE Bot 完整流程可正常運作（選部門 → 上傳 → 辨識 → 回覆）
- [ ] 員工實名制：同一 LINE User ID 不可重複建立使用者
- [ ] 案件流水號：每筆報帳唯一、格式正確
- [ ] Webhook 超時：圖片上傳後 500ms 內回應，OCR 完成後推送通知

### 測試驗收
- [ ] 後端單元測試覆蓋率 ≥ 80%
- [ ] 所有 P0 功能有對應的整合測試
- [ ] 測試可在 CI 環境穩定執行（無 flaky test）

### Dashboard 驗收
- [ ] 報帳清單可正確顯示（支援狀態篩選）
- [ ] 詳情頁顯示完整 OCR 資料與發票圖片
- [ ] 審核操作（通過/退件）可正確更新資料庫狀態

### 文件驗收
- [ ] API 規格書已建立（`.knowledge/api-spec.md`）
- [ ] 部署指南已完成（`.knowledge/deployment-guide.md`）
- [ ] Postmortem #003 已升級為 `resolved`

### 部署驗收
- [ ] Staging 環境成功部署
- [ ] Staging 上 LINE Webhook 可正常接收事件
- [ ] `GET /health` 回應 200

---

## 11. 已知問題與技術債

| # | 問題 | 嚴重度 | 處理計畫 |
|---|------|--------|---------|
| Postmortem #003 | LINE Webhook 超時（monitoring） | 高 | Sprint 1 T3 解決 |
| Dashboard 狀態不明 | Vue3 前端完成度未確認 | 中 | Sprint 開始前 Tech Lead 確認 |
| 測試覆蓋率空白 | 目前無任何自動化測試 | 高 | Sprint 1 T1 全面補齊 |

---

## 12. 不在此 Sprint 的功能（Backlog）

| 功能 | 優先級 | 預估 Sprint |
|------|--------|------------|
| LINE Rich Menu | P1 | Sprint 2 |
| Email 審核通知 | P1 | Sprint 2 |
| 批次匯出 Excel/CSV | P2 | Sprint 3 |
| 重複發票偵測 | P1 | Sprint 2 |
| 使用者權限系統 | P1 | Sprint 3 |

---

## 13. 參考文件

| 文件 | 路徑 |
|------|------|
| 專案開發規範 | `CLAUDE.md` |
| 專案概述 | `.knowledge/project-overview.md` |
| 踩坑紀錄 | `.knowledge/postmortem-log.md` |
| 共用開發規則 | `.knowledge/company-rules.md` |
| 共用工作流程 | `.knowledge/team-workflow.md` |

---

**老闆決策**: [ ] 通過進入 G0 / [ ] 調整範圍 / [ ] 擱置

> 備註：G0 審核通過後，Tech Lead 將產出 `sprint1-dev-plan.md` 並進行任務拆解。
