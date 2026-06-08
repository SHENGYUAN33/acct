# AcctAssist 架構決策紀錄

此文件記錄已落地的架構設計，供未來 Claude Code 快速釐清設計脈絡。
閱讀本文件後，應能理解「為什麼這樣設計」，而不只是「現在長什麼樣」。

---

## 1. 圖片儲存與存取架構

### 決策：後端代理 + JWT query param

**背景**  
系統儲存的發票圖片含有 PII（統一編號、金額、員工姓名），原本以 FastAPI `StaticFiles` 直接公開，無需登入即可存取。

**改動時間**：2026-06-08

**現行設計**

```
DB 儲存格式：「uploads/uuid.jpg」（相對路徑，不含 host）

前端請求路徑：GET /api/v1/uploads/{uuid}.jpg?token=<jwt>
後端代理端點：routers/files.py → serve_upload()
實際檔案位置：Path(settings.storage_path) / filename
```

**為什麼用 query param 而不是 Authorization header**  
瀏覽器的 `<img>` 標籤無法附帶自訂 header，只有 `fetch()` / `axios` 可以。
為了不把所有圖片改成 async blob URL（會大幅增加元件複雜度），選擇在 URL 帶 token。
Token 有效期 8 小時（`JWT_EXPIRE_MINUTES=480`），失效後使用者已被導回登入頁。

**前端統一入口**  
`frontend/src/utils/imageUrl.js` → `secureImgUrl(url)`

此函式是所有圖片 URL 轉換的唯一位置。接受：
- 相對路徑：`"uploads/uuid.jpg"`（來自 API 回應）
- 舊格式完整 URL：`"https://backend/uploads/uuid.jpg"`（向後相容）

輸出：`"https://backend/api/v1/uploads/uuid.jpg?token=xxx"`

**呼叫位置**（已統一，不應在其他地方出現 `/uploads/` 字串）
- `frontend/src/stores/expenseStore.js` → `mapExpense()`、`uploadImage()`、`replaceImage()`
- `frontend/src/components/ExpenseTable.vue` → `normalizeImageUrls()`（補件快取）
- `frontend/src/components/AuditModal.vue` → 子圖片顯示
- `frontend/src/components/BatchGroupModal.vue` → `imgUrl` alias
- `frontend/src/components/WaitingReturnModal.vue` → `imgUrl` alias

**路徑安全驗證**  
`routers/files.py` 用 regex 限制 filename 只能是 UUID 格式 + 白名單副檔名，
防止路徑穿越（`../../etc/passwd`）。

**未來換 GCS / S3 的擴充點**  
只需改 `routers/files.py` 的 `serve_upload()` 函式本體，
從 `FileResponse(path)` 換成從雲端讀取 blob，前端完全不動。

---

## 2. 管理員帳號建立開關

### 決策：`ENABLE_REGISTER` 環境變數，預設關閉

**改動時間**：2026-06-08

**背景**  
`/auth/register` 端點原本完全開放（無認證守衛），任何人可建立管理員帳號。

**現行設計**  
`core/config.py` → `enable_register: bool = False`  
`routers/auth.py` → 端點最頂端檢查：若 `False` 則回 403

**操作流程**
1. 全新部署時：在 `.env` 設 `ENABLE_REGISTER=true`，重啟，建帳號
2. 建完立即改回 `false`，重啟
3. 後續新增帳號同樣流程，或由現有管理員透過 API 操作

**為什麼不加 `Depends(get_current_user)`**  
雞生蛋問題：沒有第一個帳號就無法登入，無法登入就無法建立第一個帳號。

---

## 3. 容器化部署架構

### 決策：Docker Compose + Named Volume

**改動時間**：2026-06-08

**docker-compose.yml 服務結構**

```
backend  ← 從 Dockerfile 建立，掛載 uploads_data volume
  ↓ depends_on (healthy)
db       ← postgres:16-alpine，掛載 postgres_data volume
```

**為什麼用 named volume 而不是 bind mount**  
Named volume 在不同 OS（Windows/Linux/GCP VM）行為一致，
bind mount 在 Windows Docker Desktop 有路徑格式差異問題。

**容器內圖片路徑**  
`Dockerfile` 的 `WORKDIR /app`，加上 `.env` 的 `STORAGE_PATH=./uploads`，
實際解析為 `/app/uploads`，與 `volumes: uploads_data:/app/uploads` 掛載點一致。

**部署指令（改完程式碼後）**
```bash
git pull origin main
docker compose up --build -d
docker compose logs backend --tail=20
```

**GCP VM 部署補充**  
在 Compute Engine 上 `docker compose` 行為與本機完全相同，
volume 資料存在 VM 的 Persistent Disk 上，重啟不消失。
若日後遷移至 Cloud Run，需將 `serve_upload()` 改讀 GCS（見第 1 節）。

---

## 4. 檔案路徑一致性

**問題根源（已了解，非 bug，是注意事項）**  
- `liff_service.save_uploaded_file()` 使用 `Path(settings.storage_path) / filename`
- `Dockerfile WORKDIR /app` + `STORAGE_PATH=./uploads` → 實際為 `/app/uploads`
- Docker volume 掛載到 `/app/uploads`，三者對齊 ✅

**容易踩坑的情境**  
若在 Docker 外直接執行 `uvicorn main:app`（不透過 compose），
`STORAGE_PATH=./uploads` 解析為相對於執行命令的 CWD，
須確保 CWD 是專案根目錄。

---

## 5. 尚未處理的已知問題（優先度排序）

| 優先度 | 問題 | 說明 |
|--------|------|------|
| 高 | LIFF API 無 LINE ID Token 驗證 | `X-Line-User-Id` header 可偽造，任何人可假冒他人提交報帳 |
| 高 | `/auth/register` 已加開關，但無速率限制 | 登入端點可暴力破解，尚未加 slowapi |
| 中 | `liff_service.save_uploaded_file` 無檔案大小檢查 | 可上傳任意大小檔案耗盡磁碟 |
| 中 | 背景任務 OCR 無 timeout | Gemini API 掛起時任務永久等待 |
| 低 | `/health` 端點公開揭露排程設定 | 無認證，洩漏內部架構資訊 |
