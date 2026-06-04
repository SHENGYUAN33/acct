import json

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql://acctassist:acctassist@localhost:5432/acctassist"

    # JWT
    jwt_secret: str = "change-this-secret-in-production"
    jwt_expire_minutes: int = 480  # 8 小時

    # LINE Messaging API
    line_channel_secret: str = ""
    line_channel_access_token: str = ""

    # Google Gemini API
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Storage
    storage_path: str = "./uploads"

    # App
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = False

    # CORS：production 時填入允許的 origin 清單（逗號分隔或 JSON array）
    cors_origins: list[str] = []

    # 圖片上傳大小上限（bytes），預設 10MB
    max_upload_bytes: int = 10 * 1024 * 1024

    # 功能開關：LINE 退回推播（設為 False 可一鍵關閉推播，不影響 DB 更新）
    enable_line_push_reject: bool = True
    # 功能開關：首次使用身分綁定（設為 False 可跳過綁定，維持舊有暱稱邏輯）
    enable_user_binding: bool = True
    # 功能開關：員工名冊預綁定模式
    # 啟用後，首次使用的 LINE 使用者需輸入員工編號完成綁定（由管理員預先匯入名冊）
    # 關閉時，維持原有 Onboarding 流程（手動輸入姓名 + 選擇組別）
    enable_roster_binding: bool = False

    # 功能開關：待退貨 — 備註文字偵測模式
    # 啟用後，備註含「待退貨 AB-12345678」格式時，自動標記 relation_type=RETURN_SUPPLEMENT
    enable_waiting_return_text_mode: bool = False
    # 功能開關：待退貨 — LIFF 顯式按鈕模式
    # 啟用後，LIFF 確認頁顯示「此上傳為退貨物品照」toggle，提交時帶入 waiting_return_ref
    enable_waiting_return_liff_button: bool = False

    # 功能開關：LIFF 送出切割模式
    # "single" = 每次送出一律建 1 筆（單筆報帳模式）
    # "batch"  = 依憑證斷點切割成多筆（批次報帳模式）
    liff_submit_mode: str = "single"

    # 功能開關：自動切割（60 秒無操作自動送出）
    # ⚠️  僅適用於單 Worker 模式（uvicorn --workers 1），多 Worker 時必須設為 False
    enable_auto_split: bool = False
    auto_split_debounce_seconds: int = 60

    # 功能開關：每日排程批次處理
    # 啟用後，依 SCHEDULED_BATCH_TIMES 在固定時間點統一處理所有 pending 圖片
    # ⚠️  同 ENABLE_AUTO_SPLIT，僅支援單 Worker 模式（uvicorn --workers 1）
    enable_scheduled_batch: bool = False
    # 批次觸發時間清單（HH:MM 格式，逗號分隔，可設多個時間點）
    # 範例：
    #   單一時間  → "20:00"
    #   雙時段    → "20:00,22:00"
    #   模擬範圍  → "20:00,20:30,21:00,21:30,22:00"
    scheduled_batch_times: list[str] = ["20:00"]
    # 排程時區（需與伺服器部署時區一致）
    scheduled_batch_timezone: str = "Asia/Taipei"

    # OCR 並行控制：最多同時送出幾個 Gemini 請求（避免 RPM 429）
    ocr_max_concurrent: int = 3
    # OCR 重試次數（含第一次；失敗後指數退避）
    ocr_max_retries: int = 3
    # 關鍵稽核欄位信心閾值：低於此值 → NEEDS_MANUAL_REVIEW（0.0–1.0）
    key_field_confidence_threshold: float = 0.8
    # LIFF 上傳 Session 過期時間（分鐘）
    liff_session_ttl_minutes: int = 30
    # 孤立物品圖向前關聯的時間視窗（分鐘）：在此視窗內的最新報帳可被補入
    orphan_window_minutes: int = 10

    # 部門清單：透過 .env 的 DEPARTMENTS 逗號分隔字串設定，無需重新部署
    departments: list[str] = [
        "製片組_一般", "製片組_場景",
        "美術組_一般", "美術組_置景", "美術組_陳設", "美術組_道具",
        "造型組_梳化", "造型組_服裝",
        "演員管理組", "特化組", "特效組", "攝影組", "燈光組", "場務組",
        "收音組", "劇本組", "導演組", "演員組", "航拍組",
        "檔案管理組", "後期剪輯", "後期特效", "公司組",
    ]

    @field_validator("scheduled_batch_times", mode="before")
    @classmethod
    def parse_scheduled_batch_times(cls, v: object) -> list[str]:
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                return json.loads(stripped)
            return [t.strip() for t in stripped.split(",") if t.strip()]
        return v

    @field_validator("departments", mode="before")
    @classmethod
    def parse_departments(cls, v: object) -> list[str]:
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                return json.loads(stripped)
            return [d.strip() for d in stripped.split(",") if d.strip()]
        return v


settings = Settings()
