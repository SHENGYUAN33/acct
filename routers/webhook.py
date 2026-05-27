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
from models.user_state import UserState
from services import expense_service, line_service, roster_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhook"])

_parser = WebhookParser(settings.line_channel_secret)

DEPT_OPTIONS = set(settings.departments)


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
                "👋 歡迎使用劇組報帳系統！\n\n請輸入您的【姓名】以完成帳號綁定。",
            )
            continue

        if not isinstance(event, MessageEvent):
            continue

        reply_token: str = event.reply_token

        # === Onboarding 偵測：任何 MessageEvent 進入前先檢查部門 ===
        user = expense_service.get_or_create_user(db, line_user_id)

        # --- 路徑 A：名冊預綁定模式 ---
        if settings.enable_roster_binding:
            if user.real_name and user.department:
                pass  # 已綁定，往下走
            else:
                # 非文字訊息：提示輸入姓名
                if not isinstance(event.message, TextMessageContent):
                    line_service.set_user_state(db, line_user_id, "BINDING_REAL_NAME")
                    line_service.reply_text(
                        reply_token,
                        "👋 歡迎使用劇組報帳系統！\n\n請輸入您的【姓名】完成設定：",
                    )
                    continue

                name_input = event.message.text.strip()
                if not name_input:
                    line_service.reply_text(reply_token, "⚠️ 姓名不可為空白，請重新輸入：")
                    continue

                # 任何文字訊息都直接嘗試比對名冊，不需要兩步驟
                try:
                    result = roster_service.bind_line_user_by_name(db, name_input, line_user_id)
                except Exception as exc:
                    logger.error("webhook: 名冊綁定失敗 user=%s name=%r: %s", line_user_id, name_input, exc, exc_info=True)
                    line_service.reply_text(
                        reply_token,
                        "⚠️ 綁定過程發生錯誤，請稍後再試或聯繫管理員。",
                    )
                    continue

                if result is None:
                    line_service.set_user_state(db, line_user_id, "BINDING_REAL_NAME")
                    line_service.reply_text(
                        reply_token,
                        f"⚠️ 名冊中找不到「{name_input}」，請確認姓名是否正確後重新輸入。\n"
                        f"（若有問題請聯繫管理員）",
                    )
                elif isinstance(result, list):
                    line_service.reply_text(
                        reply_token,
                        f"⚠️ 找到多筆相同姓名「{name_input}」，請聯繫管理員協助綁定。",
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

        # --- 路徑 B：原有 Onboarding 流程 ---
        elif user.department is None:
            if settings.enable_user_binding and not user.real_name:
                state = line_service.get_user_state(db, line_user_id)
                step = state.get("step", "") if state else ""
                if step == "BINDING_REAL_NAME" and isinstance(event.message, TextMessageContent):
                    real_name = event.message.text.strip()
                    if not real_name:
                        line_service.reply_text(reply_token, "⚠️ 姓名不可為空白，請重新輸入您的真實姓名：")
                        continue
                    expense_service.update_user_real_name(db, line_user_id, real_name)
                    line_service.delete_user_state(db, line_user_id)
                    line_service.reply_text(
                        reply_token,
                        f"✅ 綁定成功，{real_name}您好！請選擇您的所屬組別 👇",
                    )
                    continue
                else:
                    line_service.set_user_state(db, line_user_id, "BINDING_REAL_NAME")
                    line_service.reply_text(
                        reply_token,
                        "歡迎使用報帳系統！初次使用請先綁定身分。\n請輸入您的【真實姓名】（例如：王小明）：",
                    )
                    continue

            line_service.reply_with_dept_selection(reply_token)
            continue

        # === 部門已設定的使用者：文字訊息處理 ===

        if not isinstance(event.message, TextMessageContent):
            continue

        text = event.message.text.strip()

        # ── 部門選擇（更換組別）──
        if text in DEPT_OPTIONS:
            expense_service.update_user_department(db, line_user_id, text)
            line_service.reply_text(
                reply_token,
                f"✅ 組別已更新為『{text}』！",
            )
            continue

        # ── 其他文字：引導使用者使用選單 ──
        line_service.reply_text(
            reply_token,
            "請點選下方「報帳」選單開啟報帳頁面 📷",
        )

    return {"status": "ok"}
