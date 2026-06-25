# GitHub Actions → GCP Cloud Run CI/CD 完整踩坑手冊

> 適用情境：使用 Workload Identity Federation（WIF）從 GitHub Actions 部署 Docker 容器到 GCP Cloud Run + Firebase Hosting，不使用 SA JSON Key。

---

## 一、架構概覽

```
GitHub Actions
  ├── WIF OIDC Token → 換成 SA 短期憑證
  ├── Docker build → push 到 Artifact Registry
  ├── Cloud Run Job → alembic migrate
  ├── gcloud run deploy → Cloud Run Service
  └── firebase deploy → Firebase Hosting
```

**所有認證都透過 Workload Identity Federation，不產生 SA JSON Key。**

---

## 二、必要的 GCP 前置設定

### 2.1 建立 Workload Identity Pool 與 Provider

```bash
# 建立 Pool
gcloud iam workload-identity-pools create github-pool \
  --location=global \
  --display-name="GitHub Actions Pool"

# 建立 Provider（對應 GitHub OIDC）
gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location=global \
  --workload-identity-pool=github-pool \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='你的GitHub帳號/你的Repo名稱'"
```

### 2.2 建立 CI/CD 專用 Service Account

```bash
gcloud iam service-accounts create github-actions-cicd \
  --display-name="GitHub Actions CI/CD"
```

### 2.3 授予 SA 各項 GCP 權限

```bash
PROJECT_ID="你的-project-id"
SA="github-actions-cicd@${PROJECT_ID}.iam.gserviceaccount.com"

# Artifact Registry 推送
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}" --role="roles/artifactregistry.writer"

# Cloud Run 部署
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}" --role="roles/run.admin"

# Cloud SQL 連線（migrate job 需要）
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}" --role="roles/cloudsql.client"

# Secret Manager 讀取
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}" --role="roles/secretmanager.secretAccessor"

# Firebase Hosting 部署
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}" --role="roles/firebasehosting.admin"

# 讓 SA 可以扮演執行 Cloud Run 的 SA
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}" --role="roles/iam.serviceAccountUser"
```

### 2.4 讓 WIF 綁定到 SA

```bash
POOL_ID=$(gcloud iam workload-identity-pools describe github-pool \
  --location=global --format="value(name)")

gcloud iam service-accounts add-iam-policy-binding "${SA}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${POOL_ID}/attribute.repository/你的GitHub帳號/你的Repo名稱"
```

### 2.5 必要的 GitHub Secrets 清單

| Secret 名稱 | 說明 | 正確填法範例 |
|------------|------|------------|
| `WIF_PROVIDER` | WIF Provider 完整資源名稱 | `projects/123456789/locations/global/workloadIdentityPools/github-pool/providers/github-provider` |
| `WIF_SERVICE_ACCOUNT` | SA email | `github-actions-cicd@my-project.iam.gserviceaccount.com` |
| `GCP_PROJECT_ID` | **GCP 專案 ID（字串，非數字）** | `my-project-abc123` |
| `GCP_REGION` | 部署區域 | `asia-east1` |
| `AR_REPO` | Artifact Registry 儲存庫名稱 | `acctassist` |
| `CLOUD_RUN_SERVICE` | Cloud Run 服務名稱 | `acctassist` |
| `RUN_SA_EMAIL` | Cloud Run 執行用 SA email | `acctassist-run@my-project.iam.gserviceaccount.com` |
| `SQL_CONN` | Cloud SQL 連線名稱 | `my-project:asia-east1:my-db` |
| `GCS_BUCKET` | GCS Bucket 名稱 | `my-project-uploads` |
| `CORS_ORIGINS` | 允許的 CORS 來源（任意格式） | `https://my-app.web.app,https://my-run.run.app` |
| `VITE_API_BASE_URL` | 前端 API base URL | `https://my-run.run.app` |

---

## 三、踩坑全紀錄與根本原因分析

---

### 坑 1：WIF 無法注入 OIDC Token

**錯誤訊息**
```
Error: Could not get the ID token. 
did not inject $ACTIONS_ID_TOKEN_REQUEST_TOKEN
```

**根本原因**

GitHub Actions 預設不開放 OIDC token 注入，WIF 的 `google-github-actions/auth@v2` 需要明確宣告權限。

**修法**

在 workflow 最上層（全域）加入：
```yaml
permissions:
  contents: read
  id-token: write   # ← 這行是關鍵
```

> **注意**：必須放在 workflow 最上層，不能只放在單一 job 下。

---

### 坑 2：docker push 持續報 Permission Denied（最耗時的問題）

**錯誤訊息**
```
denied: Permission 'artifactregistry.repositories.uploadArtifacts' denied on resource (or it may not exist).
```

**排查過程**

這個錯誤讓人以為是 IAM 問題，但其實 IAM 設定全部正確。真正的問題花了很長時間才找到。

#### 偵錯步驟 1：確認 SA 是否正確認證

在 workflow 加入：
```yaml
- name: Debug
  run: |
    gcloud auth list
    TOKEN=$(gcloud auth print-access-token)
    curl -s "https://www.googleapis.com/oauth2/v3/tokeninfo?access_token=${TOKEN}"
```

正常輸出應包含 `"email": "github-actions-cicd@..."` 和 `"email_verified": "true"`。

#### 偵錯步驟 2：測試 AR API 存取

```yaml
TOKEN=$(gcloud auth print-access-token)
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer ${TOKEN}" \
  "https://artifactregistry.googleapis.com/v1/projects/${{ secrets.GCP_PROJECT_ID }}/locations/${{ secrets.GCP_REGION }}/repositories/${{ secrets.AR_REPO }}")
echo "HTTP status: ${HTTP_CODE}"
```

- 回傳 **200** → IAM 沒問題，問題在 docker 認證層
- 回傳 **403** → 可能是 IAM 問題或 **`GCP_PROJECT_ID` 填錯**

#### 偵錯步驟 3：比對 project ID 是否一致（關鍵診斷）

```yaml
GCLOUD_PROJECT=$(gcloud config get-value project 2>/dev/null)
echo "gcloud project: ${GCLOUD_PROJECT}"
if [ "${GCLOUD_PROJECT}" = "${{ secrets.GCP_PROJECT_ID }}" ]; then
  echo "OK: project IDs match"
else
  echo "MISMATCH! Image is being pushed to wrong project!"
fi
```

**真正根本原因**：`GCP_PROJECT_ID` secret 填了錯誤的值。

GCP 每個專案有兩個識別碼：
- **Project ID**（字串）：`project-4e4a147c-a271-4718-8b3` ← 正確，應填這個
- **Project Number**（數字）：`993526376298`

填錯成 Project Number、或是填成了另一個帳號的 project，都會導致 image 推送到 SA 沒有權限的路徑。

**修法**

到 GitHub repo → Settings → Secrets → `GCP_PROJECT_ID`，填入正確的 **Project ID 字串**。

確認方式：
```bash
gcloud config get-value project
# 或
gcloud projects describe PROJECT_ID --format="value(projectId)"
```

**修改 secret 之後不會自動觸發 pipeline**，需要 push 一個空 commit：
```bash
git commit --allow-empty -m "chore: 觸發 CI" && git push
```

---

### 坑 3：docker 認證方式的選擇

在確認 IAM 正確後，有三種認證方式，使用順序建議如下：

**推薦（最穩定）：**
```yaml
- name: Configure Docker for Artifact Registry
  run: gcloud auth configure-docker ${{ secrets.GCP_REGION }}-docker.pkg.dev --quiet
```
設定 credential helper，docker push 時動態取得新 token。

**不推薦（容易被 runner 預設 helper 覆蓋）：**
```yaml
- name: Login
  run: |
    gcloud auth print-access-token | docker login \
      -u oauth2accesstoken --password-stdin \
      ${{ secrets.GCP_REGION }}-docker.pkg.dev
```
靜態 token 存入 `~/.docker/config.json`，但 runner 上若有預設 credHelpers 會被覆蓋。

---

### 坑 4：`needs.build-backend.outputs.image_tag` 跨 job 傳遞得到空字串

**錯誤訊息**
```
ERROR: (gcloud.run.jobs.deploy) job.spec.template.spec.containers[0].image: must provide an image name to deploy
```

**根本原因**

GitHub Actions 跨 job 的 output 傳遞在某些情況下不穩定，`needs.build-backend.outputs.image_tag` 評估為空字串，導致 `--image=""` 。

**修法**

不依賴跨 job output，讓每個 job 各自用相同公式重算 image tag：

```yaml
# 在 migrate 和 deploy-backend job 各自加入
- name: Deploy
  run: |
    SHORT_SHA=$(echo "${{ github.sha }}" | cut -c1-8)
    IMAGE="${{ secrets.GCP_REGION }}-docker.pkg.dev/${{ secrets.GCP_PROJECT_ID }}/${{ secrets.AR_REPO }}/backend:${SHORT_SHA}"
    gcloud run jobs deploy acctassist-migrate \
      --image="${IMAGE}" \
      ...
```

`github.sha` 在同一次 push 的所有 job 都是同一個值，所以算出來的 image tag 完全一致。

---

### 坑 5：Cloud Run 啟動失敗 — pydantic-settings 解析 CORS_ORIGINS 爆炸

**錯誤訊息（Cloud Run Logs）**
```
pydantic_settings.exceptions.SettingsError: error parsing value for field "cors_origins" from source "EnvSettingsSource"
json.decoder.JSONDecodeError: Expecting value: line 1 column 2 (char 1)
```

**根本原因**

這是 pydantic-settings v2 的行為陷阱：

```python
# 這樣宣告會有問題
cors_origins: list[str] = []
```

pydantic-settings 對 `list` 型別的欄位，會在 source 層（`EnvSettingsSource.decode_complex_value`）先呼叫 `json.loads()`，**這發生在 `field_validator` 之前，無法被攔截**。

若環境變數值是 `['https://foo.com']`（Python-style 單引號），或其他非合法 JSON 的字串，就會在啟動時 crash。

加 `field_validator` 無效，原因：
```
Settings.__init__
  → _settings_build_values
    → source()                    ← json.loads 在這裡爆
      → decode_complex_value
        → json.loads(value)       ← 錯誤在此
  → super().__init__(...)         ← field_validator 在這裡才跑，但已經來不及
```

**修法**

將欄位型別改成 `str`（pydantic-settings 不會對 `str` 呼叫 `json.loads`），解析邏輯移到應用層：

```python
# core/config.py
cors_origins: str = ""  # 不再是 list[str]
```

```python
# main.py
def _parse_cors_origins(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            import json as _json
            result = _json.loads(raw.replace("'", '"'))  # 容忍單引號格式
            if isinstance(result, list):
                return [str(o) for o in result]
        except Exception:
            pass
    return [o.strip() for o in raw.split(",") if o.strip()]

_cors_origins = ["*"] if settings.app_env == "development" else _parse_cors_origins(settings.cors_origins)
```

這樣 `CORS_ORIGINS` secret 無論填什麼格式都能接受：
- `https://foo.com,https://bar.com`（逗號分隔）
- `["https://foo.com"]`（合法 JSON）
- `['https://foo.com']`（Python-style，容錯）

> **規則**：所有 pydantic-settings 的 `list` / `dict` / 複合型別欄位，若來自環境變數，值**必須是合法 JSON**，或使用自訂 validator 在 str 型別上手動解析。

---

## 四、完整的 workflow 最終架構

```yaml
name: Deploy to Cloud Run

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  id-token: write   # WIF 必須

jobs:
  build-backend:
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ secrets.WIF_PROVIDER }}
          service_account: ${{ secrets.WIF_SERVICE_ACCOUNT }}
      - uses: google-github-actions/setup-gcloud@v2
      - name: Configure Docker
        run: gcloud auth configure-docker ${{ secrets.GCP_REGION }}-docker.pkg.dev --quiet
      - name: Compute tag
        id: meta
        run: |
          SHORT_SHA=$(echo "${{ github.sha }}" | cut -c1-8)
          IMAGE="${{ secrets.GCP_REGION }}-docker.pkg.dev/${{ secrets.GCP_PROJECT_ID }}/${{ secrets.AR_REPO }}/backend"
          echo "image_tag=${IMAGE}:${SHORT_SHA}" >> $GITHUB_OUTPUT
      - name: Build & push
        run: |
          docker build --tag "${{ steps.meta.outputs.image_tag }}" .
          docker push "${{ steps.meta.outputs.image_tag }}"

  migrate:
    needs: build-backend
    steps:
      # ... auth, setup-gcloud ...
      - name: Run migration
        run: |
          SHORT_SHA=$(echo "${{ github.sha }}" | cut -c1-8)
          IMAGE="${{ secrets.GCP_REGION }}-docker.pkg.dev/${{ secrets.GCP_PROJECT_ID }}/${{ secrets.AR_REPO }}/backend:${SHORT_SHA}"
          gcloud run jobs deploy my-migrate --image="${IMAGE}" ...
          # ↑ 自行算 image tag，不用 needs.build-backend.outputs

  deploy-backend:
    needs: [build-backend, migrate]
    steps:
      - name: Deploy
        run: |
          SHORT_SHA=$(echo "${{ github.sha }}" | cut -c1-8)
          IMAGE="${{ secrets.GCP_REGION }}-docker.pkg.dev/${{ secrets.GCP_PROJECT_ID }}/${{ secrets.AR_REPO }}/backend:${SHORT_SHA}"
          gcloud run deploy my-service --image="${IMAGE}" ...
          # ↑ 同樣自行算，不依賴跨 job output
```

---

## 五、快速診斷 Checklist

遇到 `Permission denied on Artifact Registry` 時，依序確認：

```
□ 1. workflow 有 permissions: id-token: write
□ 2. GCP_PROJECT_ID secret 填的是 Project ID 字串（非 Project Number）
      → 用 `gcloud config get-value project` 確認正確值
□ 3. SA 有 roles/artifactregistry.writer（project 層級即可）
      → 用 `gcloud projects get-iam-policy PROJECT_ID --filter="bindings.members:SA_EMAIL"` 確認
□ 4. WIF principalSet 有 roles/iam.workloadIdentityUser on SA
      → 用 `gcloud iam service-accounts get-iam-policy SA_EMAIL` 確認
□ 5. AR API test 回傳 200（確認是 IAM 問題還是 docker 客戶端問題）
      → TOKEN=$(gcloud auth print-access-token)
         curl -H "Authorization: Bearer ${TOKEN}" \
           "https://artifactregistry.googleapis.com/v1/projects/PROJECT/locations/REGION/repositories/REPO"
```

遇到 Cloud Run 容器啟動失敗時，先看 log：
```bash
gcloud logging read 'resource.type="cloud_run_revision"' \
  --project=PROJECT_ID --limit=20 \
  --format="value(timestamp, textPayload, jsonPayload.message)"
```
