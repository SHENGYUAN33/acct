不依賴 LIFF：業界標準規劃方式
一、問題的本質拆解
AcctAssist 的核心需求只有三件事：


① 員工能方便地拍照上傳憑證（行動端體驗）
② 後端 AI 自動辨識並分類
③ 管理員能審核、查詢、匯出
LIFF 解決的是 ①，但它帶來了「強依賴 LINE 生態」的代價。業界有更通用的解法。

二、業界主流的四種規劃方向
方向 A — Progressive Web App（PWA）
最接近現況、導入成本最低


┌─────────────────────────────────────┐
│          任何手機瀏覽器               │
│  ┌─────────────────────────────┐    │
│  │  PWA（Vue 3 / React）        │    │
│  │  ─ 加到主螢幕，像 App 一樣    │    │
│  │  ─ Service Worker 離線快取   │    │
│  │  ─ Web Push 推播通知         │    │
│  │  ─ Camera API 直接拍照       │    │
│  └─────────────────────────────┘    │
└──────────────────┬──────────────────┘
                   │ HTTPS
                   ▼
           FastAPI 後端（現有）
認證方式：Google OAuth / Microsoft Azure AD（公司帳號即身分）

優點：

無需上架 App Store，後端更新立即生效
Camera API 直接呼叫相機，不受 LINE WebKit 限制
同一個 URL 在桌機、手機、平板都能用
Service Worker 可在網路不穩時本地暫存圖片，恢復後自動送出
缺點：

iOS Safari 對 PWA 支援仍有限制（Push Notification 在 iOS 16.4 才正式支援）
需要教育員工「加到主螢幕」的操作習慣
方向 B — React Native / Flutter 原生 App
最完整的行動端體驗


┌──────────────┐  ┌──────────────┐
│   iOS App    │  │ Android App  │
│ (App Store)  │  │ (Play Store  │
│              │  │  / 企業發佈) │
└──────┬───────┘  └──────┬───────┘
       └──────────────────┘
                  │
            FastAPI 後端
認證方式：JWT + Refresh Token；整合公司 SSO（SAML / OIDC）

原生 App 帶來什麼 PWA 做不到的能力：

能力	說明
背景上傳	App 關掉後仍可繼續上傳圖片
原生相機控制	可強制要求解析度、禁止截圖
生物辨識登入	Face ID / 指紋快速解鎖
企業 MDM 管理	IT 部門可遠端推送/撤銷 App
深度推播控制	通知角標、分類通知、靜音排程
缺點：

開發成本高 2–3 倍，需維護 iOS + Android 兩個版本
App Store 審核週期（iOS 1–3 天），緊急修復無法立即生效
員工需手動更新
方向 C — 整合企業 SSO + 內部入口網站
大型企業常見方式


公司員工入口（Intranet）
         │
    SSO（Azure AD / Okta）
         │
    ┌────┴────────────────┐
    │                     │
  桌面版                行動版
  Dashboard            SPA 報帳介面
  （審核、查詢）        （上傳、追蹤）
這個模式的關鍵設計：

Single Sign-On：員工用公司 AD 帳號登入，不需另外建帳密，IT 部門可直接管控存取權限
Role-Based Access Control（RBAC）：同一系統，員工看到的是「我的報帳」，會計看到的是「所有待審核」，主管看到的是「我的部門」
稽核日誌（Audit Log）：每一筆操作都有完整紀錄，符合財務合規需求
方向 D — 直接採用 SaaS 報帳平台
中小企業快速落地的選擇

業界成熟的 SaaS 方案：

產品	市場定位
SAP Concur	大型企業，與 ERP 深度整合
Expensify	英語系市場主流，OCR 功能完整
Rydoo	歐洲市場，行動端體驗佳
iKala 鼎新	台灣市場，中文介面
適合場景：不想自建系統、快速導入、預算充足

不適合場景：有特殊業務流程、需要客製化、資料不能上雲

三、業界標準的部署架構
以「自建系統」為前提，業界標準部署如下：

3.1 整體架構圖

                      ┌──────────────┐
                      │     CDN      │  (CloudFront / Cloudflare)
                      │  (前端靜態)   │
                      └──────┬───────┘
                             │
                  ┌──────────▼──────────┐
                  │   Load Balancer      │  (AWS ALB / GCP LB)
                  │   + SSL 終止         │
                  └──────────┬──────────┘
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
    ┌──────────┐      ┌──────────┐      ┌──────────┐
    │ App Pod  │      │ App Pod  │      │ App Pod  │
    │(FastAPI) │      │(FastAPI) │      │(FastAPI) │
    └──────────┘      └──────────┘      └──────────┘
          │                  │                  │
          └──────────────────┼──────────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
   ┌─────────────┐  ┌──────────────┐  ┌──────────────┐
   │ PostgreSQL  │  │    Redis     │  │  Object      │
   │ (Primary + │  │  (Session /  │  │  Storage     │
   │  Replica)  │  │   Cache)     │  │  (圖片儲存)   │
   └─────────────┘  └──────────────┘  └──────────────┘
3.2 圖片儲存：本地 uploads/ → Cloud Object Storage
現況系統把圖片存在本地 uploads/ 目錄，這在單機環境可以，但一旦水平擴展（多個 App Pod）就會出問題——Pod A 上傳的圖片，Pod B 讀不到。

業界做法：


# 現況（本地儲存）
dest = Path(settings.storage_path) / filename
with dest.open("wb") as f:
    shutil.copyfileobj(upload_file.file, f)

# 業界標準（雲端 Object Storage）
import boto3
s3 = boto3.client('s3')
s3.upload_fileobj(upload_file.file, 'your-bucket', f'expenses/{filename}')
image_url = f"https://your-bucket.s3.amazonaws.com/expenses/{filename}"
三大雲端方案對比：

雲端平台	Object Storage	適合場景
AWS	S3	全球最成熟，台灣有北部 Region
GCP	Cloud Storage	已在用 Gemini API，同生態整合方便
Azure	Blob Storage	公司已有 O365/AD 時優先考慮
3.3 容器化部署（Docker + Kubernetes）
現況：Docker Compose 管理 PostgreSQL，App 本機運行

業界標準：


# 生產環境 Kubernetes 部署概念
Deployment:
  replicas: 3                    # 3 個副本，任一掛掉不影響服務
  strategy: RollingUpdate        # 更新時逐一替換，零停機
  resources:
    requests: { cpu: 500m, memory: 512Mi }
    limits:   { cpu: 1000m, memory: 1Gi }

HorizontalPodAutoscaler:
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70   # 忙碌時自動擴充
3.4 CI/CD Pipeline（自動化部署）

開發者 git push
        │
        ▼
  GitHub Actions
        │
  ┌─────┴──────────────────────┐
  │                            │
  ▼                            ▼
單元測試                    Docker Build
(pytest)                  推送至 Container Registry
  │                            │
  └─────────────┬──────────────┘
                ▼
          Deploy to K8s
          ┌──────────────┐
          │  Staging 環境 │  ← QA 驗收
          └──────┬───────┘
                 │ 人工核准
                 ▼
          ┌──────────────┐
          │  Production  │  ← 上線
          └──────────────┘
四、認證設計：取代 LINE 身分驗證
LIFF 透過 liff.getProfile() 解決了「誰送出這份報帳」的問題。去掉 LINE 後，業界有三種主流方案：

方案	適合對象	說明
Google Workspace OAuth	已用 Gmail 的公司	員工用公司 Google 帳號登入，一鍵授權
Microsoft Azure AD	已用 O365 的公司	整合 Teams 通知，替代 LINE 推播
自建 JWT + Email OTP	無大廠雲端依賴	較靈活，但需要自己管理帳號
五、通知推播：取代 LINE Bot
現況系統用 LINE Bot 推播「退件通知」、「審核結果」。去掉 LINE 後：

替代方案	實作難度	員工感受
Email 通知	最低，SMTP 即可	習慣，但易被忽略
Web Push（Service Worker）	中，需 HTTPS	手機跳通知，接近 App 體驗
Microsoft Teams Webhook	低	適合已用 Teams 的公司
Slack Webhook	低	適合科技業
自建推播（FCM）	高，需原生 App	最完整，但成本高
六、現況 vs 業界標準 對照表
面向	現況（AcctAssist + LIFF）	業界標準
行動端入口	LINE LIFF WebView	PWA 或 React Native App
身分驗證	LINE ID Token	Azure AD / Google OAuth / SSO
圖片儲存	本地 uploads/ 目錄	AWS S3 / GCP Cloud Storage
推播通知	LINE Bot Message API	Web Push / Teams / Email
部署方式	單機 + Docker Compose	Kubernetes + HPA 自動擴縮
CI/CD	無（手動部署）	GitHub Actions → Staging → Production
多實例支援	否（Session 在記憶體）	是（Redis Session Store）
監控告警	logging 輸出	Prometheus + Grafana / Datadog
災難復原	無	DB 每日備份 + Multi-AZ
七、遷移建議路線圖
若客戶未來要脫離 LIFF 依賴，建議分三個階段：


Phase 1（1–2 個月）：最小風險改動
─ 圖片儲存改為 GCP Cloud Storage（已在用 Gemini，同一生態）
─ 加入 Email 通知作為 LINE 推播的備援

Phase 2（2–4 個月）：前端獨立化
─ 將 liff/index.html 改建為 Vue 3 PWA
─ 整合 Google Workspace OAuth（若公司已有）
─ LIFF 與 PWA 並行運作，員工自由選擇入口

Phase 3（4–6 個月）：基礎設施現代化
─ 容器化部署至 GKE / EKS
─ 建立 CI/CD pipeline
─ 加入監控與告警儀表板
核心結論：LIFF 是一個「快速切入 LINE 生態」的戰術選擇，對台灣市場有其合理性。業界標準方向是 PWA + OAuth SSO + Cloud Storage + Container 部署，長期可維護性與擴展性更好，但前期工程投入也更大。兩條路線並不互斥，可以先 LIFF 驗證商業需求，再逐步遷移至標準架構。