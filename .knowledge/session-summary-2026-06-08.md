# AcctAssist 安全強化與架構重構 — 完整紀錄

**日期**：2026-06-08  
**性質**：安全修復 + 架構重構  
**總覽**：本次 session 針對安全審查報告進行修復，同時完成四組架構重構，並建立完整的部署基礎。

---

## 一、已修復的安全漏洞

### 1.1 `/auth/register` 端點完全開放（Critical）

**問題**：`POST /api/v1/auth/register` 無任何認證守衛，任何人可建立管理員帳號。

**修復**：加上 `ENABLE_REGISTER` 環境變數開關，預設關閉。

**涉及檔案**：
- `core/config.py` — 新增 `enable_register: bool = False`
- `routers/auth.py` — 端點進入時若 `False` 直接回 403
- `.env.example` — 新增說明

**操作流程**：
```
全新部署 → .env 設 ENABLE_REGISTER=true → 重啟 → 建帳號 → 立即改回 false → 重啟
```

---

### 1.2 `/uploads` 目錄無認證公開（High）

**問題**：`StaticFiles` 把整個 uploads/ 掛載為公開靜態資源，任何人知道 URL 即可讀取發票圖片。

**修復**：
- 移除 `main.py` 的 `StaticFiles` 掛載
- 新增 `routers/files.py`：`GET /api/v1/uploads/{filename}` 需要 JWT
- 新增 `frontend/src/utils/imageUrl.js`：`secureImgUrl(url)` 統一所有圖片 URL 轉換

**認證方式**（二擇一）：
```
Authorization: Bearer <token>    ← fetch / axios 呼叫
?token=<token>                   ← <img :src> 直接嵌入（瀏覽器 img 標籤不能帶 header）
```

**`secureImgUrl` 邏輯**（`frontend/src/utils/imageUrl.js`）：
```javascript
// 取路徑最後一個片段作為檔名，避免路徑格式差異造成雙重 uploads/
const filename = url.replace(/\\/g, '/').split('/').pop()
return `${API_BASE_URL}/api/v1/uploads/${filename}?token=${token}`
```

**已知 Bug（已修復）**：早期版本用 regex 剝前綴，在某些路徑格式下產生 `/api/v1/uploads/uploads/uuid.jpg`（雙重 uploads/），改用 `.split('/').pop()` 後解決。

**前端改動位置**（所有圖片 URL 必須經過 `secureImgUrl`）：
- `stores/expenseStore.js` → `mapExpense()`、`uploadImage()`、`replaceImage()`
- `components/ExpenseTable.vue` → `normalizeImageUrls()`
- `components/AuditModal.vue` → 子圖片顯示
- `components/BatchGroupModal.vue` → `imgUrl` alias
- `components/WaitingReturnModal.vue` → `imgUrl` alias

---

### 1.3 Host Header Injection / XSS（Medium）

**問題**：`main.py` 的兩個 LIFF 路由直接把未驗證的 `x-forwarded-host` header 注入 HTML JavaScript 變數，攻擊者可偽造惡意字串觸發 XSS。

**修復**：新增 `_get_base_url(request)` 函式，用 regex 白名單驗證 host 格式：
```python
_SAFE_HOST_RE = re.compile(r"^[a-zA-Z0-9.\-]+(:[0-9]{1,5})?$")
```
不合法的 `x-forwarded-host` 自動 fallback 到 TCP 層的 `Host` header。

---

## 二、架構重構

### 2.1 統一圖片儲存入口（`services/storage_service.py`）

**問題**：原本三處各自實作儲存邏輯，行為不一致（liff_service 無大小檢查、expenses.py 硬編碼路徑）。

**新架構**：所有上傳統一呼叫 `await save_image(file: UploadFile) -> str`

功能：
- MIME 類型驗證（`image/*` + `application/pdf`）
- 副檔名白名單：jpg/jpeg/png/gif/webp/bmp/tiff/tif/pdf
- 大小上限：`settings.max_upload_bytes`（預設 10MB）
- 路徑：`settings.storage_path`（不硬編碼）
- 回傳：`"uploads/{uuid}.ext"`（統一格式）

**回傳路徑設計原則**：永遠以 `uploads/` 開頭的相對路徑，讓前端的 `secureImgUrl` 可以一致處理。

**async 連鎖**：`save_image` 是 async → `liff_service.save_uploaded_file` 改為 async → `liff_service.add_image` 改為 async → `routers/liff.py:upload_image` 改為 async。

---

### 2.2 業務常數集中（`core/constants.py`）

**問題**：`VOUCHER_CATEGORY_ZH`、`STATUS_ZH`、`EXPENSE_CATEGORY_ZH`、`CSV_HEADERS`、`TAX_REPORT_HEADERS` 定義在 `routers/expenses.py`，業務常數放在 Router 層。

**修復**：全部移至 `core/constants.py`，`expenses.py` 改為 import。

---

### 2.3 統一 API 回應格式（`core/response.py`）

**問題**：全專案 35 個端點各自手動拼裝 `{"status": "success", "data": ..., "message": ...}`。

**修復**：新增 `core/response.py`：
```python
def ok(data=None, message="ok") -> dict:
    return {"status": "success", "data": data, "message": message}
```
5 個 router 檔案全部改用 `ok()`。

**設計原則**：
- 成功回應用 `ok()`
- 錯誤回應用 FastAPI `HTTPException`（不提供 `fail()` 避免混用格式）
- `StreamingResponse`（CSV 匯出）不走此格式

---

## 三、多格式檔案支援

**支援格式**：JPEG、PNG、GIF、WebP、BMP、TIFF、PDF

| 層級 | 改動 |
|------|------|
| `storage_service.py` | MIME 擴充至 `image/*` + `application/pdf`，副檔名白名單新增 bmp/tiff/pdf |
| `routers/files.py` | regex 擴充，`media_type` 改為依副檔名動態決定（不再固定 `image/jpeg`） |
| `routers/liff.py` | MIME 檢查允許 `application/pdf` |
| `utils/imageUrl.js` | 新增 `isViewableImage(url)` 和 `getFileType(url)` |
| 4 個前端元件 | PDF 改顯示 📄 圖示 + 連結，而非用 `<img>` |

**瀏覽器可直接顯示的格式**（`_IMG_EXTS`）：jpg/jpeg/png/gif/webp/bmp  
**PDF 顯示方式**：表格縮圖顯示「PDF」文字連結；AuditModal 顯示 📄 圖示 + 新分頁連結

---

## 四、容器化部署

### docker-compose.yml 結構
```yaml
services:
  backend:
    build: .
    volumes:
      - uploads_data:/app/uploads    # 圖片持久化
    env_file: .env
    depends_on: { db: { condition: service_healthy } }
    command: sh -c "alembic upgrade head && uvicorn main:app ..."

  db:
    image: postgres:16-alpine
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
  uploads_data:
```

### 路徑一致性
```
Dockerfile WORKDIR /app
STORAGE_PATH=./uploads（.env）→ 解析為 /app/uploads
docker volume 掛載到 /app/uploads
三者一致，重啟不丟失圖片
```

### 程式碼更新後的部署指令
```bash
git pull origin main
docker compose up --build -d
docker compose logs backend --tail=20
```

---

## 五、設計決策快查表

| 決策 | 原因 |
|------|------|
| `ENABLE_REGISTER=false` 預設關閉 | 防止任何人建立管理員帳號；雞生蛋問題解法 |
| JWT 用 query param 傳給圖片端點 | `<img>` 標籤不支援 Authorization header |
| `secureImgUrl` 用 `.split('/').pop()` 取檔名 | 相容所有路徑格式，避免 regex 邊界情況造成雙重 uploads/ |
| `ok()` 不提供 `fail()` | 避免 JSON 錯誤格式與 HTTPException 混用 |
| Docker named volume（不用 bind mount） | 跨 OS 行為一致，Windows Docker Desktop 無路徑問題 |
| 圖片回傳路徑固定以 `uploads/` 開頭 | 讓 `secureImgUrl` 可以一致提取檔名 |
| PDF 在前端不用 `<iframe>` 而用連結 | `<iframe>` 行為跨瀏覽器不一致，連結最穩定 |

---

## 六、尚未處理的已知問題（優先度排序）

| 優先度 | 問題 | 位置 |
|--------|------|------|
| 高 | LIFF API 無 LINE ID Token 驗證，`X-Line-User-Id` header 可偽造 | `routers/liff.py` |
| 高 | 登入端點無速率限制，可暴力破解 | `routers/auth.py` |
| 中 | 背景任務 OCR 無 timeout，Gemini API 掛起時任務永久等待 | `services/liff_service.py:process_session_background` |
| 中 | `/health` 端點公開揭露排程設定，無需認證 | `main.py` |
| 低 | 員工名冊 `bank_account` 以明文儲存於 DB | `models/staff_roster.py` |

---

## 七、相關知識文件索引（`.knowledge/`）

| 文件 | 內容 |
|------|------|
| `architecture-decisions.md` | 整體架構設計決策（圖片存取、部署、路徑） |
| `fix-group-a-host-header.md` | Host Header XSS 修復詳細說明與驗證腳本 |
| `fix-group-b-storage-service.md` | 儲存服務統一設計，async 連鎖說明 |
| `fix-group-c-constants.md` | 業務常數集中原因與擴充注意事項 |
| `fix-group-d-response.md` | API 回應格式統一，未來加欄位方式 |
| `session-summary-2026-06-08.md` | 本文件（總覽） |
