"""AcctAssist — FastAPI application entry point."""

import logging
import os as _os
import re as _re

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from core.config import settings
from core.database import check_db_connection
from models import admin_user, liff_session, staff_roster, system_setting  # noqa: F401
from routers import admin, auth, config, expenses, files, liff, roster, webhook

logging.basicConfig(
    level=logging.DEBUG if settings.app_debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AcctAssist API",
    description="LINE 報帳與發票自動辨識審核系統",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

_cors_origins = ["*"] if settings.app_env == "development" else settings.cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(admin.ops_router)
app.include_router(config.router)
app.include_router(webhook.router)
app.include_router(expenses.router)
app.include_router(roster.router)
app.include_router(liff.router)
app.include_router(files.router)

_BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))

_liff_index  = _os.path.join(_BASE_DIR, "liff", "index.html")
_liff_single = _os.path.join(_BASE_DIR, "liff", "single.html")


def _inject_liff_vars(html_path: str, api_base: str) -> str:
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace("'{{LIFF_API_BASE}}'", f"'{api_base}'")
    content = content.replace(
        "'{{ENABLE_WAITING_RETURN_LIFF_BUTTON}}'",
        "true" if settings.enable_waiting_return_liff_button else "false",
    )
    return content


_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

# 合法主機名格式：字母/數字/連字號/點，可選 :port（1–5 位數）
_SAFE_HOST_RE = _re.compile(r"^[a-zA-Z0-9.\-]+(:[0-9]{1,5})?$")


def _get_base_url(request: Request) -> str:
    """
    從反向代理 header 安全地提取 base URL。

    x-forwarded-host 是用戶可控的 HTTP header，若未驗證直接注入 HTML，
    攻擊者可偽造惡意字串觸發 XSS（Host Header Injection）。
    此函式用 regex 白名單驗證後才使用，不合法則 fallback 到
    TCP 層的真實 Host header。
    """
    raw_forwarded = request.headers.get("x-forwarded-host", "")
    host = (
        raw_forwarded
        if raw_forwarded and _SAFE_HOST_RE.match(raw_forwarded)
        else request.headers.get("host", "localhost:8000")
    )
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    if proto not in ("http", "https"):
        proto = "http"
    return f"{proto}://{host}"


@app.get("/liff-app", include_in_schema=False)
@app.get("/liff-app/", include_in_schema=False)
async def serve_liff_root(request: Request) -> Response:
    """LIFF 批次報帳前端（多憑證模式）。"""
    return Response(
        content=_inject_liff_vars(_liff_index, _get_base_url(request)),
        media_type="text/html; charset=utf-8",
        headers=_NO_CACHE_HEADERS,
    )


@app.get("/liff-single", include_in_schema=False)
@app.get("/liff-single/", include_in_schema=False)
async def serve_liff_single(request: Request) -> Response:
    """LIFF 單筆報帳前端（每次 1 筆，0–1 張憑證）。"""
    return Response(
        content=_inject_liff_vars(_liff_single, _get_base_url(request)),
        media_type="text/html; charset=utf-8",
        headers=_NO_CACHE_HEADERS,
    )


@app.on_event("startup")
def on_startup() -> None:
    if not check_db_connection():
        logger.error("Database connection failed on startup — 請確認 PostgreSQL 已啟動並執行 alembic upgrade head")
        raise RuntimeError("Cannot connect to database")
    logger.info("Database ready.")


@app.get("/health", tags=["health"])
def health_check() -> dict:
    db_ok = check_db_connection()
    return {
        "status": "success" if db_ok else "error",
        "data": {
            "db": "ok" if db_ok else "unreachable",
        },
        "message": "AcctAssist is running",
    }
