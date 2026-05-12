# 技術文件

| 欄位 | 值 |
|------|-----|
| ID | T4 |
| 專案 | AcctAssist |
| Sprint | Sprint 1 |
| 指派給 | tech-writer |
| 優先級 | P1 |
| 狀態 | assigned |
| 依賴 | T1,T2,T3 |
| 預估 | 1d |
| 建立時間 | 2026-04-10T03:09:26.113Z |

---

## 任務描述

建立 `.knowledge/deployment-guide.md` 部署指南，並更新 postmortem-log.md #003 為 resolved。

**新增檔案**：
- `.knowledge/deployment-guide.md`

**修改檔案**：
- `.knowledge/postmortem-log.md`：更新 #003 狀態為 `resolved`

**deployment-guide.md 內容需包含**：
1. 環境需求（Python 3.10+、Docker、Node.js）
2. 本地開發設定 SOP（.env、Docker Compose、Alembic、前後端啟動）
3. Staging 部署步驟（VM、Nginx、SSL、LINE Webhook URL 設定）
4. 環境變數說明表（含新增的 `LINE_CHANNEL_ACCESS_TOKEN`）
5. 常見問題（引用 `.knowledge/postmortem-log.md`）

**參考文件**：
- `.knowledge/specs/api-design.md`
- `.knowledge/postmortem-log.md`
- `.env.example`

⚠️ 執行 `/pitfall-resolve` 更新 #003

## 驗收標準

- [ ] `.knowledge/deployment-guide.md` 完成，包含本地 / Staging / Production 三種環境 SOP
- [ ] 環境變數說明表包含所有 `.env.example` 中的 key（含 `LINE_CHANNEL_ACCESS_TOKEN`）
- [ ] postmortem-log.md #003 狀態更新為 `resolved`
- [ ] 常見問題章節有引用 postmortem 紀錄

---

## 事件紀錄

### 2026-04-10T03:09:26.113Z — 建立任務（assigned）
由 L1 透過 /task-delegation 建立
