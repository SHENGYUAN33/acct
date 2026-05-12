"""
每日排程批次服務

排程觸發時，掃描所有仍有 pending_images 的 UserState，
依序呼叫 auto_split_service.auto_split_process() 處理。
靜默執行，不推播任何 LINE 通知。
"""

import json
import logging

from sqlalchemy import select

from core.database import SessionLocal
from models.user import User
from models.user_state import UserState
from services import auto_split_service

logger = logging.getLogger(__name__)


async def run_scheduled_batch() -> None:
    """
    排程批次入口：掃描所有有 pending 圖片的使用者，逐一執行自動切割流程。

    使用者之間序列執行，避免同時大量送出 OCR 請求觸發 Gemini RPM 429。
    auto_split_service.auto_split_process() 內部已有 Semaphore 限制單使用者並行張數。
    """
    logger.info("scheduled_batch: 開始執行排程批次處理")

    db = SessionLocal()
    try:
        # 查詢所有有 pending 圖片的 UserState
        states: list[UserState] = db.execute(
            select(UserState).where(
                UserState.pending_images.isnot(None),
                UserState.pending_images != "[]",
                UserState.pending_images != "",
            )
        ).scalars().all()

        if not states:
            logger.info("scheduled_batch: 無待處理使用者，結束")
            return

        logger.info("scheduled_batch: 發現 %d 位使用者有 pending 圖片", len(states))

        processed = 0
        skipped = 0

        for state in states:
            # 取得對應的 User 資料（uploader_name / dept）
            user: User | None = db.execute(
                select(User).where(User.line_user_id == state.line_user_id)
            ).scalar_one_or_none()

            if user is None:
                logger.warning(
                    "scheduled_batch: 找不到 User 記錄，line_user_id=%s，略過",
                    state.line_user_id,
                )
                skipped += 1
                continue

            pending_count = len(json.loads(state.pending_images or "[]"))
            logger.info(
                "scheduled_batch: 處理 line_user_id=%s，pending 圖片數=%d",
                state.line_user_id,
                pending_count,
            )

            try:
                await auto_split_service.auto_split_process(
                    line_user_id=state.line_user_id,
                    user_id=user.id,
                    uploader_name=user.real_name or user.name or state.line_user_id,
                    uploader_dept=user.department or "",
                )
                processed += 1
            except Exception as exc:
                logger.error(
                    "scheduled_batch: 處理失敗 line_user_id=%s: %s",
                    state.line_user_id,
                    exc,
                    exc_info=True,
                )
                skipped += 1

    except Exception as exc:
        logger.error("scheduled_batch: 查詢 UserState 失敗: %s", exc, exc_info=True)
    finally:
        db.close()

    logger.info(
        "scheduled_batch: 排程批次處理完成，成功=%d，略過/失敗=%d",
        processed,
        skipped,
    )
