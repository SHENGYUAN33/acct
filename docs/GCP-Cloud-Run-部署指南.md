# AcctAssist — Google Cloud Run 上架完整操作指南

> 本指南依據目前專案實際程式碼與架構撰寫，目標：將 AcctAssist 從「Compute Engine VM + docker-compose + nginx」遷移到 **Cloud Run（無伺服器）** 架構。
>
> **已與你確認的四項決策：**
> 1. 檔案儲存 → 改用 **Google Cloud Storage（GCS）SDK**（前端圖片走後端代理）
> 2. 資料庫 → 建立 **Cloud SQL for PostgreSQL 16**
> 3. 前端 Dashboard → **Firebase Hosting**（前後端分離，需設定 CORS）
> 4. 排程功能 → **移除**「每日排程批次（ENABLE_SCHEDULED_BATCH）」與「60 秒自動切割（ENABLE_AUTO_SPLIT）」

---

## 目錄

- [0. 為什麼不能直接上 Cloud Run（架構差異）](#0-架構差異)
- [1. 目標架構總覽](#1-目標架構)
- [2. 前置準備與變數表](#2-前置準備)
- [Part A — 上架前必要的程式碼調整](#part-a)
- [Part B — GCP 基礎設施建置（一次性）](#part-b)
- [Part C — 建置映像與資料庫遷移](#part-c)
- [Part D — 部署後端到 Cloud Run](#part-d)
- [Part E — 部署前端到 Firebase Hosting](#part-e)
- [Part F — 串接 LINE / LIFF](#part-f)
- [Part G — 端到端驗證（情境 A/B/C）](#part-g)
- [Part H — CI/CD（可選）](#part-h)
- [Part I — 維運：監控、回滾、成本](#part-i)
- [附錄：環境變數對照表 / 疑難排解](#附錄)

---

<a name="0-架構差異"></a>
## 0. 為什麼不能直接上 Cloud Run（架構差異）

你目前的 `deploy-gcp.yml` / `docker-compose.prod.yml` / `nginx/nginx.conf` 是 **VM 架構**。Cloud Run 是無狀態容器平台，以下三點若不先處理，上線後一定會出問題：

| # | VM 現況 | Cloud Run 限制 | 後果（若不改） | 對策 |
|---|---------|---------------|--------------|------|
| 1 | 圖片存本機 `uploads/`（`/data/uploads` volume） | 容器磁碟是**臨時**的，重啟即清空、多實例不共享、可縮容到 0 | 重新整理 Dashboard 圖片 404、OCR 找不到檔 | **Part A1** 改存 GCS |
| 2 | Postgres 跑在容器內（volume） | 不可在 Cloud Run 跑有狀態 DB | 資料遺失 | **Part B3** 改用 Cloud SQL |
| 3 | APScheduler / auto-split 在記憶體內，需常駐單一 Worker | 縮容到 0 時沒有實例可跑排程；多實例會重複觸發 | 排程不觸發或重複處理 | **Part A2** 移除這兩功能 |

此外還有四個 Cloud Run 專屬細節，本指南都會處理：

- **背景 OCR**：`webhook` / `liff` 用 `BackgroundTasks` 在回應後才跑 OCR。Cloud Run 預設會在回應後「凍結 CPU」，背景任務會卡住 → 必須加 `--no-cpu-throttling`。
- **PORT**：Cloud Run 以環境變數 `PORT`（預設 8080）告知容器監聽埠，現有 `CMD` 寫死 `--port 8000` → 需改讀 `$PORT`。
- **Migration**：現在靠 docker-compose entrypoint 跑 `alembic upgrade head`；Cloud Run 沒有這個 entrypoint → 需另外執行（Part C2）。
- **LIFF / Webhook URL**：網址會變成 Cloud Run 網域 → 需回 LINE 後台更新（Part F）。

---

<a name="1-目標架構"></a>
## 1. 目標架構總覽

```
                         ┌─────────────────────────┐
   LINE 平台 ───webhook──▶│                         │
   (Messaging API)        │   Cloud Run             │──unix socket──▶ Cloud SQL
                          │   acctassist-backend    │                (PostgreSQL 16)
   使用者手機 LIFF ───────▶│   (FastAPI / 容器)       │
                          │                         │──SDK──────────▶ Cloud Storage
   Dashboard 瀏覽器 ──API─▶│                         │                (gs://...-uploads)
        │                 └─────────────────────────┘
        │                            ▲
        │ 靜態檔                      │ 每日 03:00 觸發清理
        ▼                            │
  Firebase Hosting            Cloud Scheduler
  (Vue 3 SPA)                 (取代原 APScheduler)

  機敏設定：Secret Manager（JWT / LINE / Gemini / DB 連線）
  映像倉庫：Artifact Registry
```

**元件清單：**

| 元件 | GCP 服務 | 用途 |
|------|---------|------|
| 後端 API | Cloud Run | FastAPI 容器（webhook、API、LIFF 頁面） |
| 資料庫 | Cloud SQL (PostgreSQL 16) | 取代容器內 Postgres |
| 圖片儲存 | Cloud Storage | 取代本機 `uploads/` |
| 前端 | Firebase Hosting | Vue 3 Dashboard 靜態檔 |
| 排程 | Cloud Scheduler | 取代 APScheduler（LIFF 清理） |
| 機敏設定 | Secret Manager | 金鑰集中管理 |
| 映像 | Artifact Registry | Docker image |

---

<a name="2-前置準備"></a>
## 2. 前置準備與變數表

### 2.1 你需要先具備

- 一個 **GCP 專案** 且已**啟用計費（Billing）**。
- 對該專案有 **Owner** 或（Editor + 各服務 Admin）權限。
- LINE 既有的 Channel secret / access token、Gemini API key（沿用現有）。
- 建議：直接用 **Google Cloud Shell**（瀏覽器內，已內建 `gcloud`/`gsutil`/`docker`），可避免 Windows PowerShell 換行與工具安裝問題。本指南所有 `gcloud` 指令皆以 **bash** 撰寫（用 `\` 換行）。
  - 若堅持用本機 PowerShell：請把指令寫成**單行**，或把每行尾端的 `\` 換成反引號 `` ` ``。

### 2.2 本機（若要本機建置 / 部署前端）

- `gcloud` CLI（或用 Cloud Shell）
- `node` 20 + `npm`（前端建置）
- `firebase-tools`（前端部署）：`npm i -g firebase-tools`

### 2.3 變數表（**先填好，後面整份指南都會用到**）

> 建議在 Cloud Shell 開一個檔案記下這些值，或直接 `export` 成環境變數。

```bash
# ── 請依實際情況修改這一段，其餘指令直接複製即可 ──
export PROJECT_ID="your-gcp-project-id"          # GCP 專案 ID
export REGION="asia-east1"                        # 台灣，沿用你現有設定
export AR_REPO="acctassist"                        # Artifact Registry 倉庫名
export SQL_INSTANCE="acctassist-db"                # Cloud SQL 實例名
export DB_NAME="acctassist"                        # 資料庫名
export DB_USER="acctassist"                        # 資料庫帳號
export GCS_BUCKET="acctassist-uploads-${PROJECT_ID}"  # GCS bucket（全球唯一）
export RUN_SA="acctassist-run"                      # Cloud Run 執行用服務帳號名
export SERVICE="acctassist-backend"                # Cloud Run 服務名

gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"
```

---

<a name="part-a"></a>
# Part A — 上架前必要的程式碼調整

> ⚠️ **這是上線的前提**。Part B 之後的基礎設施步驟，都假設這些程式碼調整已完成。
> 這些調整我可以直接幫你實作（你說一聲即可）；以下說明「改什麼、為什麼、怎麼改」。

每項調整完成後，請務必在本機跑一次測試確保沒破壞既有邏輯：

```bash
pytest tests/ --ignore=tests/postgres/ -q
cd frontend && npm test && cd ..
```

---

## A1. 圖片儲存改用 Cloud Storage（GCS）

**目標**：在不改變 DB 既有 `image_url` 格式（維持 `uploads/{uuid}.ext`）的前提下，把「寫入 / 讀取 / 刪除」從本機磁碟改成 GCS。這樣**舊資料相容**，前端不必改。

### 影響檔案

| 檔案 | 現況 | 調整 |
|------|------|------|
| `requirements.txt` | 無 GCS 套件 | 新增 `google-cloud-storage>=2.16.0` |
| `core/config.py` | 只有 `storage_path` | 新增 `storage_backend`（local/gcs）與 `gcs_bucket` |
| `services/storage_service.py` | `dest.write_bytes()` 寫本機 | 改呼叫統一儲存層 |
| `services/line_service.py` | `download_image()` 寫本機 | 維持原狀（無 live caller — 聊天上傳圖片流程已改走 LIFF / `storage_service`，不在 Cloud Run 請求路徑上） |
| `services/ocr_service.py` | `Image.open(本機路徑)` | 改成從儲存層取 bytes 再 `Image.open(BytesIO)` |
| `routers/files.py` | `FileResponse(本機路徑)` | 改成從 GCS 取 bytes 用 `Response`/`StreamingResponse` 回傳 |
| `services/liff_service.py` | 清理時刪本機檔 | 改呼叫儲存層刪除 |

### 設計：新增統一儲存層 `services/object_storage.py`（建議）

集中處理 local / GCS 兩種後端，其他模組只呼叫這四個函式：`put_bytes()`、`get_bytes()`、`delete()`、`exists()`。`STORAGE_BACKEND=local` 時走本機（本機開發不變），`=gcs` 時走 GCS（Cloud Run）。

參考實作（正式碼我會幫你補齊與測試）：

```python
# services/object_storage.py（示意）
"""統一物件儲存層：依 STORAGE_BACKEND 切換本機磁碟或 GCS。

DB 內 image_url 一律維持相對鍵格式「uploads/{uuid}.ext」，
本層負責把該鍵對應到本機路徑或 GCS object。
"""
import logging
from io import BytesIO
from pathlib import Path

from core.config import settings

logger = logging.getLogger(__name__)
_gcs_client = None  # 延遲初始化，避免本機開發載入 GCS SDK


def _key(rel_path: str) -> str:
    """正規化為 uploads/xxx 形式的物件鍵。"""
    return rel_path.replace("\\", "/").lstrip("/")


def _bucket():
    global _gcs_client
    if _gcs_client is None:
        from google.cloud import storage  # 僅在 gcs 模式才 import
        _gcs_client = storage.Client()
    return _gcs_client.bucket(settings.gcs_bucket)


def put_bytes(rel_path: str, data: bytes, content_type: str) -> None:
    if settings.storage_backend == "gcs":
        blob = _bucket().blob(_key(rel_path))
        blob.upload_from_string(data, content_type=content_type)
    else:
        dest = Path(settings.storage_path) / Path(rel_path).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)


def get_bytes(rel_path: str) -> bytes | None:
    if settings.storage_backend == "gcs":
        blob = _bucket().blob(_key(rel_path))
        return blob.download_as_bytes() if blob.exists() else None
    p = Path(settings.storage_path) / Path(rel_path).name
    return p.read_bytes() if p.is_file() else None


def delete(rel_path: str) -> None:
    if settings.storage_backend == "gcs":
        blob = _bucket().blob(_key(rel_path))
        if blob.exists():
            blob.delete()
    else:
        p = Path(settings.storage_path) / Path(rel_path).name
        p.unlink(missing_ok=True)
```

`config.py` 新增：

```python
    # Storage backend：local（本機磁碟，開發用）/ gcs（Cloud Run 用）
    storage_backend: str = "local"
    gcs_bucket: str = ""
```

> **重點**：`ocr_service.classify_and_extract()` 目前直接 `Image.open(本機路徑)`。改成：先用 `object_storage.get_bytes(rel_path)` 取得 bytes，再 `Image.open(BytesIO(data))`。`files.py` 同理改成 `get_bytes()` → `Response(content=..., media_type=...)`。

> **既有正式資料搬遷**（若 VM 上已有圖片要保留）：
> ```bash
> gsutil -m cp -r /data/uploads/* gs://${GCS_BUCKET}/uploads/
> ```
> 物件鍵需保持 `uploads/` 前綴，才能與 DB 既有 `image_url` 對上。

---

## A2. 移除 auto-split 與 scheduled-batch 兩功能

**為什麼**：兩者都依賴「記憶體內常駐單一 Worker」，與 Cloud Run 的無狀態 / 多實例 / 縮容到 0 根本衝突（見 `.knowledge/postmortem-log.md #013`）。移除後，App 變成**完全無狀態**，可安全水平擴展。

> LINE 報帳的送出，移除後仍由使用者按 **「確認送出」**（`confirm_submit` postback）即時觸發 OCR 與建單，這是原本就有的主路徑，使用體驗不受影響。LIFF 送出路徑也不受影響。

### 要刪除 / 調整

| 檔案 | 動作 |
|------|------|
| `services/auto_split_service.py` | 刪除 |
| `services/auto_split_timer.py` | 刪除 |
| `services/scheduler.py`（APScheduler） | 刪除 |
| `services/scheduled_batch_service.py` | 視情況刪除（見下方「process-pending」說明） |
| `main.py` | 移除 `start_scheduler` / `stop_scheduler` / `get_scheduled_jobs` 相關啟動碼；`/health` 移除 `scheduled_jobs` 欄位；移除讀取 `SystemSetting` 排程設定的區塊 |
| `routers/admin.py` | 移除 `/scheduler-config` 相關端點；`/process-pending` 見下 |
| `routers/webhook.py` | 移除呼叫 auto-split timer 的程式碼（保留 `confirm_submit` 即時處理） |
| `core/config.py` / `.env.example` | 移除 `enable_auto_split`、`auto_split_debounce_seconds`、`enable_scheduled_batch`、`scheduled_batch_times`、`scheduled_batch_timezone` |
| `requirements.txt` | 移除 `apscheduler` |
| 前端 | 移除「排程設定」按鈕（`VITE_ENABLE_SCHEDULER_CONFIG`）與相關 UI/呼叫 |
| `tests/` | 移除 / 調整 `test_auto_split*`、`test_auto_split_flow` 等 |

### ⚠️ 一個需你決定的小分叉：`/process-pending`（「立即處理 Pending」按鈕）

`routers/admin.py` 的 `/process-pending` 會呼叫 `run_scheduled_batch`（與排程共用同一個批次處理函式）。正式環境 CI 目前已把這顆按鈕關閉（`VITE_ENABLE_PROCESS_PENDING=false`）。**兩個選項：**

- **(建議) 一併移除**：連同 `scheduled_batch_service.py`、`/process-pending` 一起刪掉，最乾淨。
- **保留手動批次**：保留 `scheduled_batch_service.run_scheduled_batch` 與 `/process-pending` 端點，只移除「定時觸發（cron）」。這樣管理員仍可手動一次處理所有 pending 圖片。

> 我預設採「一併移除」。若你要保留手動批次，告訴我即可。

---

## A3. 把 03:00 LIFF 清理改用 Cloud Scheduler

原本「每日凌晨 3 點清理過期 LIFF session 與圖片」是掛在 APScheduler 裡（`services/scheduler.py`）。移除排程器後，需用 **Cloud Scheduler** 定時呼叫一個受保護端點來取代。

### 新增受保護端點（建議放 `routers/admin.py`）

```python
# 以共享密鑰標頭保護（Cloud Scheduler 會帶這個 header）
@router.post("/cleanup-liff", include_in_schema=False)
def cleanup_liff_endpoint(
    x_cleanup_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    if not settings.cleanup_token or x_cleanup_token != settings.cleanup_token:
        raise HTTPException(status_code=401, detail="unauthorized")
    from services.liff_service import cleanup_expired_sessions
    cleanup_expired_sessions(db)
    return ok(data=None, message="cleanup done")
```

`config.py` 新增 `cleanup_token: str = ""`（值放 Secret Manager，見 Part B5、Part D3 設定 Cloud Scheduler）。

---

## A4. Dockerfile 改讀 `$PORT`

Cloud Run 用環境變數 `PORT`（預設 8080）。把 `Dockerfile` 最後一行改成 shell 形式以便展開變數：

```dockerfile
# 變更前：
# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

# 變更後：
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
```

> 保留 `--workers 1`：Cloud Run 以「實例數」做水平擴展，單實例內由 async 處理併發即可。移除排程後多實例安全。

---

## A5. CORS 設定（前後端分離）

前端在 Firebase Hosting（不同網域），後端必須允許該來源。`main.py` 已有邏輯：`APP_ENV != development` 時用 `settings.cors_origins`。因此 Cloud Run 上：

- `APP_ENV=production`
- `CORS_ORIGINS=["https://<你的-firebase-app>.web.app","https://<你的-firebase-app>.firebaseapp.com"]`（Part E 取得網址後回填）

> 後端是用 JWT（Authorization header）+ 圖片 `?token=` 查詢字串，圖片 `<img>` 跨網域不受 CORS 限制；一般 API 才需要 CORS 白名單。

---

## A6. Rich Menu 設定移出 startup

`main.py` 啟動時呼叫 `line_service.setup_rich_menu()`。Cloud Run 縮容到 0、每次冷啟動都會重打 LINE API，可能造成重複建立或觸發 LINE 速率限制。

**建議**：從 `on_startup` 移除這段，改為**部署後手動執行一次**（已有 `POST /api/v1/admin/setup-rich-menu` 端點與 `scripts/setup_rich_menu.py`，見 Part F3）。

---

<a name="part-b"></a>
# Part B — GCP 基礎設施建置（一次性）

> 以下在 **Cloud Shell** 執行，並已 `export` 好 [2.3 變數表](#2-前置準備)。

## B1. 啟用必要 API

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  storage.googleapis.com
```

## B2. 建立 Artifact Registry（Docker 映像倉庫）

```bash
gcloud artifacts repositories create "$AR_REPO" \
  --repository-format=docker \
  --location="$REGION" \
  --description="AcctAssist container images"
```

## B3. 建立 Cloud SQL（PostgreSQL 16）

```bash
# 1) 建立實例（tier 二選一）
#    最省錢（開發/小量）：--tier=db-f1-micro
#    正式建議（1 vCPU/3.75GB）：--tier=db-custom-1-3840
gcloud sql instances create "$SQL_INSTANCE" \
  --database-version=POSTGRES_16 \
  --tier=db-custom-1-3840 \
  --region="$REGION" \
  --storage-size=10GB \
  --storage-auto-increase \
  --availability-type=zonal          # 正式環境要高可用可改 regional（成本翻倍）

# 2) 設定 postgres 超級使用者密碼（自行替換）
gcloud sql users set-password postgres \
  --instance="$SQL_INSTANCE" --password='REPLACE_WITH_STRONG_PW'

# 3) 建立應用程式資料庫
gcloud sql databases create "$DB_NAME" --instance="$SQL_INSTANCE"

# 4) 建立應用程式帳號（自行替換密碼，後面 DATABASE_URL 會用到）
gcloud sql users create "$DB_USER" \
  --instance="$SQL_INSTANCE" --password='REPLACE_WITH_APP_DB_PW'

# 5) 取得「連線名稱」（格式 PROJECT:REGION:INSTANCE），記下來
export SQL_CONN="$(gcloud sql instances describe "$SQL_INSTANCE" --format='value(connectionName)')"
echo "$SQL_CONN"
```

**Cloud Run 用的 `DATABASE_URL`（unix socket 形式）：**

```
postgresql+psycopg2://DB_USER:APP_DB_PW@/DB_NAME?host=/cloudsql/SQL_CONN
```

例如：`postgresql+psycopg2://acctassist:****@/acctassist?host=/cloudsql/myproj:asia-east1:acctassist-db`

> 密碼若含特殊字元（`@ : / ?` 等）要做 URL-encode。此字串將放入 Secret（Part B5）。

## B4. 建立 GCS Bucket（圖片儲存）

```bash
gcloud storage buckets create "gs://${GCS_BUCKET}" \
  --location="$REGION" \
  --uniform-bucket-level-access            # 統一權限，不開公開讀取

# 建議：設定生命週期（例：物件 365 天後自動刪，可選）
# gcloud storage buckets update gs://${GCS_BUCKET} --lifecycle-file=lifecycle.json
```

> Bucket **保持私有**：圖片一律經後端 `files.py`（JWT 驗證）代理讀取，不對外公開。

## B5. 建立 Secret Manager 機敏設定

```bash
# 一個一個建立（值用 printf 從 stdin 餵入，避免留在 shell 歷史）
printf '%s' 'REPLACE_JWT_RANDOM_64HEX'  | gcloud secrets create JWT_SECRET --data-file=-
printf '%s' 'LINE_CHANNEL_SECRET_VALUE' | gcloud secrets create LINE_CHANNEL_SECRET --data-file=-
printf '%s' 'LINE_ACCESS_TOKEN_VALUE'   | gcloud secrets create LINE_CHANNEL_ACCESS_TOKEN --data-file=-
printf '%s' 'GEMINI_API_KEY_VALUE'      | gcloud secrets create GEMINI_API_KEY --data-file=-
printf '%s' 'CLEANUP_TOKEN_RANDOM'      | gcloud secrets create CLEANUP_TOKEN --data-file=-
printf '%s' 'postgresql+psycopg2://acctassist:APP_DB_PW@/acctassist?host=/cloudsql/'"$SQL_CONN" \
  | gcloud secrets create DATABASE_URL --data-file=-
```

> 產生強隨機 JWT_SECRET：`openssl rand -hex 32`

## B6. 建立 Cloud Run 執行用服務帳號與權限

```bash
# 1) 建立服務帳號
gcloud iam service-accounts create "$RUN_SA" \
  --display-name="AcctAssist Cloud Run runtime"

export RUN_SA_EMAIL="${RUN_SA}@${PROJECT_ID}.iam.gserviceaccount.com"

# 2) 連 Cloud SQL 的權限
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUN_SA_EMAIL}" \
  --role="roles/cloudsql.client"

# 3) 讀寫 GCS bucket 的權限（只授在這個 bucket 上）
gcloud storage buckets add-iam-policy-binding "gs://${GCS_BUCKET}" \
  --member="serviceAccount:${RUN_SA_EMAIL}" \
  --role="roles/storage.objectAdmin"

# 4) 讀取 Secret 的權限
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUN_SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor"
```

---

<a name="part-c"></a>
# Part C — 建置映像與資料庫遷移

## C1. 建置並推送後端映像

用 **Cloud Build**（不需本機 Docker，最簡單）：

```bash
export IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/backend:v1"

gcloud builds submit --tag "$IMAGE" .
```

> 確認專案根目錄有 `.dockerignore` 排除 `uploads/`、`.env*`、`frontend/node_modules`、`.git` 等，縮小映像並避免機敏外洩。

## C2. 執行資料庫遷移（Alembic）

Cloud Run 容器**不會**自動跑 migration，需在首次部署前先建好資料表。用 **Cloud SQL Auth Proxy** 在 Cloud Shell 跑最簡單：

```bash
# 1) 下載 proxy
curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.11.0/cloud-sql-proxy.linux.amd64
chmod +x cloud-sql-proxy

# 2) 背景啟動 proxy（本機 5432 → Cloud SQL）
./cloud-sql-proxy "$SQL_CONN" --port 5432 &

# 3) 安裝依賴並跑 migration（用 TCP 連線字串）
pip install -r requirements.txt
export DATABASE_URL="postgresql+psycopg2://${DB_USER}:APP_DB_PW@localhost:5432/${DB_NAME}"
alembic upgrade head

# 4) 完成後關閉 proxy
kill %1
```

> CI 自動化可改用 **Cloud Run Job**：以同一映像、entrypoint 設為 `alembic upgrade head`、掛上 `--set-cloudsql-instances`，每次部署前 `gcloud run jobs execute`。Part H 有範例。

## C3.（部署後）建立第一個管理員帳號

第一次部署完成（Part D）後，因為還沒有任何 Dashboard 帳號，需臨時開啟註冊：

1. Part D 部署時，env 暫時設 `ENABLE_REGISTER=true`。
2. 呼叫一次（把 URL 換成你的 Cloud Run 網址）：
   ```bash
   curl -X POST "https://<CLOUD_RUN_URL>/api/v1/auth/register" \
     -H "Content-Type: application/json" \
     -d '{"username":"admin","password":"YOUR_STRONG_PW","display_name":"管理員"}'
   ```
3. 建好後，把 env 改回 `ENABLE_REGISTER=false` 並重新部署（Part D 的 deploy 指令再跑一次即可）。

---

<a name="part-d"></a>
# Part D — 部署後端到 Cloud Run

## D1. 準備非機敏環境變數檔（`cloudrun.env.yaml`）

非機敏設定用 YAML 檔帶入，避免 `--set-env-vars` 遇到逗號（例如 `CORS_ORIGINS`、`DEPARTMENTS`）escape 問題。

```yaml
# cloudrun.env.yaml（放專案根目錄；機敏值不要寫這裡，走 Secret）
APP_ENV: "production"
APP_DEBUG: "false"
STORAGE_BACKEND: "gcs"
GCS_BUCKET: "acctassist-uploads-your-gcp-project-id"   # = $GCS_BUCKET
GEMINI_MODEL: "gemini-2.5-flash"
JWT_EXPIRE_MINUTES: "480"
ENABLE_LINE_PUSH_REJECT: "true"
ENABLE_USER_BINDING: "true"
ENABLE_ROSTER_BINDING: "false"
ENABLE_REGISTER: "true"          # 首次建帳號用，建完改 false 重新部署
LIFF_SUBMIT_MODE: "single"
OCR_MAX_CONCURRENT: "3"
OCR_MAX_RETRIES: "3"
KEY_FIELD_CONFIDENCE_THRESHOLD: "0.8"
LIFF_SESSION_TTL_MINUTES: "30"
ORPHAN_WINDOW_MINUTES: "10"
EXPENSE_EXPORT_LIMIT: "10000"
COMPANY_TAX_ID: ""
# CORS_ORIGINS 先留單一佔位，Part E 取得 Firebase 網址後回填再重部署：
CORS_ORIGINS: '["https://REPLACE.web.app"]'
# DEPARTMENTS / ACCOUNT_ROLES 若沿用 config.py 預設可省略；要自訂再加：
# DEPARTMENTS: '["製片組_一般", ... ]'
```

> 已移除排程相關變數（`ENABLE_AUTO_SPLIT`、`ENABLE_SCHEDULED_BATCH` 等），對應 Part A2。

## D2. 部署指令

```bash
gcloud run deploy "$SERVICE" \
  --image="$IMAGE" \
  --region="$REGION" \
  --service-account="$RUN_SA_EMAIL" \
  --add-cloudsql-instances="$SQL_CONN" \
  --env-vars-file=cloudrun.env.yaml \
  --set-secrets="DATABASE_URL=DATABASE_URL:latest,JWT_SECRET=JWT_SECRET:latest,LINE_CHANNEL_SECRET=LINE_CHANNEL_SECRET:latest,LINE_CHANNEL_ACCESS_TOKEN=LINE_CHANNEL_ACCESS_TOKEN:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest,CLEANUP_TOKEN=CLEANUP_TOKEN:latest" \
  --no-cpu-throttling \
  --cpu=1 --memory=1Gi \
  --min-instances=0 --max-instances=4 \
  --concurrency=20 \
  --timeout=300 \
  --allow-unauthenticated
```

**關鍵參數說明：**

| 參數 | 為什麼 |
|------|--------|
| `--add-cloudsql-instances` | 在容器內掛上 `/cloudsql/<conn>` socket，配合 `DATABASE_URL` 連 Cloud SQL |
| `--set-secrets` | 把 Secret Manager 的值注入成環境變數 |
| `--no-cpu-throttling` | **必要**：背景 OCR（`BackgroundTasks`）在回應後才跑，需 CPU 持續配置才能完成 |
| `--allow-unauthenticated` | webhook / LIFF / 前端皆從公網呼叫；真正的授權由 App 內 JWT + LINE 簽章把關 |
| `--min-instances=0` | 移除排程後可縮容到 0，省錢（可接受冷啟動可設 0；要低延遲設 1） |
| `--timeout=300` | OCR 可能較久，放寬請求逾時 |
| `--concurrency=20` | 單實例併發；OCR 吃資源，先保守 |

部署完成後記下服務網址：

```bash
export RUN_URL="$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')"
echo "$RUN_URL"
curl -s "$RUN_URL/health"     # 應回 {"status":"success",...}
```

## D3. 建立 Cloud Scheduler（取代 03:00 LIFF 清理）

```bash
gcloud scheduler jobs create http acctassist-liff-cleanup \
  --location="$REGION" \
  --schedule="0 3 * * *" \
  --time-zone="Asia/Taipei" \
  --uri="${RUN_URL}/api/v1/admin/cleanup-liff" \
  --http-method=POST \
  --headers="X-Cleanup-Token=REPLACE_WITH_CLEANUP_TOKEN_VALUE"
```

> `X-Cleanup-Token` 的值要與 Secret `CLEANUP_TOKEN` 相同（對應 Part A3 的端點驗證）。

---

<a name="part-e"></a>
# Part E — 部署前端到 Firebase Hosting

> 前端在本機（或 Cloud Shell）建置。Vite 設定為 `envDir: '../'`（讀**專案根目錄**的 `.env`）。

```bash
# 1) 安裝 Firebase CLI 並登入
npm i -g firebase-tools
firebase login          # 在本機瀏覽器完成授權（Cloud Shell 用 firebase login --no-localhost）

# 2) 在「專案根目錄」寫入前端建置變數（指向後端 Cloud Run 網址）
cat > .env << EOF
VITE_API_BASE_URL=${RUN_URL}
VITE_ENABLE_PROCESS_PENDING=false
VITE_ENABLE_SCHEDULER_CONFIG=false      # 已移除排程，關閉此按鈕
VITE_ENABLE_DUPLICATE_DETECTION=true
EOF

# 3) 建置前端
cd frontend
npm ci
npm run build           # 產出 frontend/dist

# 4) 初始化 Firebase Hosting（第一次才需要）
firebase init hosting
#   - 選擇/建立 Firebase 專案（建議用同一個 GCP 專案）
#   - Public directory 輸入：dist
#   - Configure as single-page app：Yes（重要，SPA 路由）
#   - 不要覆寫 dist/index.html

# 5) 部署
firebase deploy --only hosting
cd ..
```

部署完成會得到網址，例如 `https://your-app.web.app`。

### 回填後端 CORS（重要）

把 Firebase 網址填回 `cloudrun.env.yaml` 的 `CORS_ORIGINS`，重新部署後端：

```yaml
CORS_ORIGINS: '["https://your-app.web.app","https://your-app.firebaseapp.com"]'
```

```bash
gcloud run deploy "$SERVICE" --image="$IMAGE" --region="$REGION" \
  --env-vars-file=cloudrun.env.yaml \
  # ...（其餘參數同 D2，或直接重跑 D2 指令）
```

---

<a name="part-f"></a>
# Part F — 串接 LINE / LIFF

到 **LINE Developers Console**（你的 Messaging API channel）：

## F1. 更新 Webhook URL

- Webhook URL：`https://<RUN_URL>/webhook`
- 開啟「Use webhook」
- 按「Verify」應回 200

## F2. 更新 LIFF Endpoint URL

LIFF 頁面是由後端服務（`/liff-app`、`/liff-single`）。到 LINE Login channel 的 LIFF 設定，把各 LIFF app 的 Endpoint URL 改為：

- 批次模式：`https://<RUN_URL>/liff-app`
- 單筆模式：`https://<RUN_URL>/liff-single`

> `main.py` 會用 `x-forwarded-host` / `x-forwarded-proto`（Cloud Run 會帶）自動注入正確的 API base URL，不需改程式碼。

## F3. 設定一次 Rich Menu（對應 A6）

部署後執行一次（擇一）：

```bash
# 方式一：用受 JWT 保護的 admin 端點（先用管理員帳號登入取得 token）
TOKEN=$(curl -s -X POST "$RUN_URL/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"YOUR_PW"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["access_token"])')

curl -X POST "$RUN_URL/api/v1/admin/setup-rich-menu" -H "Authorization: Bearer $TOKEN"
```

---

<a name="part-g"></a>
# Part G — 端到端驗證（對照 CLAUDE.md 的情境）

| # | 驗證項目 | 預期 |
|---|---------|------|
| 1 | `GET $RUN_URL/health` | `status: success`、`db: ok` |
| 2 | Dashboard 登入（Firebase 網址） | 能登入、清單載入、**圖片能正常顯示**（驗證 GCS 代理） |
| 3 | 情境 A：LINE 首次使用者 Onboarding → 上傳發票 → 按「確認送出」 | 收到完成摘要（含 EXP-YYYYMM-NNNN），Dashboard 出現該筆、圖片可看 |
| 4 | OCR 欄位（金額/發票號等） | 有值 → PENDING；失敗 → NEEDS_MANUAL_REVIEW |
| 5 | 情境 B：Dashboard 退回 → LINE 收到退件通知 → 重新上傳 | 狀態變 SUPPLEMENTED |
| 6 | 情境 C：LINE 傳「查詢進度」 | 回最近 3 筆狀態 |
| 7 | LIFF 頁面（手機點 Rich Menu / LIFF） | 正常開啟、可上傳、送出後建單 |
| 8 | CSV 匯出 | 正常下載（含 BOM） |
| 9 | 隔日 03:00 後查 Cloud Scheduler 執行紀錄 | LIFF 清理 job 成功（200） |

**查日誌：**
```bash
gcloud run services logs read "$SERVICE" --region="$REGION" --limit=100
```

---

<a name="part-h"></a>
# Part H — CI/CD（可選：改寫現有 workflow）

你現有的 `.github/workflows/deploy-gcp.yml` 是 **VM/SSH 部署**，與 Cloud Run 不相容。可新增一個 Cloud Run 版（保留 test / integration-test 兩個 job，替換 build/deploy）。核心步驟：

```yaml
# 摘要（測試 job 沿用現有；以下為部署部分）
  deploy-cloudrun:
    needs: [test, integration-test]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}   # 或改用 Workload Identity Federation（更安全）
      - uses: google-github-actions/setup-gcloud@v2

      - name: Build & push image
        run: |
          IMAGE=${{ env.GCP_REGION }}-docker.pkg.dev/${{ secrets.GCP_PROJECT_ID }}/acctassist/backend:${{ github.sha }}
          gcloud builds submit --tag "$IMAGE" .
          echo "IMAGE=$IMAGE" >> $GITHUB_ENV

      - name: DB migrate (Cloud Run Job)
        run: |
          gcloud run jobs deploy acctassist-migrate \
            --image="$IMAGE" --region=${{ env.GCP_REGION }} \
            --set-cloudsql-instances=$SQL_CONN \
            --set-secrets=DATABASE_URL=DATABASE_URL:latest \
            --command="alembic" --args="upgrade,head" || true
          gcloud run jobs execute acctassist-migrate --region=${{ env.GCP_REGION }} --wait

      - name: Deploy Cloud Run
        run: |
          gcloud run deploy acctassist-backend \
            --image="$IMAGE" --region=${{ env.GCP_REGION }} \
            --env-vars-file=cloudrun.env.yaml \
            --set-secrets=... --no-cpu-throttling --allow-unauthenticated
```

> 前端可加一個 job：`npm ci && npm run build` 後 `firebase deploy`（用 `FIREBASE_TOKEN` 或服務帳號）。
> 建議改用 **Workload Identity Federation** 取代長期 `GCP_SA_KEY` 金鑰。

---

<a name="part-i"></a>
# Part I — 維運：監控、回滾、成本

## 回滾（Cloud Run 內建版本管理）

```bash
# 列出 revisions
gcloud run revisions list --service="$SERVICE" --region="$REGION"
# 把流量切回前一版
gcloud run services update-traffic "$SERVICE" --region="$REGION" --to-revisions=<上一版revision>=100
```

## 資料庫

- Cloud SQL 預設每日自動備份；可設 PITR（point-in-time recovery）。
- 變更 schema 一律走 Alembic（Cloud Run Job 或 proxy），勿手動改表。

## 監控 / 告警

- Cloud Run：在 Console 看 request 數、延遲、錯誤率、實例數。
- 建議建立 Uptime Check 打 `/health`，失敗時告警。
- Cloud Logging：可建 log-based metric 抓 `OCR 處理失敗` 等關鍵字。

## 成本（粗估，asia-east1）

| 項目 | 估算 |
|------|------|
| Cloud Run | 縮容到 0，依用量計費；小流量常為個位數美元/月 |
| Cloud SQL | `db-f1-micro` 約 USD 8–10/月；`db-custom-1-3840` 約 USD 45–55/月 |
| Cloud Storage | 數 GB 圖片約 < USD 1/月 |
| Firebase Hosting | 免費額度通常足夠 |
| Secret Manager / Scheduler | 免費額度內 |

> 最大變數是 Cloud SQL tier 與 `--min-instances`。要壓成本：DB 用 `db-f1-micro`、Cloud Run `--min-instances=0`。

---

<a name="附錄"></a>
# 附錄

## 附錄 A：環境變數對照表（.env → Cloud Run）

| 變數 | 來源 | 備註 |
|------|------|------|
| `DATABASE_URL` | Secret | unix socket 形式 |
| `JWT_SECRET` | Secret | `openssl rand -hex 32` |
| `LINE_CHANNEL_SECRET` | Secret | 沿用現有 |
| `LINE_CHANNEL_ACCESS_TOKEN` | Secret | 沿用現有 |
| `GEMINI_API_KEY` | Secret | 沿用現有 |
| `CLEANUP_TOKEN` | Secret | Cloud Scheduler 標頭驗證（A3 新增） |
| `APP_ENV` | env file | 設 `production`（啟用 CORS 白名單） |
| `STORAGE_BACKEND` | env file | 設 `gcs`（A1 新增） |
| `GCS_BUCKET` | env file | bucket 名（A1 新增） |
| `CORS_ORIGINS` | env file | Firebase 網址（JSON array） |
| `GEMINI_MODEL` | env file | `gemini-2.5-flash` |
| `ENABLE_REGISTER` | env file | 首次建帳號 `true`，之後 `false` |
| ~~`ENABLE_AUTO_SPLIT`~~ | — | **已移除**（A2） |
| ~~`ENABLE_SCHEDULED_BATCH`~~ | — | **已移除**（A2） |
| ~~`SCHEDULED_BATCH_*`~~ | — | **已移除**（A2） |

## 附錄 B：疑難排解

| 症狀 | 可能原因 | 處置 |
|------|---------|------|
| 部署後 `/health` `db: unreachable` | `DATABASE_URL` 格式錯 / 未加 `--add-cloudsql-instances` / SA 缺 `cloudsql.client` | 檢查三者；確認 socket path `/cloudsql/<conn>` |
| 容器啟動失敗（crash loop） | startup `check_db_connection` 失敗就 `raise` | 先確認 Cloud SQL 與 Secret 正確 |
| Dashboard 圖片 404 / 破圖 | `STORAGE_BACKEND` 沒設 gcs / bucket 權限不足 / A1 未完成 | 檢查 env、SA `storage.objectAdmin`、`files.py` 是否已改 GCS |
| LINE 上傳後沒建單、無回覆 | 背景 OCR 被凍結 | 確認有加 `--no-cpu-throttling` |
| Dashboard 呼叫 API CORS 被擋 | `APP_ENV` 非 production 或 `CORS_ORIGINS` 沒含 Firebase 網址 | 修正 env file 後重新部署 |
| LIFF 開啟後 API base 錯誤 | proxy header 沒帶到 | Cloud Run 會自動帶；確認 LIFF Endpoint URL 指向 `/liff-app` |
| `--set-env-vars` 報逗號錯誤 | `CORS_ORIGINS`/`DEPARTMENTS` 含逗號 | 改用 `--env-vars-file=cloudrun.env.yaml` |
| Cloud Scheduler 回 401 | `X-Cleanup-Token` 與 Secret 不一致 | 對齊兩者 |

---

## 執行順序速查

```
Part A（改程式碼：GCS / 移除排程 / Port / CORS / 清理端點）→ 本機測試通過
   └─ git commit
Part B（建基礎設施：API/AR/CloudSQL/GCS/Secret/SA）
Part C（建映像 → Alembic migration）
Part D（部署後端 Cloud Run + Cloud Scheduler）
Part C3（建第一個管理員帳號 → 關閉 ENABLE_REGISTER 重新部署）
Part E（建置 + 部署前端 Firebase → 回填 CORS 重新部署）
Part F（LINE webhook / LIFF URL / Rich Menu）
Part G（端到端驗證）
Part H/I（CI/CD、維運）
```
