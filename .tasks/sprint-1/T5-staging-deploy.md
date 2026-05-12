# 部署驗證

| 欄位 | 值 |
|------|-----|
| ID | T5 |
| 專案 | AcctAssist |
| Sprint | Sprint 1 |
| 指派給 | devops |
| 優先級 | P1 |
| 狀態 | assigned |
| 依賴 | T4 |
| 預估 | 0.5d |
| 建立時間 | 2026-04-10T03:09:26.113Z |

---

## 任務描述

依照 `.knowledge/deployment-guide.md` 執行 Staging 環境部署，並驗證三項指標通過。

**驗證指標**：
1. `GET /health` → 200 OK
2. LINE Webhook 可接收測試事件（驗簽通過）
3. Dashboard 可存取（`GET /api/v1/expenses` 回傳正確格式）

## 驗收標準

- [ ] Staging 環境成功部署（無 error log）
- [ ] `GET /health` 回應 `200 OK`
- [ ] LINE Webhook 簽章驗證通過（測試事件可接收）
- [ ] `GET /api/v1/expenses` 回傳正確 JSON 格式
- [ ] 部署結果記錄於 dev-plan Section 10

---

## 事件紀錄

### 2026-04-10T03:09:26.113Z — 建立任務（assigned）
由 L1 透過 /task-delegation 建立
