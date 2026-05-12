# AcctAssist — LINE 報帳審核系統

基於 LINE Messaging API + Google Gemini OCR，讓使用者透過 LINE 上傳發票，後台自動辨識並提供 Vue3 Dashboard 進行審核。

---

## 技術棧

| 層級 | 技術 |
|------|------|
| Backend | Python 3.10+, FastAPI |
| Database | PostgreSQL 16 (Docker) |
| ORM | SQLAlchemy 2.0, Alembic |
| AI/OCR | Google Gemini API (gemini-2.5-flash) |
| Messaging | LINE Messaging API |
| Frontend | Vue 3 + TailwindCSS |

---

## 部署 SOP（新機器）

### 1. Clone 專案

```bash
git clone https://github.com/SHENGYUAN33/AcctAssist.git
cd AcctAssist
```

### 2. 建立 `.env`

```bash
cp .env.example .env
```

開啟 `.env`，填入以下真實金鑰：

| 變數 | 說明 |
|------|------|
| `LINE_CHANNEL_SECRET` | LINE Bot Channel Secret |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot Access Token |
| `GEMINI_API_KEY` | Google Gemini API Key |
| `DATABASE_URL` | PostgreSQL 連線字串，例如 `postgresql+asyncpg://user:pass@localhost:5432/acctassist` |

> `.env` 含有機敏資訊，**絕對不可提交至 git**。

### 3. 建立上傳目錄

```bash
mkdir uploads
```

### 4. 啟動 PostgreSQL（Docker）

```bash
docker compose up -d
```

### 5. 安裝 Python 依賴

```bash
pip install -r requirements.txt
```

### 6. 執行資料庫 Migration

```bash
alembic upgrade head
```

### 7. 啟動後端服務

```bash
uvicorn main:app --reload
```

服務預設運行於 `http://localhost:8000`

### 8. 啟動前端 Dashboard（開發模式）

```bash
cd frontend
npm install
npm run dev
```

---

## 目錄結構說明

```
ocr/
├── main.py                # FastAPI 入口
├── core/                  # 設定與 DB session
├── models/                # SQLAlchemy ORM
├── schemas/               # Pydantic schema
├── routers/               # API 路由（webhook + dashboard）
├── services/              # 業務邏輯（OCR、LINE、Expense）
├── alembic/versions/      # 資料庫 migration 紀錄
├── frontend/              # Vue3 Dashboard
├── uploads/               # 發票圖片暫存（不進 git）
├── .env.example           # 環境變數範本
└── docker-compose.yml     # PostgreSQL 容器定義
```

---

## API 端點

| Method | Path | 說明 |
|--------|------|------|
| `POST` | `/webhook` | LINE Webhook 接收入口 |
| `GET` | `/api/v1/expenses` | 報帳清單（支援 status / 日期過濾） |
| `GET` | `/api/v1/expenses/{id}` | 單筆報帳詳情 |
| `PUT` | `/api/v1/expenses/{id}/status` | 審核（APPROVED / REJECTED） |
| `GET` | `/health` | 健康檢查 |
