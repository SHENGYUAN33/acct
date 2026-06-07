"""LINE Webhook 路由 — 接收並處理來自 LINE 平台的事件。"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from starlette.requests import ClientDisconnect
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import (
    FollowEvent,
    MessageEvent,
    TextMessageContent,
)
from sqlalchemy.orm import Session

from core.config import settings
from core.database import get_db
from services import expense_service, line_service, roster_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhook"])

_parser = WebhookParser(settings.line_channel_secret)


# ---------------------------------------------------------------------------
# Webhook 主路由
# ---------------------------------------------------------------------------

@router.post("/webhook")
async def webhook(
    request: Request,
    x_line_signature: str = Header(...),
    db: Session = Depends(get_db),
) -> dict:
    try:
        body = await request.body()
    except ClientDisconnect:
        logger.warning("webhook: client disconnected before body was read, ignoring")
        return {"status": "ok"}

    try:
        events = _parser.parse(body.decode("utf-8"), x_line_signature)
    except InvalidSignatureError:
        # LINE Verify 會送空 body，允許通過以回傳 200
        if not body:
            return {"status": "ok"}
        raise HTTPException(status_code=400, detail="Invalid LINE signature")

    for event in events:
        line_user_id: str = event.source.user_id
        logger.info("webhook event: type=%s user=%s", type(event).__name__, line_user_id)

        if isinstance(event, FollowEvent):
            line_service.push_text(
                line_user_id,
                "👋 歡迎使用劇組報帳系統！\n請輸入您的【姓名】完成設定：",
            )
            continue

        if not isinstance(event, MessageEvent):
            continue

        reply_token: str = event.reply_token

        # === Onboarding 偵測：任何 MessageEvent 進入前先檢查部門 ===
        user = expense_service.get_or_create_user(db, line_user_id)

        # --- 名冊預綁定模式 ---
        if settings.enable_roster_binding:
            if user.real_name and user.department:
                # 已綁定，不回覆任何訊息
                continue

            # 未綁定使用者

            # 非文字訊息 → 顯示歡迎
            if not isinstance(event.message, TextMessageContent):
                line_service.set_user_state(db, line_user_id, "BINDING_REAL_NAME")
                line_service.reply_text(
                    reply_token,
                    "👋 歡迎使用劇組報帳系統！\n請輸入您的【姓名】完成設定：",
                )
                continue

            name_input = event.message.text.strip()
            if not name_input:
                line_service.set_user_state(db, line_user_id, "BINDING_REAL_NAME")
                line_service.reply_text(
                    reply_token,
                    "👋 歡迎使用劇組報帳系統！\n請輸入您的【姓名】完成設定：",
                )
                continue

            # 文字訊息 → 不論狀態，直接嘗試比對名冊
            line_display_name = user.name or line_service.get_user_display_name(line_user_id)
            try:
                result = roster_service.bind_line_user_by_name(
                    db, name_input, line_user_id, line_display_name=line_display_name
                )
            except Exception as exc:
                logger.error("webhook: 名冊綁定失敗 user=%s name=%r: %s", line_user_id, name_input, exc, exc_info=True)
                line_service.delete_user_state(db, line_user_id)
                line_service.reply_text(reply_token, "請聯繫管理員")
                continue

            if result is None or isinstance(result, list):
                state = line_service.get_user_state(db, line_user_id)
                step = state.get("step", "") if state else ""
                if step == "BINDING_REAL_NAME":
                    # 已看過歡迎訊息後仍找不到 → 請聯繫管理員
                    line_service.delete_user_state(db, line_user_id)
                    line_service.reply_text(reply_token, "請聯繫管理員")
                else:
                    # 第一次嘗試失敗 → 顯示歡迎引導
                    line_service.set_user_state(db, line_user_id, "BINDING_REAL_NAME")
                    line_service.reply_text(
                        reply_token,
                        "👋 歡迎使用劇組報帳系統！\n請輸入您的【姓名】完成設定：",
                    )
            else:
                expense_service.update_user_real_name(db, line_user_id, result.name)
                expense_service.update_user_department(db, line_user_id, result.department)
                line_service.delete_user_state(db, line_user_id)
                line_service.reply_text(
                    reply_token,
                    f"✅ 設定完成，{result.name}（{result.department}）您好！\n"
                    f"之後請透過選單開啟報帳頁面 📷",
                )
            continue

    return {"status": "ok"}
