# GCP 換帳號重新部署指南

> 本文件說明如何將 AcctAssist 從舊 GCP 帳號完整遷移至新 GCP 帳號。
> **本地程式碼、git 分支、GitHub repo 完全不需要動。**

---

## 概念說明

```
GitHub repo（程式碼）
       │
       │  push to main
       ▼
GitHub Actions（CI/CD）
       │
       │  使用 Secrets 中的憑證連線
       ▼
新 GCP 帳號（部署目的地）
  ├── Artifact Registry（Docker image）
  ├── Cloud Run（後端 API）
  ├── Cloud SQL（PostgreSQL 資料庫）
  ├── Cloud Storage（圖片 GCS bucket）
  ├── Secret Manager（所有機敏環境變數）
  └── Firebase Hosting（前端 Vue SPA）
```

換帳號的本質：**在新 GCP 帳號重建上述所有雲端資源，然後把 GitHub Secrets 換掉。**

---

## 前置確認清單

- [ ] 已建立新 GCP 帳號並啟用計費
- [ ] 已安裝並登入 `gcloud` CLI（`gcloud auth login`）
- [ ] 已安裝 `firebase-tools`（`npm install -g firebase-tools`）
- [ ] 已確認新帳號有足夠的 IAM 權限（Owner 或 Editor）

---

## Step 1：建立 GCP Project

```bash
# 建立新 Project（project-id 自訂，全球唯一）
gcloud projects create YOUR_NEW_PROJECT_ID --name="AcctAssist"

# 設定為預設 Project
gcloud config set project YOUR_NEW_PROJECT_ID

# 啟用計費（至 GCP Console 手動綁定帳單帳戶）
# https://console.cloud.google.com/billing
```

---

## Step 2：啟用所需 GCP API

```bash
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  storage.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  cloudresourcemanager.googleapis.com \
  firebase.googleapis.com \
  firebasehosting.googleapis.com
```

---

## Step 3：建立 Artifact Registry

```bash
gcloud artifacts repositories create acctassist \
  --repository-format=docker \
  --location=asia-east1 \
  --description="AcctAssist backend images"
```

---

## Step 4：建立 Cloud SQL（PostgreSQL 16）

```bash
# 建立 Cloud SQL 執行個體（需等約 5 分鐘）
gcloud sql instances create acctassist-db \
  --database-version=POSTGRES_16 \
  --tier=db-f1-micro \
  --region=asia-east1 \
  --root-password=YOUR_ROOT_PASSWORD

# 建立資料庫
gcloud sql databases create acctassist \
  --instance=acctassist-db

# 建立資料庫使用者
gcloud sql users create acctassist_user \
  --instance=acctassist-db \
  --password=YOUR_DB_PASSWORD

# 取得 Connection Name（後面 Secret Manager 會用到）
gcloud sql instances describe acctassist-db --format="value(connectionName)"
# 格式：YOUR_PROJECT_ID:asia-east1:acctassist-db
```

---

## Step 5：建立 GCS Bucket（圖片儲存）

```bash
# Bucket 名稱全球唯一，建議用 project-id 當前綴
gcloud storage buckets create gs://YOUR_NEW_PROJECT_ID-uploads \
  --location=asia-east1 \
  --uniform-bucket-level-access
```

---

## Step 6：建立 Secret Manager 機敏資料

```bash
# 建立所有 Secret（value 請替換為真實值）

echo -n "postgresql+asyncpg://acctassist_user:YOUR_DB_PASSWORD@/acctassist?host=/cloudsql/YOUR_SQL_CONN_NAME" \
  | gcloud secrets create DATABASE_URL --data-file=-

echo -n "YOUR_JWT_SECRET_MIN_32_CHARS" \
  | gcloud secrets create JWT_SECRET --data-file=-

echo -n "YOUR_LINE_CHANNEL_SECRET" \
  | gcloud secrets create LINE_CHANNEL_SECRET --data-file=-

echo -n "YOUR_LINE_CHANNEL_ACCESS_TOKEN" \
  | gcloud secrets create LINE_CHANNEL_ACCESS_TOKEN --data-file=-

echo -n "YOUR_GEMINI_API_KEY" \
  | gcloud secrets create GEMINI_API_KEY --data-file=-

echo -n "YOUR_CLEANUP_TOKEN" \
  | gcloud secrets create CLEANUP_TOKEN --data-file=-
```

> **說明**：`DATABASE_URL` 的格式中，`YOUR_SQL_CONN_NAME` 為 Step 4 取得的 Connection Name（如 `myproject:asia-east1:acctassist-db`）。

---

## Step 7：建立 Service Account（Cloud Run 執行身份）

```bash
# 建立 Service Account
gcloud iam service-accounts create acctassist-run \
  --display-name="AcctAssist Cloud Run SA"

# 取得完整 email（後面要用）
# 格式：acctassist-run@YOUR_PROJECT_ID.iam.gserviceaccount.com

# 授予必要權限
SA_EMAIL="acctassist-run@YOUR_NEW_PROJECT_ID.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding YOUR_NEW_PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudsql.client"

gcloud projects add-iam-policy-binding YOUR_NEW_PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectAdmin"

gcloud projects add-iam-policy-binding YOUR_NEW_PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor"

gcloud projects add-iam-policy-binding YOUR_NEW_PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker"
```

---

## Step 8：設定 Workload Identity Federation（WIF）

> WIF 讓 GitHub Actions 不需要 JSON 金鑰就能登入 GCP，更安全。

```bash
PROJECT_ID="YOUR_NEW_PROJECT_ID"
PROJECT_NUMBER=$(gcloud projects describe ${PROJECT_ID} --format="value(projectNumber)")
GITHUB_REPO="你的GitHub帳號/你的repo名稱"  # 例：myuser/acctassist

# 建立 WIF Pool
gcloud iam workload-identity-pools create github-pool \
  --location=global \
  --display-name="GitHub Actions Pool"

# 建立 WIF Provider
gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location=global \
  --workload-identity-pool=github-pool \
  --display-name="GitHub Provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='${GITHUB_REPO}'"

# 建立 GitHub Actions 專用 Service Account
gcloud iam service-accounts create github-actions-sa \
  --display-name="GitHub Actions SA"

GH_SA="github-actions-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# 授予 GitHub Actions SA 所需權限
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${GH_SA}" \
  --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${GH_SA}" \
  --role="roles/run.developer"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${GH_SA}" \
  --role="roles/iam.serviceAccountUser"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${GH_SA}" \
  --role="roles/firebase.admin"

# 允許 WIF 冒充此 SA
gcloud iam service-accounts add-iam-policy-binding ${GH_SA} \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/${GITHUB_REPO}" \
  --role="roles/iam.workloadIdentityUser"

# 取得 WIF Provider 完整路徑（填入 GitHub Secret 用）
echo "WIF_PROVIDER:"
gcloud iam workload-identity-pools providers describe github-provider \
  --location=global \
  --workload-identity-pool=github-pool \
  --format="value(name)"
# 格式：projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/providers/github-provider
```

---

## Step 9：設定 Firebase Hosting

```bash
# 初始化 Firebase（在 frontend/ 目錄下）
# 如果已有 .firebaserc 記得確認 project 是否正確

firebase use --add YOUR_NEW_PROJECT_ID
# 或直接編輯 frontend/.firebaserc：
# { "projects": { "default": "YOUR_NEW_PROJECT_ID" } }
```

> 也可至 [Firebase Console](https://console.firebase.google.com) 新增 Project，並啟用 Hosting。

---

## Step 10：更新 cloudrun.env.yaml

檢查專案根目錄的 `cloudrun.env.yaml`，確認以下佔位符號會被 CI/CD 正確替換：

```yaml
# cloudrun.env.yaml 中這兩個值由 GitHub Actions 在部署時動態替換
GCS_BUCKET: REPLACE_GCS_BUCKET      # → 由 Secret GCS_BUCKET 填入
CORS_ORIGINS: REPLACE_CORS_ORIGINS  # → 由 Secret CORS_ORIGINS 填入
```

其他固定值欄位（如 `APP_ENV`、`ENABLE_AUTO_SPLIT` 等）維持不變。

---

## Step 11：更新 GitHub Secrets

至 GitHub repo → **Settings → Secrets and variables → Actions**，更新以下所有 Secrets：

| Secret 名稱 | 說明 | 取得方式 |
|---|---|---|
| `GCP_PROJECT_ID` | 新 Project ID | Step 1 自訂的 project-id |
| `GCP_REGION` | 部署區域 | `asia-east1`（或你選的區域） |
| `WIF_PROVIDER` | WIF Provider 完整路徑 | Step 8 最後的 echo 輸出 |
| `WIF_SERVICE_ACCOUNT` | GitHub Actions SA email | `github-actions-sa@NEW_PROJECT_ID.iam.gserviceaccount.com` |
| `RUN_SA_EMAIL` | Cloud Run 執行 SA email | `acctassist-run@NEW_PROJECT_ID.iam.gserviceaccount.com` |
| `AR_REPO` | Artifact Registry repo 名稱 | `acctassist` |
| `CLOUD_RUN_SERVICE` | Cloud Run 服務名稱 | `acctassist`（或你決定的名稱） |
| `SQL_CONN` | Cloud SQL Connection Name | Step 4 的 connectionName 輸出 |
| `GCS_BUCKET` | GCS Bucket 名稱 | Step 5 建立的 bucket 名稱 |
| `CORS_ORIGINS` | 允許的 CORS 來源 | Firebase Hosting URL，如 `https://NEW_PROJECT_ID.web.app` |
| `VITE_API_BASE_URL` | 前端 API 基底 URL | 先填舊的，部署後 Cloud Run URL 出來再更新 |

---

## Step 12：觸發第一次部署

```bash
# 隨便做一個空 commit 觸發 CI/CD
git commit --allow-empty -m "chore: 觸發新 GCP 帳號首次部署"
git push origin main
```

至 GitHub repo → **Actions** 頁面觀看部署進度（約 10–15 分鐘）。

---

## Step 13：部署完成後的收尾

### 取得新的 Cloud Run URL

```bash
gcloud run services describe acctassist \
  --region=asia-east1 \
  --format="value(status.url)"
```

### 更新 VITE_API_BASE_URL

1. 複製上面取得的 Cloud Run URL
2. 至 GitHub Secrets 更新 `VITE_API_BASE_URL` 為此 URL
3. 再 push 一次 commit 重新 build 前端

### 更新 LINE Bot Webhook URL

至 [LINE Developers Console](https://developers.line.biz) → 你的 Channel → Messaging API：

```
Webhook URL: https://YOUR_CLOUD_RUN_URL/webhook
```

### 建立管理員帳號

```bash
curl -X POST https://YOUR_CLOUD_RUN_URL/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "YOUR_PASSWORD", "display_name": "管理員"}'
```

### 建立 LINE Rich Menu

```bash
curl -X POST https://YOUR_CLOUD_RUN_URL/api/v1/admin/setup-rich-menu \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

---

## 注意事項

### 資料庫資料遷移

換帳號後 Cloud SQL 是全新的空資料庫（schema 由 Alembic 自動建立）。若需要保留舊資料：

```bash
# 在舊帳號的 Cloud SQL 匯出
gcloud sql export sql OLD_INSTANCE_NAME gs://OLD_BUCKET/backup.sql \
  --database=acctassist

# 在新帳號匯入
gcloud sql import sql NEW_INSTANCE_NAME gs://NEW_BUCKET/backup.sql \
  --database=acctassist
```

### GCS 圖片資料遷移

若需要保留舊的發票圖片：

```bash
gcloud storage cp -r gs://OLD_BUCKET/* gs://NEW_BUCKET/
```

### 舊帳號資源

確認新帳號一切正常後，再去舊 GCP 帳號刪除資源，避免繼續計費：
- Cloud Run 服務
- Cloud SQL 執行個體（費用最高）
- Artifact Registry
- GCS Bucket

---

## 快速檢查清單（部署完成後）

- [ ] GitHub Actions pipeline 全部 job 綠燈
- [ ] Cloud Run URL 可正常訪問（`/health` 回傳 `{"status": "success"}`）
- [ ] Firebase Hosting URL 可正常開啟 Dashboard
- [ ] Dashboard 可用管理員帳密登入
- [ ] LINE Bot Webhook 驗證通過
- [ ] 上傳圖片測試 OCR 流程正常
- [ ] 管理員可在 Dashboard 看到報帳記錄
