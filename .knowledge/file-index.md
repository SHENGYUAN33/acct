# AcctAssist 文件索引 (File Index)

> **用途**: 統一管理專案文件位置，快速查找 Sprint 記錄、規範文件、會議紀錄
> **更新時機**: 每次新增 Sprint / 更新規範 / 產出重要文件時
> **版本**: v2.0
> **最後更新**: 2026-04-17

---

## 1. Sprint 記錄表

| Sprint | 期間 | 類型 | 目標 | 提案書 | 開發計畫 | 回顧 | 狀態 |
|--------|------|------|------|--------|---------|------|------|
| S1 | 2026-04-08 | full | MVP 驗收與生產就緒（後端測試、Dashboard、Webhook 超時修正） | `proposal/sprint1-proposal.md` | `proposal/sprint1-dev-plan.md` | 待產出 | `completed` |
| S2 | 2026-04-10 ~ 2026-04-12 | full | 多張照片批次報帳 + 部門 Onboarding + LINE Rich Menu | `proposal/sprint2-proposal.md` | `proposal/sprint2-dev-plan.md` | 待產出 | `completed` |
| S3 | 2026-04-13 ~ 2026-04-14 | full | Auto Split 自動切割（滑動視窗 Timer + 多筆切割） | 待補 | 待補 | 待產出 | `completed` |

**說明**:
- **類型**: `full` (完整流程) / `quick` (快速開發) / `hotfix` (緊急修復) / `research` (研究探索)
- **狀態**: `planning` / `in_progress` / `review` / `completed` / `cancelled`

---

## 2. 知識庫文件

### 2.1 核心規範文件

| 文件名稱 | 路徑 | 版本 | 用途 | 最後更新 |
|---------|------|------|------|---------|
| **專案開發規範** | `CLAUDE.md` | - | AcctAssist 專案的開發約束與架構說明 | 2026-04-08 |
| **共用開發規則** | `.knowledge/company-rules.md` | v1.0 | 文件治理、命名規範、Commit 紀律 | 2026-03-25 |
| **共用團隊流程** | `.knowledge/team-workflow.md` | v1.0 | 指揮鏈、Sprint 流程、Gate、Review | 2026-03-25 |
| **專案概述** | `.knowledge/project-overview.md` | v1.3 | 技術棧、系統架構、核心功能說明 | 2026-04-17 |
| **踩坑紀錄** | `.knowledge/postmortem-log.md` | v1.1 | 問題記錄與解決方案（13 筆） | 2026-04-13 |
| **通用踩坑紀錄** | `.knowledge/postmortem-common.md` | v1.0 | 跨專案通用踩坑（由 /knowledge-feedback 維護） | 2026-03-26 |
| **文件索引** | `.knowledge/file-index.md` | v2.0 | 本文件（Sprint 與文件索引） | 2026-04-17 |
| **機制架構文件** | `.knowledge/mechanism-architecture.md` | v1.1 | 機制一（Onboarding）、機制二（批次）、機制三（Auto Split）技術流程 | 2026-04-14 |
| **工作日誌** | `.knowledge/work-log.md` | - | 每日工作記錄 | 2026-04-14 |

### 2.2 技術規範文件

| 文件名稱 | 路徑 | 版本 | 用途 | 狀態 |
|---------|------|------|------|------|
| API 設計規範 | `.knowledge/specs/api-design.md` | v1.2 | RESTful API 端點定義（含認證端點） | ✅ 存在 |
| 資料模型規範 | `.knowledge/specs/data-model.md` | v2.0 | 資料表結構、欄位定義、Alembic 遷移歷史 | ✅ 存在 |
| 功能規格書 | `.knowledge/specs/feature-spec.md` | v1.0 | Sprint 1 功能規格（待更新至 Sprint 3） | ⚠️ 過時 |
| 架構文件 | `.knowledge/architecture.md` | - | 系統架構（目前為通用模板） | ⚠️ 通用模板未客製化 |
| 部署指南 | `.knowledge/deployment-guide.md` | - | 生產環境部署 SOP | ❌ 待建立 |
| 測試策略 | `.knowledge/testing-strategy.md` | - | 單元/整合/E2E 測試規劃 | ❌ 待建立 |

---

## 3. Sprint 提案與計畫書

### 目錄結構
```
proposal/
├── sprint1-proposal.md      # Sprint 1 提案書
├── sprint1-dev-plan.md      # Sprint 1 開發計畫書
├── sprint2-proposal.md      # Sprint 2 提案書
├── sprint2-dev-plan.md      # Sprint 2 開發計畫書（G4 通過，已封版）
└── ...
```

### 當前 Sprint
**S3 — Auto Split 自動切割**（`completed` 階段，2026-04-14 完成）

---

## 4. 任務追蹤文件

### 目錄結構
```
.tasks/
├── T001-{task-name}.md         # 任務詳情（系統自動建立）
├── T002-{task-name}.md
└── ...
```

### 任務狀態統計
| 狀態 | 數量 |
|------|------|
| `pending` | 0 |
| `in_progress` | 0 |
| `in_review` | 0 |
| `done` | 19（S1:5 + S2:9 + S3:5 合計，各 Sprint 完整封版） |
| **總計** | **19** |

---

## 5. 會議與決策記錄（未來規劃）

| 日期 | 類型 | 主題 | 參與者 | 記錄 | 決策 |
|------|------|------|--------|------|------|
| - | - | - | - | - | 待建立 |

**會議類型**:
- `G0` - 需求確認會議
- `G1` - 設計審核會議
- `G2` - 程式碼審查會議
- `G3` - 測試驗收會議
- `G4` - 文件審查會議
- `G5` - 部署就緒會議
- `retro` - Sprint 回顧會議
- `sync` - 同步會議

---

## 6. 外部資源與參考

### 官方文件

| 資源 | 連結 | 用途 |
|------|------|------|
| FastAPI 官方文件 | https://fastapi.tiangolo.com/ | API 框架參考 |
| SQLAlchemy 2.0 文件 | https://docs.sqlalchemy.org/ | ORM 操作參考 |
| LINE Messaging API | https://developers.line.biz/en/docs/messaging-api/ | LINE Bot 開發 |
| Google Gemini API | https://ai.google.dev/docs | OCR 與 AI 整合 |
| Vue 3 官方文件 | https://vuejs.org/ | 前端框架參考 |
| TailwindCSS 文件 | https://tailwindcss.com/ | CSS 框架參考 |

### 內部資源

| 資源 | 路徑 | 說明 |
|------|------|------|
| AgentHub 標準文件庫 | `C:/Users/User/Desktop/AgentHub/.knowledge/` | 公司共用規範與模板 |
| 專案範本庫 | `AgentHub/.knowledge/company/project-templates/` | 各類專案標準模板 |

---

## 7. 文件命名規範

### Sprint 相關文件
- 提案書: `sprint-{編號}-proposal.md`（例：`sprint-001-proposal.md`）
- 開發計畫: `sprint-{編號}-dev-plan.md`
- 回顧: `sprint-{編號}-retro.md`

### 任務文件
- 格式: `T{編號}-{kebab-case-name}.md`（例：`T001-setup-database.md`）

### 審核記錄
- 格式: `review-{YYYY-MM-DD}-{類型}.md`（例：`review-2026-04-08-G2.md`）

### Gate 記錄
- 格式: `gate-{G編號}-{YYYY-MM-DD}.md`（例：`gate-G0-2026-04-08.md`）

---

## 8. 文件更新日誌

| 日期 | 變更內容 | 負責人 |
|------|---------|--------|
| 2026-04-08 | 初始化文件索引結構 | product-manager |
| 2026-04-08 | 建立 Sprint 1 提案書（`proposal/sprint1-proposal.md`） | product-manager |
| 2026-04-11 | Sprint 2 封版；更新 postmortem v1.1；api-design.md v1.1；project-overview.md v1.2 | product-manager |
| 2026-04-14 | Sprint 3 完成（Auto Split T1–T10）；新增 mechanism-architecture.md v1.1；postmortem #013 | tech-lead |
| 2026-04-17 | 全面文件更新：data-model v2.0、api-design v1.2、project-overview v1.3、file-index v2.0 | project-lead |

---

## 9. 快速查找指令

### 查找 Sprint 記錄
```bash
# 列出所有 Sprint 提案
ls proposal/sprint-*-proposal.md

# 查看最新 Sprint 計畫
cat proposal/sprint-*-dev-plan.md | tail -1
```

### 查找任務
```bash
# 列出所有任務
ls .tasks/

# 查找進行中的任務
grep -l "status: in_progress" .tasks/*.md
```

### 查找踩坑紀錄
```bash
# 查看所有 open 狀態的問題
grep "| open |" .knowledge/postmortem-log.md
```

---

## 10. 維護指引

### 何時更新此文件？
- ✅ 建立新 Sprint 時（更新第 1 節表格）
- ✅ 新增規範文件時（更新第 2 節）
- ✅ 重大會議後（更新第 5 節）
- ✅ 發現外部資源時（更新第 6 節）
- ✅ 變更命名規範時（更新第 7 節）

### 更新流程
1. 修改對應章節
2. 更新「最後更新」日期
3. 在第 8 節「文件更新日誌」新增記錄
4. 執行 `/spec-update` 確保規範版本正確遞增（如有異動規範文件）

---

**維護者**: project-lead (L1)
**審查週期**: 每週五或 Sprint 結束時
**最後審查**: 2026-04-17
