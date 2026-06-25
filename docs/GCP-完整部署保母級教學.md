# AcctAssist GCP Cloud Run 完整部署教學（保母級）

> 適用版本：2026-06  
> 整合所有踩坑與修正，照著做可 0 失誤完成部署。

---

## 執行位置說明

每個步驟開頭都有標記，代表要在哪裡執行：

| 標記 | 意思 |
|------|------|
| ☁️ **Cloud Shell** | 開啟 https://shell.cloud.google.com ，在瀏覽器裡的終端機貼上 |
| 💻 **本機 PowerShell** | 在你的 Windows 電腦上，用 PowerShell 貼上 |
| 🌐 **瀏覽器操作** | 到指定網站用滑鼠點選，不用貼指令 |

---

## 事前準備：備妥這些資訊（開始前先抄下來）

從以下地方取得，全部複製到一個記事本備用：

**LINE Developers Console** (https://developers.line.biz/console/)：
- LINE Channel Secret → 在 Basic Settings 頁面
- LINE Channel Access Token → 在 Messaging API 頁面（點 Issue 產生）
- LIFF ID → 在 LIFF 頁面（格式像 `2010115806-XXXXXXXX`）

**Google AI Studio** (https://aistudio.google.com/)：
- Gemini API Key

**自行產生（在 Cloud Shell 執行）：**

☁️ **Cloud Shell** — 產生隨機金鑰，把輸出結果抄下來

```bash
echo "JWT_SECRET=$(openssl rand -hex 32)"
echo "CLEANUP_TOKEN=$(openssl rand -hex 16)"
```

---

## 第一步：把程式碼上傳到 Cloud Shell

☁️ **Cloud Shell** — 開啟 Cloud Shell 後，把程式碼 clone 進來

如果你的程式碼在 GitHub：
```bash
git clone https://github.com/你的帳號/你的repo名稱.git
cd 你的repo名稱
```

如果程式碼在本機，沒有推到 GitHub，可以用 Cloud Shell 的上傳功能：
1. Cloud Shell 右上角點「⋮」→「Upload」
2. 把整個專案資料夾壓成 zip 上傳
3. 解壓縮：`unzip 檔名.zip && cd 解壓後的資料夾名稱`

---

## Part B｜GCP 基礎設施建置

### 準備工作：設定專案 ID

☁️ **Cloud Shell** — **先執行這兩行，後面所有指令都依賴這兩個變數**

```bash
# 先查詢你的 Project ID 列表
gcloud projects list
```

看輸出，找到你要用的那個 PROJECT_ID，然後貼這兩行（把 `你的-project-id` 換成真實值）：

```bash
export PROJECT_ID="你的-project-id"
export REGION="asia-east1"
```

例如：`export PROJECT_ID="my-company-gcp-2026"`

> ⚠️ Cloud Shell 重新開啟後變數會消失，每次開 Cloud Shell 都要重新執行這兩行。

---

### B1：啟用必要 API

☁️ **Cloud Shell** — 直接全部貼上，不需要改任何東西

```bash
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  --project=$PROJECT_ID
```

等到出現 `Operation "operations/..." finished successfully.` 代表成功。

---

### B2：建立 Artifact Registry（存放 Docker 映像的倉庫）

☁️ **Cloud Shell** — 直接貼上，不需要改

```bash
gcloud artifacts repositories create acctassist \
  --repository-format=docker \
  --location=$REGION \
  --project=$PROJECT_ID
```

---

### B3：建立 Cloud SQL（資料庫）

☁️ **Cloud Shell** — 直接貼上，不需要改（等待約 5~10 分鐘）

```bash
gcloud sql instances create acctassist-db \
  --database-version=POSTGRES_16 \
  --tier=db-custom-1-3840 \
  --edition=ENTERPRISE \
  --region=$REGION \
  --storage-size=10GB \
  --storage-auto-increase \
  --no-assign-ip \
  --project=$PROJECT_ID
```

> ⚠️ `--edition=ENTERPRISE` 不可省略，否則會報錯 `Invalid Tier`。

等資料庫建立完成後，繼續貼這段（建立資料庫、使用者、並產生密碼）：

```bash
gcloud sql databases create acctassist \
  --instance=acctassist-db \
  --project=$PROJECT_ID
```

```bash
export DB_PASSWORD=$(openssl rand -hex 16)
echo "=== 資料庫密碼（請記下來）=== $DB_PASSWORD"

gcloud sql users create acctassist \
  --instance=acctassist-db \
  --password=$DB_PASSWORD \
  --project=$PROJECT_ID
```

取得資料庫連線名稱（後面很多步驟會用到）：

```bash
export SQL_CONN=$(gcloud sql instances describe acctassist-db \
  --project=$PROJECT_ID \
  --format='value(connectionName)')
echo "SQL_CONN=$SQL_CONN"
```

把 DATABASE_URL 組合好存入變數：

```bash
export DATABASE_URL="postgresql+asyncpg://acctassist:${DB_PASSWORD}@/acctassist?host=/cloudsql/${SQL_CONN}"
echo "DATABASE_URL 已設定"
```

---

### B4：建立 GCS Bucket（存放上傳圖片）

☁️ **Cloud Shell** — 直接貼上，不需要改

```bash
export BUCKET_NAME="acctassist-uploads-${PROJECT_ID}"

gcloud storage buckets create gs://${BUCKET_NAME} \
  --location=$REGION \
  --uniform-bucket-level-access \
  --no-public-access-prevention \
  --project=$PROJECT_ID

echo "Bucket 建立完成：$BUCKET_NAME"
```

---

### B5：建立 Secret Manager（儲存金鑰）

☁️ **Cloud Shell** — **把下面每個變數的值換成你實際的金鑰後貼上**

```bash
# ↓↓↓ 把引號內的文字換成你實際的金鑰 ↓↓↓
JWT_SECRET="在事前準備步驟產生的那串 64 位 hex 字元"
LINE_CHANNEL_SECRET="從 LINE Developers Console Basic Settings 複製"
LINE_CHANNEL_ACCESS_TOKEN="從 LINE Developers Console Messaging API 複製"
GEMINI_API_KEY="從 Google AI Studio 複製"
CLEANUP_TOKEN="在事前準備步驟產生的那串 32 位 hex 字元"
# DATABASE_URL 上一步已設定，不用重複填
```

填完後，貼這段建立 6 個 secret（不需要改）：

```bash
for SECRET_NAME in JWT_SECRET LINE_CHANNEL_SECRET LINE_CHANNEL_ACCESS_TOKEN GEMINI_API_KEY CLEANUP_TOKEN DATABASE_URL; do
  printf '%s' "${!SECRET_NAME}" | \
    gcloud secrets create $SECRET_NAME \
      --data-file=- \
      --project=$PROJECT_ID
  echo "✅ $SECRET_NAME 建立完成"
done
```

> ⚠️ 若出現 `already exists` 錯誤，改用以下指令追加版本（不需要改，直接貼）：
> ```bash
> for SECRET_NAME in JWT_SECRET LINE_CHANNEL_SECRET LINE_CHANNEL_ACCESS_TOKEN GEMINI_API_KEY CLEANUP_TOKEN DATABASE_URL; do
>   printf '%s' "${!SECRET_NAME}" | \
>     gcloud secrets versions add $SECRET_NAME \
>       --data-file=- \
>       --project=$PROJECT_ID
>   echo "✅ $SECRET_NAME 更新完成"
> done
> ```

**驗證金鑰有沒有存進去（不是空的）：**

☁️ **Cloud Shell** — 直接貼上

```bash
for SECRET_NAME in JWT_SECRET LINE_CHANNEL_SECRET LINE_CHANNEL_ACCESS_TOKEN GEMINI_API_KEY CLEANUP_TOKEN DATABASE_URL; do
  LEN=$(gcloud secrets versions access latest --secret=$SECRET_NAME --project=$PROJECT_ID | wc -c)
  echo "$SECRET_NAME: ${LEN} 字元"
done
```

每個應該都 > 10。若某個顯示 0 或 1，代表存入空值，需要重新填值再跑 `versions add`。

---

### B6：建立 Service Account（Cloud Run 的執行身份）

☁️ **Cloud Shell** — 直接貼上，不需要改

```bash
gcloud iam service-accounts create acctassist-run \
  --display-name="AcctAssist Cloud Run SA" \
  --project=$PROJECT_ID

export SA_EMAIL="acctassist-run@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudsql.client"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectAdmin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor"

echo "Service Account 設定完成：$SA_EMAIL"
```

---

## Part C｜建置 Docker 映像 + 執行 Migration

### C1：授予 Cloud Build 權限（必做，否則 build 會失敗）

☁️ **Cloud Shell** — 直接貼上，不需要改

```bash
export PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
export COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${COMPUTE_SA}" \
  --role="roles/storage.objectAdmin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${COMPUTE_SA}" \
  --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${COMPUTE_SA}" \
  --role="roles/logging.logWriter"

echo "Cloud Build 權限設定完成"
```

---

### C2：建置並推送 Docker 映像

☁️ **Cloud Shell** — 確認你在專案根目錄（有 `Dockerfile` 的地方），再貼這段

```bash
# 確認在正確的目錄（應該可以看到 Dockerfile）
ls Dockerfile

export IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/acctassist/backend:latest"

gcloud builds submit \
  --tag=$IMAGE \
  --project=$PROJECT_ID \
  .
```

等到輸出出現 `STATUS: SUCCESS` 代表完成（約 3~5 分鐘）。

---

### C3：執行 Alembic Migration（建立資料表）

☁️ **Cloud Shell** — 依序貼，共三段

**第一段：安裝 Python 套件**

```bash
pip install --user -r requirements.txt
pip install --user psycopg2-binary
export PATH="$HOME/.local/bin:$PATH"
```

**第二段：啟動 Cloud SQL Auth Proxy（讓 Cloud Shell 可以連到資料庫）**

```bash
wget -q https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.14.1/cloud-sql-proxy.linux.amd64 -O cloud-sql-proxy
chmod +x cloud-sql-proxy
./cloud-sql-proxy --port=5432 $SQL_CONN &
sleep 3
echo "Proxy 已啟動"
```

**第三段：執行 Migration**

```bash
export DATABASE_URL="postgresql+psycopg2://acctassist:${DB_PASSWORD}@127.0.0.1:5432/acctassist"
alembic upgrade head
```

Migration 全部跑完，最後沒有 ERROR 就代表成功（會看到很多 `Running upgrade ...`）。

> ⚠️ 若出現 `alembic: command not found`：
> ```bash
> export PATH="$HOME/.local/bin:$PATH"
> ```
> 再重跑 `alembic upgrade head`。

> ⚠️ 若出現 `UnsafeNewEnumValueUsage`：代表 `alembic/env.py` 裡沒有加 `transaction_per_migration=True`。  
> 確認檔案內的 `run_migrations_online()` 有這一行再重跑。

---

## Part D｜部署 Cloud Run 後端

### D1：建立設定檔 cloudrun.env.yaml

☁️ **Cloud Shell** — **把 `你的-project-id` 和 `部門清單` 換掉後貼上**

```bash
cat > cloudrun.env.yaml << EOF
APP_ENV: "production"
APP_DEBUG: "false"
STORAGE_BACKEND: "gcs"
GCS_BUCKET: "acctassist-uploads-${PROJECT_ID}"
GEMINI_MODEL: "gemini-2.5-flash"
JWT_EXPIRE_MINUTES: "480"
ENABLE_LINE_PUSH_REJECT: "true"
ENABLE_USER_BINDING: "true"
ENABLE_ROSTER_BINDING: "true"
ENABLE_REGISTER: "true"
ENABLE_WAITING_RETURN_TEXT_MODE: "true"
ENABLE_WAITING_RETURN_LIFF_BUTTON: "true"
LIFF_SUBMIT_MODE: "single"
OCR_MAX_CONCURRENT: "3"
OCR_MAX_RETRIES: "3"
KEY_FIELD_CONFIDENCE_THRESHOLD: "0.8"
LIFF_SESSION_TTL_MINUTES: "30"
ORPHAN_WINDOW_MINUTES: "10"
EXPENSE_EXPORT_LIMIT: "10000"
COMPANY_TAX_ID: ""
CORS_ORIGINS: '[]'
DEPARTMENTS: "製作部,美術部,演員組,執行製作"
EOF

echo "cloudrun.env.yaml 建立完成"
cat cloudrun.env.yaml
```

> 注意：`DEPARTMENTS` 換成你的實際部門名稱，逗號分隔。  
> `CORS_ORIGINS` 先留 `'[]'`，等 Firebase 部署完再更新。

---

### D2：部署 Cloud Run 服務

☁️ **Cloud Shell** — 直接貼上，不需要改（約 2~3 分鐘）

```bash
gcloud run deploy acctassist-backend \
  --image=$IMAGE \
  --region=$REGION \
  --platform=managed \
  --service-account=$SA_EMAIL \
  --add-cloudsql-instances=$SQL_CONN \
  --env-vars-file=cloudrun.env.yaml \
  --set-secrets="JWT_SECRET=JWT_SECRET:latest,LINE_CHANNEL_SECRET=LINE_CHANNEL_SECRET:latest,LINE_CHANNEL_ACCESS_TOKEN=LINE_CHANNEL_ACCESS_TOKEN:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest,CLEANUP_TOKEN=CLEANUP_TOKEN:latest,DATABASE_URL=DATABASE_URL:latest" \
  --min-instances=0 \
  --max-instances=3 \
  --memory=512Mi \
  --cpu=1 \
  --timeout=300 \
  --concurrency=80 \
  --no-cpu-throttling \
  --allow-unauthenticated \
  --project=$PROJECT_ID
```

> ⚠️ `--no-cpu-throttling` 一定要加，否則背景 OCR 任務會中途被系統中斷。

部署完成後取得後端 URL：

```bash
export BACKEND_URL=$(gcloud run services describe acctassist-backend \
  --region=$REGION --project=$PROJECT_ID \
  --format='value(status.url)')
echo "=== 後端 URL（抄下來）=== $BACKEND_URL"
```

---

### D3：驗證後端是否正常

☁️ **Cloud Shell** — 直接貼上

```bash
curl ${BACKEND_URL}/health
```

**預期看到：**
```json
{"status":"success","data":{"db":"ok"},"message":"AcctAssist is running"}
```

有看到 `"db":"ok"` 才代表資料庫連線正常。

---

### D4：建立管理員帳號

☁️ **Cloud Shell** — **把 `password` 的 `你的強密碼` 換成你要設定的密碼**

```bash
curl -X POST ${BACKEND_URL}/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"你的強密碼","display_name":"管理員"}'
```

預期回傳包含 `"status":"success"` 的 JSON。

---

### D5：關閉開放註冊（建立帳號後立刻做）

☁️ **Cloud Shell** — 直接貼上

```bash
gcloud run services update acctassist-backend \
  --region=$REGION \
  --update-env-vars ENABLE_REGISTER=false \
  --project=$PROJECT_ID
```

---

## Part E｜部署 Firebase 前端（Dashboard）

### E1：在瀏覽器啟用 Firebase

🌐 **瀏覽器操作**

> ⚠️ 不要用 CLI 指令加 Firebase，很容易失敗，直接用網頁操作最穩。

1. 開啟 https://console.firebase.google.com/
2. 點「新增專案」
3. 選擇「將 Firebase 新增到現有的 Google Cloud 專案」
4. 從下拉選單選你的 GCP 專案（`PROJECT_ID`）
5. 一路點下一步直到完成

---

### E2：安裝 Firebase CLI 並登入

☁️ **Cloud Shell** — 直接貼上

```bash
npm install -g firebase-tools
firebase login --no-localhost
```

執行後會出現一個 URL，在瀏覽器開啟這個 URL，用 Google 帳號登入，然後把頁面上的授權碼貼回 Cloud Shell。

---

### E3：初始化 Firebase Hosting

☁️ **Cloud Shell** — 確認在專案根目錄，直接貼上

```bash
firebase init hosting --project=$PROJECT_ID
```

出現問題時依序回答：
- `What do you want to use as your public directory?` → 輸入 `frontend/dist` 然後 Enter
- `Configure as a single-page app?` → 輸入 `y` 然後 Enter
- `Set up automatic builds and deploys with GitHub?` → 輸入 `N` 然後 Enter
- `File frontend/dist/index.html already exists. Overwrite?` → 輸入 `N` 然後 Enter

---

### E4：建置前端

☁️ **Cloud Shell** — **把 `BACKEND_URL` 替換成 D2 步驟取得的後端 URL**（若 `$BACKEND_URL` 變數還在就不用換）

```bash
cat > .env << EOF
VITE_API_BASE_URL=${BACKEND_URL}
VITE_ENABLE_PROCESS_PENDING=false
VITE_ENABLE_SCHEDULER_CONFIG=false
VITE_ENABLE_DUPLICATE_DETECTION=true
EOF

echo "=== .env 內容確認 ==="
cat .env
```

確認 `VITE_API_BASE_URL=` 後面有實際的 URL（不是空的），再繼續：

```bash
cd frontend
npm install
npm run build
cd ..
```

**確認 URL 有成功打包進去：**

```bash
grep -r "acctassist-backend" frontend/dist/assets/*.js | head -c 100
```

有印出東西才代表正確，若沒輸出代表 URL 沒有打包進去，要重新確認 `.env` 再重 build。

---

### E5：部署到 Firebase

☁️ **Cloud Shell** — 直接貼上

```bash
firebase deploy --only hosting --project=$PROJECT_ID
```

成功後輸出會有：
```
Hosting URL: https://你的project-id.web.app
```

把這個 URL 抄下來。

---

### E6：更新 Cloud Run 的 CORS 設定

☁️ **Cloud Shell** — **把 `你的project-id` 換成實際的 Project ID**（若變數還在就不用換）

```bash
FIREBASE_URL="https://${PROJECT_ID}.web.app"

gcloud run services update acctassist-backend \
  --region=$REGION \
  --update-env-vars "CORS_ORIGINS=[\"${FIREBASE_URL}\",\"https://${PROJECT_ID}.firebaseapp.com\"]" \
  --project=$PROJECT_ID

echo "CORS 更新完成，允許：$FIREBASE_URL"
```

---

## Part F｜LINE 設定（全部在瀏覽器做）

### F1：更新 Webhook URL

🌐 **瀏覽器操作** — 開啟 https://developers.line.biz/console/

1. 選擇你的 Provider → 選擇 Messaging API Channel
2. 點「Messaging API」分頁
3. 找到「Webhook URL」欄位，點編輯，填入：
   ```
   https://你的cloud-run-url/webhook
   ```
   （把 `你的cloud-run-url` 換成 D2 步驟拿到的 BACKEND_URL）
4. 開啟「Use webhook」開關
5. 點「Verify」，出現 `Success` 才算成功

---

### F2：更新 LIFF Endpoint URL

🌐 **瀏覽器操作**

> ⚠️ LIFF 頁面是由 **Cloud Run 後端**提供的（路徑 `/liff-single`），**不是** Firebase 前端。  
> 舊的 ngrok URL 失效後，Rich Menu 點開會顯示 ERR_NGROK_3200，就是因為這裡沒更新。

1. LINE Developers Console → 同一個 Channel
2. 點「LIFF」分頁
3. 點進去你的 LIFF App，點編輯
4. 把「Endpoint URL」改成：
   ```
   https://你的cloud-run-url/liff-single
   ```
5. 儲存

---

### F3：設定 LINE Rich Menu

☁️ **Cloud Shell** — **先取得 JWT Token，再設定 Rich Menu**

**步驟一：取得 JWT Token（登入 API）**

```bash
TOKEN=$(curl -s -X POST ${BACKEND_URL}/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=你的管理員密碼" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['access_token'])")

echo "Token: $TOKEN"
```

**步驟二：設定 Rich Menu**

```bash
curl -X POST ${BACKEND_URL}/api/v1/admin/setup-rich-menu \
  -H "Authorization: Bearer $TOKEN"
```

---

## Part G｜Cloud Scheduler（定時清理任務）

☁️ **Cloud Shell** — 直接貼上，不需要改

```bash
export CLEANUP_TOKEN_VALUE=$(gcloud secrets versions access latest \
  --secret=CLEANUP_TOKEN --project=$PROJECT_ID)

gcloud scheduler jobs create http acctassist-liff-cleanup \
  --location=$REGION \
  --schedule="0 3 * * *" \
  --time-zone="Asia/Taipei" \
  --uri="${BACKEND_URL}/api/v1/admin/cleanup-liff-sessions" \
  --http-method=POST \
  --headers="Content-Type=application/json,X-Cleanup-Token=${CLEANUP_TOKEN_VALUE}" \
  --message-body='{}' \
  --project=$PROJECT_ID
```

確認建立成功：

```bash
gcloud scheduler jobs list --location=$REGION --project=$PROJECT_ID
```

應該看到 `STATE: ENABLED`。

---

## Part H｜功能開關確認（部署後必做）

以下開關在 `cloudrun.env.yaml` 已設為 `true`，但若你是用舊方法部署的，要手動更新：

☁️ **Cloud Shell** — 直接貼上

```bash
gcloud run services update acctassist-backend \
  --region=$REGION \
  --update-env-vars ENABLE_ROSTER_BINDING=true,ENABLE_WAITING_RETURN_TEXT_MODE=true,ENABLE_WAITING_RETURN_LIFF_BUTTON=true \
  --project=$PROJECT_ID
```

| 開關 | 功能 | 沒開會怎樣 |
|------|------|-----------|
| `ENABLE_ROSTER_BINDING` | 員工在 LINE 輸入姓名自動綁定名冊 | 輸入姓名完全沒反應 |
| `ENABLE_WAITING_RETURN_TEXT_MODE` | 備注輸入「待退貨」自動標記案件 | 案件不會出現在待退貨管理左欄 |
| `ENABLE_WAITING_RETURN_LIFF_BUTTON` | LIFF 頁面顯示退換貨處理 checkbox | LIFF 沒有退換貨選項 |

---

## 最終驗證清單

全部做完，用這份清單逐一確認：

```
□ 1. Cloud Shell：curl /health 回傳 {"data":{"db":"ok"}}
□ 2. 瀏覽器：開啟 Firebase URL (https://project-id.web.app)，可以登入 Dashboard
□ 3. LINE Developers Console：Webhook Verify 顯示 Success
□ 4. LINE App：點 Rich Menu，不顯示 ngrok 錯誤，正確開啟 LIFF 報帳頁面
□ 5. LINE App：輸入名冊上的姓名，收到「設定完成」綁定成功訊息
□ 6. LINE App：報帳後，Dashboard 可看到這筆案件
□ 7. LINE App：報帳時備注輸入「待退貨」，案件出現在 Dashboard 待退貨管理左欄
□ 8. Cloud Shell：gcloud scheduler jobs list 顯示 STATE: ENABLED
```

---

## 踩坑速查表

| 錯誤訊息 / 症狀 | 原因 | 解法 |
|----------------|------|------|
| `Invalid Tier (db-custom-1-3840) for ENTERPRISE_PLUS` | 沒加 `--edition=ENTERPRISE` | B3 加上這個參數 |
| `storage.objects.get access denied` | Cloud Build 缺少 GCS 權限 | C1 授予 `storage.objectAdmin` |
| `artifactregistry.repositories.uploadArtifacts access denied` | Cloud Build 缺少 AR 權限 | C1 授予 `artifactregistry.writer` |
| `alembic: command not found` | PATH 沒包含 pip 安裝路徑 | `export PATH="$HOME/.local/bin:$PATH"` |
| `UnsafeNewEnumValueUsage: unsafe use of new value` | PostgreSQL enum transaction 限制 | 確認 `alembic/env.py` 有 `transaction_per_migration=True` |
| Secret 長度顯示 0 或 1 | `read -p` 用法錯誤，存入空值 | 改用 `printf '%s' "$VAR" \| gcloud secrets versions add ...` |
| Firebase `addfirebase` 指令失敗 | CLI 有時有 quota 問題 | 改用 Firebase Console 網頁操作 |
| 登入 Dashboard 成功但 API 都回傳 HTML | Vite 沒有讀到 `VITE_API_BASE_URL` | 在 Cloud Shell 用 `cat > .env` 寫檔，不要在 PowerShell 用 `Out-File` |
| LINE Rich Menu 點開顯示 `ERR_NGROK_3200` | LIFF Endpoint URL 還是舊 ngrok 網址 | F2 更新為 Cloud Run URL + `/liff-single` |
| 員工輸入姓名沒有綁定 | `ENABLE_ROSTER_BINDING=false` | H 更新環境變數為 `true` |
| 備注輸入「待退貨」案件沒出現在左欄 | `ENABLE_WAITING_RETURN_TEXT_MODE=false` | H 更新環境變數為 `true` |
| LIFF 沒有退換貨 checkbox | `ENABLE_WAITING_RETURN_LIFF_BUTTON=false` | H 更新環境變數為 `true` |
