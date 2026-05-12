"""Admin Router — 系統管理操作（需 JWT 認證）。"""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from core.config import settings
from core.database import get_db
from models.system_setting import SystemSetting
from routers.auth import get_current_user
from services import line_service
from services.scheduled_batch_service import run_scheduled_batch
from services import scheduler as scheduler_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_user)],
)

# DB keys
_KEY_ENABLED = "scheduler.enabled"
_KEY_TIMES = "scheduler.times"
_KEY_TIMEZONE = "scheduler.timezone"


# ---------------------------------------------------------------------------
# 內部 helper：讀寫 system_settings
# ---------------------------------------------------------------------------

def _read_scheduler_config(db: Session) -> dict:
    """
    從 DB 讀取排程設定；若無記錄則回傳 config.py 預設值。
    """
    def _get(key: str, default: str) -> str:
        row = db.get(SystemSetting, key)
        return row.value if row else default

    enabled_raw = _get(_KEY_ENABLED, str(settings.enable_scheduled_batch).lower())
    times_raw = _get(_KEY_TIMES, json.dumps(settings.scheduled_batch_times, ensure_ascii=False))
    timezone_raw = _get(_KEY_TIMEZONE, settings.scheduled_batch_timezone)

    return {
        "enabled": enabled_raw == "true",
        "times": json.loads(times_raw),
        "timezone": timezone_raw,
    }


def _write_scheduler_config(db: Session, enabled: bool, times: list[str], timezone: str) -> None:
    """將排程設定寫入 DB（upsert）。"""
    data = {
        _KEY_ENABLED: str(enabled).lower(),
        _KEY_TIMES: json.dumps(times, ensure_ascii=False),
        _KEY_TIMEZONE: timezone,
    }
    for key, value in data.items():
        row = db.get(SystemSetting, key)
        if row:
            row.value = value
        else:
            db.add(SystemSetting(key=key, value=value))
    db.commit()


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------

class SchedulerConfigUpdate(BaseModel):
    enabled: bool
    times: list[str]
    timezone: str = "Asia/Taipei"

    @field_validator("times")
    @classmethod
    def validate_times(cls, v: list[str]) -> list[str]:
        for t in v:
            parts = t.strip().split(":")
            if len(parts) != 2:
                raise ValueError(f"時間格式錯誤：{t!r}（應為 HH:MM）")
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError(f"時間超出範圍：{t!r}")
        return v

    @field_validator("times")
    @classmethod
    def require_times_when_enabled(cls, v: list[str]) -> list[str]:
        # 允許 enabled=False 時傳空陣列；空陣列在 enabled=True 時由路由層攔截
        return v


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

@router.post("/setup-rich-menu", response_model=dict)
def setup_rich_menu(_: str = Depends(get_current_user)) -> dict:
    """
    建立並設定 LINE Bot 預設 Rich Menu。
    需要有效的 LINE_CHANNEL_ACCESS_TOKEN。
    """
    rich_menu_id = line_service.setup_rich_menu()
    return {
        "status": "success",
        "data": {"rich_menu_id": rich_menu_id},
        "message": "Rich Menu 設定完成",
    }


@router.post("/process-pending", response_model=dict)
async def process_pending_now(background_tasks: BackgroundTasks) -> dict:
    """
    立即觸發 pending 圖片批次處理（不等待排程時間）。
    以 BackgroundTask 非同步執行，端點立即回傳，不阻塞請求。
    """
    background_tasks.add_task(run_scheduled_batch)
    logger.info("admin: 手動觸發 pending 批次處理")
    return {
        "status": "success",
        "data": None,
        "message": "批次處理已開始，請稍後重新整理頁面查看結果",
    }


@router.get("/scheduler-config", response_model=dict)
def get_scheduler_config(db: Session = Depends(get_db)) -> dict:
    """
    取得目前排程設定（DB 值優先，無 DB 記錄時回傳 .env 預設值）。
    同時回傳各排程任務的下次執行時間。
    """
    config = _read_scheduler_config(db)
    config["scheduled_jobs"] = scheduler_service.get_scheduled_jobs()
    config["is_running"] = scheduler_service.is_running()
    return {
        "status": "success",
        "data": config,
        "message": "排程設定讀取成功",
    }


@router.patch("/scheduler-config", response_model=dict)
def update_scheduler_config(
    payload: SchedulerConfigUpdate,
    db: Session = Depends(get_db),
) -> dict:
    """
    更新排程設定，立即生效（無需重啟服務）。
    設定同時寫入 DB，重啟後自動還原。
    """
    if payload.enabled and not payload.times:
        raise HTTPException(status_code=422, detail="啟用排程時，至少需設定一個觸發時間")

    # 1. 更新 APScheduler（立即生效）
    registered = scheduler_service.update_jobs(
        times=payload.times,
        enabled=payload.enabled,
        timezone_str=payload.timezone,
    )

    # 2. 持久化至 DB
    _write_scheduler_config(
        db=db,
        enabled=payload.enabled,
        times=payload.times,
        timezone=payload.timezone,
    )

    logger.info(
        "admin: 排程設定已更新 — enabled=%s times=%s timezone=%s registered=%d",
        payload.enabled,
        payload.times,
        payload.timezone,
        registered,
    )

    return {
        "status": "success",
        "data": {
            "enabled": payload.enabled,
            "times": payload.times,
            "timezone": payload.timezone,
            "registered_jobs": registered,
            "scheduled_jobs": scheduler_service.get_scheduled_jobs(),
        },
        "message": f"排程設定已更新，共 {registered} 個觸發時間點",
    }
