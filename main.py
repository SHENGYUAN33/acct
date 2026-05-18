"""AcctAssist — FastAPI application entry point."""

import logging
import os as _os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.config import settings
from core.database import Base, check_db_connection, engine
from models import admin_user, liff_session, staff_roster, system_setting  # noqa: F401
from routers import admin, auth, expenses, liff, roster, webhook
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
app.include_router(webhook.router)
app.include_router(expenses.router)
app.include_router(roster.router)
app.include_router(liff.router)

# 靜態檔案
_BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
app.mount("/uploads", StaticFiles(directory=_os.path.join(_BASE_DIR, "uploads")), name="uploads")

_liff_index = _os.path.join(_BASE_DIR, "liff", "index.html")


@app.get("/liff-app", include_in_schema=False)
@app.get("/liff-app/", include_in_schema=False)
async def serve_liff_root() -> FileResponse:
    """LIFF 前端入口（單頁應用）。"""
    return FileResponse(_liff_index)


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
