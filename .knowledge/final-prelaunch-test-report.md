# AcctAssist 上線前最終測試報告

## 1. 總結

報告時間：2026-06-02 17:24:58 +08:00  
測試人員：Codex  
分支：main  
Commit：bf2a91f0a1e1694c3a7c50c80298f29c3e9bc4fb  
工作區狀態：已有未提交變更，包含 `.github/workflows/deploy-gcp.yml`、`frontend/package.json`、`tests/conftest.py`，以及新增的 e2e、k6、postgres tests、frontend tests 等檔案。  
Staging URL：未提供  
Staging 測試帳號：未提供  
CI run id：未取得，本機未安裝 GitHub CLI `gh`  
k6 artifact：未產生，本機未安裝 k6，且未觸發 GitHub Actions stress workflow  

最終上線判定：No-Go。

主要原因：

- 後端完整 pytest 仍有 1 個失敗測試。
- PostgreSQL 整合測試沒有實際 PostgreSQL 測試環境，全部 skip。
- 前端 `npm ci --dry-run` 失敗，代表 `frontend/package.json` 與 `frontend/package-lock.json` 不同步。
- 前端 Vitest 無法執行，因目前 `frontend/node_modules` 沒有 `vitest`。
- E2E 無法執行，因 `e2e` 沒有 lockfile 且目前沒有 Playwright 可執行檔。
- Staging URL 與測試帳密未提供，E2E 與壓力測試無法形成正式上線證據。
- CI/CD 目前沒有把 frontend Vitest 與 Playwright E2E 納入 deploy workflow。

## 2. 執行環境

| 項目 | 結果 |
|---|---|
| OS Shell | Windows PowerShell |
| Python | 3.12.10 |
| Node.js | v24.15.0 |
| npm | 11.12.1 |
| k6 | 未安裝，`k6` command not found |
| GitHub CLI | 未安裝，`gh` command not found |
| Git remote | `https://github.com/SHENGYUAN33/acct.git` |

測試使用的主要環境變數：

- `DATABASE_URL=sqlite:///file::memory:?cache=shared&uri=true`
- `LINE_CHANNEL_SECRET=test-secret-32chars-placeholder00`
- `LINE_CHANNEL_ACCESS_TOKEN=test-token`
- `GEMINI_API_KEY=test-key`
- `JWT_SECRET=test-jwt-secret-for-ci-only-not-production`
- `APP_ENV=development`
- `ENABLE_SCHEDULED_BATCH=false`

## 3. 單元測試

為什麼要測：

單元測試負責確認核心邏輯在不依賴外部 API 與真實資料庫的情況下仍可運作。這層主要攔截安全驗證、OCR 分類、LIFF 流程、批次報帳、自動拆單、邊界值、網路韌性與退貨配對等低層風險。

怎麼測：

```powershell
python -m pytest tests/unit/ -q --tb=short
```

測試結果：

| 結果 | 數量 |
|---|---:|
| Passed | 187 |
| Failed | 0 |
| Warnings | 2 |

重要 warning：

- `HTTP_422_UNPROCESSABLE_ENTITY` 已 deprecated，建議改用 `HTTP_422_UNPROCESSABLE_CONTENT`。
- `download_image` 成功但 DB commit 失敗時，測試已提示可能殘留孤兒檔案。

如何修正：

- 將 FastAPI deprecated constant 更新為新常數。
- 在檔案下載與 DB 寫入流程加上失敗清理機制：DB commit 失敗時刪除已寫入的本機檔案。

單元測試結論：通過，但仍有可修正 warning 與已揭露韌性風險。

## 4. 後端整合測試

為什麼要測：

整合測試確認 FastAPI router、service、資料庫 fixture、排程設定與 webhook 流程可以合在一起運作。這層最接近 LINE webhook、批次送出、onboarding、auto split、並發狀態更新等真實業務流程。

怎麼測：

```powershell
python -m pytest tests/integration/ -q --tb=short
python -m pytest tests/ --ignore=tests/postgres/ -q --tb=short
```

測試結果：

| 測試命令 | 結果 |
|---|---|
| `tests/integration/` | 29 passed, 1 failed, 4 skipped, 6 warnings |
| `tests/ --ignore=tests/postgres/` | 216 passed, 1 failed, 4 skipped, 8 warnings |

完整套件失敗測試：

```text
tests/integration/test_batch_flow.py::TestOnboardingFlow::test_new_user_without_binding_triggers_dept_selection
AssertionError: Expected 'mock' to have been called once. Called 0 times.
```

關鍵 log：

```text
Cannot read scheduler settings from DB: no such table: system_settings
webhook: 名冊綁定失敗 ... no such table: staff_roster
```

原因判斷：

測試預期新使用者未綁定時會呼叫 `reply_with_dept_selection`。實際流程先進入名冊綁定分支並查詢 `staff_roster`，但 integration SQLite fixture 沒建立 `staff_roster` 與 `system_settings`，造成流程提前進入錯誤回覆，沒有呼叫部門選單。

單獨跑 `tests/integration/` 時的另一個失敗：

```text
tests/integration/test_auto_split_flow.py::TestConfirmSubmitCancelsTimer::test_confirm_submit_no_cancel_when_auto_split_disabled
ValueError: not enough values to unpack (expected 3, got 0)
```

原因判斷：

單獨執行 integration suite 時，`main` 匯入與 `core.database.create_engine` 初始化出現測試環境不穩定。完整套件與單獨整合測試出現不同失敗，代表測試 fixture 或 import patch 有順序敏感問題。

其他重要 warning：

- pending_images 並發 read-modify-write 可能導致圖片遺失。
- 15MB 圖片下載沒有大小限制，可能造成磁碟與記憶體風險。
- FastAPI `on_event` deprecated，建議未來改用 lifespan handler。

如何修正：

- 讓 `tests/integration/test_batch_flow.py` 的 SQLite schema 與目前模型一致，補上 `staff_roster`、`system_settings` 等目前流程會讀取的表。
- 明確 patch `routers.webhook.settings.enable_roster_binding` 與 `enable_user_binding` 實際引用來源，避免只 patch `core.config.settings` 但 router 已持有不同物件。
- 清理 integration tests 的 import patch 與 fake psycopg2 設定，避免單獨跑與整包跑結果不一致。
- 對 pending_images append 改用 PostgreSQL row lock 或 atomic update。
- 在 `download_image` 中加上 `settings.max_upload_bytes` 檢查。

整合測試結論：不通過，是目前後端上線阻塞項。

## 5. PostgreSQL 整合測試

為什麼要測：

SQLite 無法驗證 PostgreSQL 專屬能力，例如 ARRAY 欄位、migration、transaction lock、序號並發與實際 production database dialect 行為。這是部署前必要關卡。

怎麼測：

```powershell
python -m pytest tests/postgres/ -q --tb=short
```

測試結果：

| 結果 | 數量 |
|---|---:|
| Skipped | 7 |

原因：

目前本機使用 SQLite `DATABASE_URL`，不是 PostgreSQL URL，因此 `tests/postgres/` 依 fixture 設計全部 skip。

如何修正：

- 使用 PostgreSQL 16 測試資料庫執行：

```powershell
$env:DATABASE_URL="postgresql+psycopg2://testuser:testpassword@localhost:5432/acctassist_test"
alembic upgrade head
python -m pytest tests/postgres/ -v --tb=short -q
```

- 在 CI 中保留 PostgreSQL service container，且將該 job 設為部署前硬性 gate。

PostgreSQL 測試結論：Blocked，尚未形成正式上線證據。

## 6. 前端測試

為什麼要測：

前端測試確認 Dashboard 的 axios interceptor、token 流程、WaitingReturnModal 邏輯與 build artifact 正常。正式上線前，必須確定乾淨 CI 環境可重現安裝與測試。

怎麼測：

```powershell
npm ci --dry-run
npm test
npm run build
npm ls vitest
```

測試結果：

| 項目 | 結果 |
|---|---|
| `npm ci --dry-run` | Failed |
| `npm test` | Failed |
| `npm run build` | Passed |
| `npm ls vitest` | Failed，dependency tree empty |

重要錯誤：

```text
npm ci can only install packages when package.json and package-lock.json are in sync.
Missing: @vitest/coverage-v8, vitest, jsdom, ...
'vitest' is not recognized as an internal or external command
```

build 結果：

```text
vite v8.0.3 building client environment for production...
1815 modules transformed.
dist/index.html 0.45 kB
dist/assets/index-2FoHvcgc.js 306.28 kB
build completed
```

如何修正：

- 同步 `frontend/package-lock.json`，讓 `vitest`、`jsdom`、coverage 相關 dependency 進入 lockfile。
- 使用乾淨環境重跑：

```powershell
cd frontend
npm ci
npm test
npm run build
```

前端測試結論：build 通過，但測試與 CI clean install 不通過，是上線阻塞項。

## 7. E2E 測試

為什麼要測：

E2E 測試驗證使用者真實流程：登入、錯誤密碼、token 保存、未登入導向、報帳列表、審核通過、退回、CSV 匯出、WAITING_RETURN modal、401 導回登入。這些流程跨越 frontend、backend、auth、DB 與瀏覽器行為，單元測試無法替代。

怎麼測：

```powershell
cd e2e
npm ci --dry-run
npm test
```

測試結果：

| 項目 | 結果 |
|---|---|
| `npm ci --dry-run` | Failed |
| `npm test` | Failed |
| Staging E2E | Blocked，未提供 `BASE_URL`、`E2E_ADMIN_USER`、`E2E_ADMIN_PASS` |

重要錯誤：

```text
npm ci command can only install with an existing package-lock.json
'playwright' is not recognized as an internal or external command
```

如何修正：

- 建立並提交 `e2e/package-lock.json`。
- 在乾淨環境安裝 Playwright：

```powershell
cd e2e
npm ci
npx playwright install --with-deps chromium
$env:BASE_URL="https://staging.example.com"
$env:E2E_ADMIN_USER="..."
$env:E2E_ADMIN_PASS="..."
npm test
```

- 測試帳密不可寫入報告或 repo，只用環境變數或 CI secret。

E2E 測試結論：Blocked，尚未形成正式上線證據。

## 8. 壓力測試

為什麼要測：

壓力測試確認 GCP VM、FastAPI、DB、auth、Webhook 與 Dashboard API 在上線流量下仍能維持 SLA，並驗證尖峰流量不會造成 5xx、timeout 或服務不可用。

怎麼測：

本機檢查：

```powershell
k6 version
```

正式建議：

```powershell
gh workflow run stress-test.yml -f target_url=https://staging.example.com -f scenario=dashboard
gh workflow run stress-test.yml -f target_url=https://staging.example.com -f scenario=webhook
gh workflow run stress-test.yml -f target_url=https://staging.example.com -f scenario=spike
gh workflow run stress-test.yml -f target_url=https://staging.example.com -f scenario=all
```

測試結果：

| 項目 | 結果 |
|---|---|
| 本機 k6 | Failed，command not found |
| GitHub Actions stress workflow | 未觸發 |
| Staging 壓測 | Blocked，未提供 target URL 與 secrets |

SLA 門檻：

| Scenario | 門檻 |
|---|---|
| dashboard | p95 < 500ms，錯誤率 < 1% |
| webhook | p95 < 2000ms，錯誤率 < 1% |
| spike | p99 < 10s，錯誤率 < 5% |

CI 設定觀察：

- `dashboard` scenario `continue-on-error: false`，可阻斷。
- `webhook` 與 `spike` scenario `continue-on-error: true`，目前只記錄，不阻斷。

如何修正：

- 以 GitHub Actions manual workflow 跑 staging 壓測並保存 artifact。
- 若 webhook/spike 也是上線必要門檻，建議將其 `continue-on-error` 改為 `false` 或建立明確的人工核准 gate。
- 在報告中記錄 GitHub run id、artifact 名稱、p95/p99/error rate。

壓力測試結論：Blocked，尚未形成正式上線證據。

## 9. CI/CD 測試

為什麼要測：

CI/CD 是最後一道防線，必須保證測試失敗不會進入 build 或 deploy，且部署後 health check 失敗會中止流程。

怎麼測：

本次未觸發 workflow，只做本機靜態檢查：

```powershell
Select-String -Path .github\workflows\deploy-gcp.yml,.github\workflows\stress-test.yml -Pattern "pytest|npm run build|npm test|vitest|playwright|k6|workflow_dispatch|environment: production|health check|continue-on-error"
```

測試結果：

deploy workflow 已包含：

- `pytest tests/ --tb=short -q`
- PostgreSQL service container
- `alembic upgrade head`
- `pytest tests/postgres/ -v --tb=short -q`
- frontend `npm ci`
- frontend `npm run build`
- production environment gate
- VM deploy health check `/health`

deploy workflow 缺口：

- 未跑 frontend Vitest。
- 未跑 Playwright E2E。
- `pytest tests/` 會包含 `tests/postgres/`，但同 workflow 又另設 PostgreSQL job；建議明確 ignore postgres tests，避免 SQLite job 中 postgres tests 只 skip 而混淆結果。
- 無測試報告 artifact 或 junit report。

stress workflow 已包含：

- manual trigger
- k6 installation
- dashboard/webhook/spike/all scenarios
- k6 result artifact upload
- GitHub step summary

stress workflow 缺口：

- webhook/spike 目前 `continue-on-error: true`，無法作為硬性上線 gate。
- 未與 deploy workflow 串接，仍需人工觸發與審查。

如何修正：

- deploy workflow 加入 frontend unit test：

```yaml
run: npm test
```

- deploy workflow 加入 staging E2E job，或至少在 production environment approval 前要求 E2E workflow 成功。
- 為 pytest 加上 junit artifact，為 Playwright 加上 HTML report artifact。
- 將壓測結果納入 release checklist 或 environment approval 條件。

CI/CD 測試結論：靜態檢查可看出 deploy 有基本 gate，但目前覆蓋不足，尚不能視為完整上線把關。

## 10. 上線阻塞清單

| 優先級 | 問題 | 影響 | 建議修正 |
|---|---|---|---|
| P0 | 後端完整 pytest 失敗 | 不能保證 webhook onboarding 流程正確 | 修正 integration fixture schema 與 settings patch |
| P0 | 前端 lockfile 不同步 | CI clean install 會失敗 | 更新 `frontend/package-lock.json` |
| P0 | Vitest 無法執行 | 前端邏輯測試沒有證據 | lockfile 修正後重跑 `npm ci && npm test` |
| P0 | PostgreSQL tests 未實跑 | migration/ARRAY/並發未驗證 | 使用 PostgreSQL 16 test DB 或 CI service container |
| P1 | E2E 未實跑 | 使用者主流程未驗證 | 提供 staging URL/帳密並建立 e2e lockfile |
| P1 | k6 未實跑 | SLA 無正式證據 | 觸發 `stress-test.yml` 並保存 artifact |
| P1 | CI 未跑 Vitest/E2E | 部署前 gate 不完整 | 將 frontend test 與 E2E 納入 workflow |
| P2 | warnings 暴露韌性風險 | 可能上線後變成事故 | 排程修正 pending_images race、大圖限制、孤兒檔案清理 |

## 11. 建議重新驗收順序

1. 修正 integration fixture 與 settings patch，確認：

```powershell
python -m pytest tests/ --ignore=tests/postgres/ -q --tb=short
```

2. 同步 frontend lockfile，確認：

```powershell
cd frontend
npm ci
npm test
npm run build
```

3. 使用 PostgreSQL 16 測試 DB，確認：

```powershell
alembic upgrade head
python -m pytest tests/postgres/ -v --tb=short -q
```

4. 建立 e2e lockfile 並在 staging 跑：

```powershell
cd e2e
npm ci
npx playwright install --with-deps chromium
npm test
```

5. 觸發 k6 stress workflow，保存 run id、artifact、p95、p99、錯誤率。

6. 確認 deploy workflow 在以上測試皆通過後才允許 production deploy，且 `/health` 回傳 success。

## 12. 最終結論

目前不建議正式上線。

本次測試已確認後端 unit 層穩定、前端可 build，但上線前關鍵 gate 仍未通過：後端整合測試失敗、PostgreSQL 未實跑、前端 clean install 和 Vitest 不可用、E2E 與 k6 缺少 staging 執行證據、CI/CD 未涵蓋所有必要測試。

修正上述 P0/P1 項目並重新跑完整驗收後，才可將判定改為 Go。
