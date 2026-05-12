"""
Per-user asyncio.create_task() 滑動視窗 Timer 管理器。

⚠️  WARNING: 僅支援單 Worker 模式（uvicorn --workers 1）。
    多 Worker 環境下，各 Worker 各自持有 _timers dict，Timer 無法跨 Worker 同步。
    ENABLE_AUTO_SPLIT=true 時，務必確認以單 Worker 啟動。
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

# 全域 dict: line_user_id → asyncio.Task
_timers: dict[str, asyncio.Task] = {}


async def _delayed_call(
    delay: float,
    callback: Callable[[], Awaitable[None]],
    user_id: str,
) -> None:
    """等待 delay 秒後執行 callback；CancelledError 靜默吸收（表示被按鈕取消）。"""
    try:
        await asyncio.sleep(delay)
        logger.info("auto_split_timer: firing auto-split for user=%s", user_id)
        await callback()
    except asyncio.CancelledError:
        logger.debug("auto_split_timer: cancelled for user=%s", user_id)
    except Exception as exc:
        logger.error(
            "auto_split_timer: callback raised exception user=%s: %s",
            user_id,
            exc,
            exc_info=True,
        )
    finally:
        _timers.pop(user_id, None)


def schedule(
    line_user_id: str,
    delay_seconds: float,
    callback: Callable[[], Awaitable[None]],
) -> None:
    """
    為指定用戶安排 delay_seconds 後觸發 callback（滑動視窗）。
    若已存在計時器則先取消（重設視窗）。
    """
    cancel(line_user_id)
    task = asyncio.create_task(
        _delayed_call(delay_seconds, callback, line_user_id)
    )
    _timers[line_user_id] = task
    logger.debug(
        "auto_split_timer: scheduled user=%s delay=%ds",
        line_user_id,
        int(delay_seconds),
    )


def cancel(line_user_id: str) -> bool:
    """
    取消指定用戶的計時器。
    有取消到（任務尚未完成）返回 True，否則返回 False。
    """
    task = _timers.pop(line_user_id, None)
    if task and not task.done():
        task.cancel()
        logger.debug("auto_split_timer: cancelled timer for user=%s", line_user_id)
        return True
    return False


def active_count() -> int:
    """回傳目前活躍中的 Timer 數量（監控 / 測試用）。"""
    return len(_timers)
