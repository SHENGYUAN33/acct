"""Admin Router — 系統管理操作。"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from core.config import settings
from core.database import get_db
from core.response import ok
from routers.auth import get_current_user
from services import line_service

logger = logging.getLogger(__name__)

# 需 JWT 認證的管理端點
router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_user)],
)

# 不需 JWT、由 Cloud Scheduler 以共享密鑰標頭呼叫的維運端點
ops_router = APIRouter(prefix="/api/v1/admin", tags=["admin-ops"])


# ---------------------------------------------------------------------------
# 需 JWT 的管理端點
# ---------------------------------------------------------------------------

@router.post("/setup-rich-menu", response_model=dict)
def setup_rich_menu(_: str = Depends(get_current_user)) -> dict:
    """
    建立並設定 LINE Bot 預設 Rich Menu。
    需要有效的 LINE_CHANNEL_ACCESS_TOKEN。
    """
    rich_menu_id = line_service.setup_rich_menu()
    return ok(data={"rich_menu_id": rich_menu_id}, message="Rich Menu 設定完成")


# ---------------------------------------------------------------------------
# 維運端點（共享密鑰驗證，供 Cloud Scheduler 呼叫）
# ---------------------------------------------------------------------------

@ops_router.post("/cleanup-liff", include_in_schema=False)
def cleanup_liff(
    x_cleanup_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """
    清理過期 LIFF Session 與其圖片（取代原 APScheduler 每日凌晨排程）。

    由 Cloud Scheduler 每日呼叫，以共享密鑰標頭 X-Cleanup-Token 驗證，
    不使用 JWT（排程器無法登入）。CLEANUP_TOKEN 未設定時一律拒絕，避免誤開放。
    """
    if not settings.cleanup_token or x_cleanup_token != settings.cleanup_token:
        raise HTTPException(status_code=401, detail="未授權")

    from services.liff_service import cleanup_expired_sessions

    result = cleanup_expired_sessions(db)
    logger.info("admin: LIFF 清理完成 — %s", result)
    return ok(data=result, message="LIFF 清理完成")
