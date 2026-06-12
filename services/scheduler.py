"""
APScheduler 排程管理器

依設定在固定時間點批次處理所有 pending 圖片。
支援 runtime 更新（不需重啟服務）：前端呼叫 PATCH /api/v1/admin/scheduler-config
即可立即生效，設定同步存入 DB，重啟後自動還原。

設定優先順序：DB（system_settings）> .env（config.py）

⚠️  WARNING: 同 auto_split_timer，僅支援單 Worker 模式（uvicorn --workers 1）。
    多 Worker 環境下，每個 Worker 各自持有排程器，會重複觸發批次處理。
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from core.config import settings
from services.scheduled_batch_service import run_scheduled_batch

logger = logging.getLogger(__name__)

# 全域排程器實例（由 start_scheduler / stop_scheduler 管理生命週期）
_scheduler: AsyncIOScheduler | None = None


def _register_jobs(
    times: list[str],
    timezone_str: str,
) -> int:
    """
    在 _scheduler 上依時間清單注冊 CronTrigger jobs。
    回傳成功注冊數量；格式無效的時間點記 error log 並略過。
    """
    if _scheduler is None:
        return 0

    registered = 0
    for time_str in times:
        try:
            parts = time_str.strip().split(":")
            if len(parts) != 2:
                raise ValueError("格式錯誤")
            hour, minute = int(parts[0]), int(parts[1])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("時間超出範圍")

            job_id = f"scheduled_batch_{hour:02d}{minute:02d}"
            _scheduler.add_job(
                run_scheduled_batch,
                trigger=CronTrigger(hour=hour, minute=minute, timezone=timezone_str),
                id=job_id,
                name=f"每日批次報帳處理 {time_str}",
                replace_existing=True,
                misfire_grace_time=300,  # 5 分鐘內補跑（服務重啟補救）
            )
            logger.info("scheduler: 已排程 — 每日 %s（時區：%s）", time_str, timezone_str)
            registered += 1

        except (ValueError, TypeError) as exc:
            logger.error(
                "scheduler: 無效時間格式 '%s'（應為 HH:MM）：%s，已略過",
                time_str,
                exc,
            )

    return registered


def start_scheduler(
    times: list[str] | None = None,
    enabled: bool | None = None,
    timezone_str: str | None = None,
) -> None:
    """
    啟動 APScheduler。

    參數優先於 config.py 設定（由 main.py 傳入 DB 讀取的值）。
    若未傳入，使用 .env / config.py 預設值。
    """
    global _scheduler

    _enabled = enabled if enabled is not None else settings.enable_scheduled_batch
    _times = times if times is not None else settings.scheduled_batch_times
    _timezone = timezone_str if timezone_str is not None else settings.scheduled_batch_timezone

    if not _enabled:
        logger.info("scheduler: 排程已停用（enable_scheduled_batch=false），跳過啟動")
        return

    if not isinstance(_timezone, str):
        logger.warning(
            "scheduler: 時區型別無效（%s），跳過啟動（測試環境 settings mock 未設定 scheduled_batch_timezone？）",
            type(_timezone).__name__,
        )
        return

    if not _times:
        logger.warning("scheduler: 時間清單為空，跳過排程器啟動")
        return

    _scheduler = AsyncIOScheduler(timezone=_timezone)

    registered = _register_jobs(_times, _timezone)
    if registered == 0:
        logger.warning("scheduler: 所有時間格式均無效，排程器未啟動")
        _scheduler = None
        return

    # 每日凌晨 3 點清理過期 LIFF session 與圖片（固定排程，不受批次設定影響）
    from core.database import SessionLocal as _SessionLocal
    from services.liff_service import cleanup_expired_sessions as _cleanup_liff

    async def _run_cleanup_liff() -> None:
        db = _SessionLocal()
        try:
            _cleanup_liff(db)
        except Exception as exc:
            logger.error("cleanup_liff job failed: %s", exc, exc_info=True)
        finally:
            db.close()

    _scheduler.add_job(
        _run_cleanup_liff,
        trigger=CronTrigger(hour=3, minute=0, timezone=_timezone),
        id="cleanup_liff_sessions",
        name="LIFF Session 過期清理",
        replace_existing=True,
        misfire_grace_time=600,
    )

    _scheduler.start()
    logger.info("scheduler: 排程器啟動完成，共 %d 個觸發時間點 + LIFF 清理 job", registered)


def update_jobs(
    times: list[str],
    enabled: bool,
    timezone_str: str,
) -> int:
    """
    Runtime 更新排程任務（不重啟服務）。

    行為：
    - 移除所有現有的 scheduled_batch_* jobs
    - 若 enabled=True，依新時間清單重新注冊
    - 若 enabled=False，排程器保持運行但無任何 job

    回傳：成功注冊的 job 數量（enabled=False 時回傳 0）
    """
    global _scheduler

    if _scheduler is None or not _scheduler.running:
        # 排程器尚未啟動 → 依新設定啟動
        if enabled:
            start_scheduler(times=times, enabled=True, timezone_str=timezone_str)
            return len(_scheduler.get_jobs()) if _scheduler else 0
        return 0

    # 移除所有現有批次任務
    for job in _scheduler.get_jobs():
        if job.id.startswith("scheduled_batch_"):
            job.remove()

    if not enabled:
        logger.info("scheduler: 排程已停用，已移除所有批次任務")
        return 0

    registered = _register_jobs(times, timezone_str)
    logger.info("scheduler: 排程已更新，共 %d 個觸發時間點", registered)
    return registered


def stop_scheduler() -> None:
    """關閉 APScheduler。"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler: 排程器已關閉")
    _scheduler = None


def get_scheduled_jobs() -> list[dict]:
    """
    回傳目前所有排程任務的摘要（供 /health 與前端設定頁使用）。

    回傳格式：
        [{"id": "...", "name": "...", "next_run_time": "ISO8601"}, ...]
    """
    if _scheduler is None or not _scheduler.running:
        return []
    return [
        {
            "id": job.id,
            "name": job.name,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
        }
        for job in _scheduler.get_jobs()
    ]


def is_running() -> bool:
    """回傳排程器是否正在運行。"""
    return _scheduler is not None and _scheduler.running
