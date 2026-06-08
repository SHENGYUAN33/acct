"""AcctAssist — FastAPI application entry point."""

import logging
import os as _os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from core.config import settings
from core.database import Base, check_db_connection, engine
from models import admin_user, liff_session, staff_roster, system_setting  # noqa: F401
from routers import admin, auth, config, expenses, files, liff, roster, webhook
from core.database import SessionLocal
from services import line_service
from services.scheduler import get_scheduled_jobs, start_scheduler, stop_scheduler

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


@app.get("/liff-app", include_in_schema=False)
@app.get("/liff-app/", include_in_schema=False)
async def serve_liff_root(request: Request) -> Response:
    """LIFF 批次報帳前端（多憑證模式）。"""
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost:8000")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    return Response(
        content=_inject_liff_vars(_liff_index, f"{proto}://{host}"),
        media_type="text/html; charset=utf-8",
        headers=_NO_CACHE_HEADERS,
    )


@app.get("/liff-single", include_in_schema=False)
@app.get("/liff-single/", include_in_schema=False)
async def serve_liff_single(request: Request) -> Response:
    """LIFF 單筆報帳前端（每次 1 筆，0–1 張憑證）。"""
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost:8000")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    return Response(
        content=_inject_liff_vars(_liff_single, f"{proto}://{host}"),
        media_type="text/html; charset=utf-8",
        headers=_NO_CACHE_HEADERS,
    )


@app.on_event("startup")
def on_startup() -> None:
    logger.info("Creating database tables if not exist...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database ready.")

    try:
        rich_menu_id = line_service.setup_rich_menu()
        logger.info("Rich Menu: %s", rich_menu_id)
    except Exception as e:
        logger.warning("Rich Menu init failed: %s", e)

    _sched_enabled = settings.enable_scheduled_batch
    _sched_times = settings.scheduled_batch_times
    _sched_tz = settings.scheduled_batch_timezone
    _db = SessionLocal()
    try:
        from models.system_setting import SystemSetting
        import json as _json
        row_enabled = _db.get(SystemSetting, "scheduler.enabled")
        row_times = _db.get(SystemSetting, "scheduler.times")
        row_tz = _db.get(SystemSetting, "scheduler.timezone")
        if row_enabled is not None:
            _sched_enabled = row_enabled.value == "true"
        if row_times is not None:
            _sched_times = _json.loads(row_times.value)
        if row_tz is not None:
            _sched_tz = row_tz.value
    except Exception as _e:
        logger.warning("Cannot read scheduler settings from DB: %s", _e)
    finally:
        _db.close()

    start_scheduler(times=_sched_times, enabled=_sched_enabled, timezone_str=_sched_tz)


@app.on_event("shutdown")
def on_shutdown() -> None:
    stop_scheduler()


@app.get("/health", tags=["health"])
def health_check() -> dict:
    db_ok = check_db_connection()
    return {
        "status": "success" if db_ok else "error",
        "data": {
            "db": "ok" if db_ok else "unreachable",
            "scheduled_jobs": get_scheduled_jobs(),
        },
        "message": "AcctAssist is running",
    }
