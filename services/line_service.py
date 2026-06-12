"""LINE Service —下載內容與發送回覆訊息的輔助函式。"""

from __future__ import annotations

import logging
from pathlib import Path

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
    PushMessageRequest,
    ReplyMessageRequest,
    TextMessage,
    URIAction,
)
from sqlalchemy.orm import Session

from core.config import settings
from models.user_state import UserState

logger = logging.getLogger(__name__)

_line_config = Configuration(access_token=settings.line_channel_access_token)


# ---------------------------------------------------------------------------
# User state helpers (DB-backed)
# ---------------------------------------------------------------------------

def get_user_state(db: Session, line_user_id: str) -> dict | None:
    """取得使用者目前的狀態，若不存在則回傳 None。"""
    row = db.get(UserState, line_user_id)
    if row is None:
        return None
    return {"step": row.step, "dept": row.dept}


def set_user_state(db: Session, line_user_id: str, step: str, dept: str | None = None) -> None:
    """建立或更新使用者狀態（upsert）。"""
    row = db.get(UserState, line_user_id)
    if row is None:
        row = UserState(line_user_id=line_user_id, step=step, dept=dept)
        db.add(row)
    else:
        row.step = step
        row.dept = dept
    db.commit()


def delete_user_state(db: Session, line_user_id: str) -> None:
    """刪除使用者狀態（流程完成後清除）。"""
    row = db.get(UserState, line_user_id)
    if row is not None:
        db.delete(row)
        db.commit()


def get_user_display_name(line_user_id: str) -> str | None:
    """向 LINE API 取得使用者的顯示名稱（暱稱）。失敗時回傳 None。"""
    try:
        with ApiClient(_line_config) as api_client:
            profile = MessagingApi(api_client).get_profile(line_user_id)
        return profile.display_name
    except Exception as exc:
        logger.warning("line_service.get_user_display_name: failed for user=%s: %s", line_user_id, exc)
        return None


def reply_text(reply_token: str, text: str) -> None:
    """回覆純文字訊息給 LINE 使用者。"""
    with ApiClient(_line_config) as api_client:
        api = MessagingApi(api_client)
        req = ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=text)],
        )
        api.reply_message(req)



def push_reject_notification(
    line_user_id: str,
    upload_date: str | None,
    invoice_number: str | None,
    total_amount: str | None,
    voucher_categories: str | None = None,
) -> None:
    """
    主動推播退回通知純文字訊息給 LINE 使用者。
    顯示上傳日期、憑證類別、發票號碼、發票金額，並提示重新上傳。
    包含完整 try-except，避免 LINE API 異常導致後端 Crash。
    """
    try:
        import json as _json
        categories_display = "無"
        if voucher_categories:
            try:
                parsed = _json.loads(voucher_categories)
                categories_display = "、".join(parsed) if parsed else "無"
            except Exception:
                categories_display = voucher_categories

        message_text = (
            f"上傳日期：{upload_date or '無'}\n"
            f"憑證類別：{categories_display}\n"
            f"發票號碼：{invoice_number or '無'}\n"
            f"發票金額：{total_amount or '無'}\n\n"
            "此筆報帳已退回"
        )
        req = PushMessageRequest(
            to=line_user_id,
            messages=[TextMessage(text=message_text)],
        )
        with ApiClient(_line_config) as api_client:
            MessagingApi(api_client).push_message(req)
        logger.info("退回通知（純文字）已推播給 line_user_id=%s", line_user_id)
    except Exception as e:
        logger.error(
            "LINE 推播退回通知失敗，line_user_id=%s: %s", line_user_id, e, exc_info=True
        )


_RICH_MENU_NAME = "AcctAssist Main Menu v5 (LIFF)"
_LIFF_URL = "https://liff.line.me/2010115806-UP0jctF7"
_RICH_MENU_IMAGE_PATH = Path(__file__).parent.parent / "static" / "mockup" / "sprint2" / "rich_menu.jpg"


def setup_rich_menu() -> str:
    """
    Sprint 2 版本：將 LINE Rich Menu 更新為單格「確認送出」按鈕。
    冪等設計：
    1. 先查詢並刪除現有 default Rich Menu（若存在）。
    2. 建立新的 2500×843 單格 Rich Menu，Postback data="action=confirm_submit"。
    3. 若設計圖存在則上傳圖片；不存在則跳過。
    4. 設為 default Rich Menu。
    回傳 rich_menu_id。
    """
    from linebot.v3.messaging import (
        RichMenuArea,
        RichMenuBounds,
        RichMenuRequest,
        RichMenuSize,
        URIAction as _URIAction,
    )

    with ApiClient(_line_config) as api_client:
        api = MessagingApi(api_client)
        blob_api = MessagingApiBlob(api_client)

        # ── 1. 查詢現有 default Rich Menu，若存在則刪除 ─────────────────
        try:
            current_default_id: str = api.get_default_rich_menu().rich_menu_id
            try:
                api.delete_rich_menu(current_default_id)
                logger.info("已刪除舊有 default Rich Menu：%s", current_default_id)
            except Exception as e:
                logger.warning("刪除舊有 default Rich Menu 失敗（忽略繼續）：%s", e)
        except Exception:
            logger.info("目前無 default Rich Menu，直接建立新版本。")

        # ── 2. 清除所有其他殘留 Rich Menu（防止佔用配額）───────────────
        try:
            all_menus = api.get_rich_menu_list().richmenus or []
            for stale in all_menus:
                try:
                    api.delete_rich_menu(stale.rich_menu_id)
                    logger.info("清除殘留 Rich Menu：%s (%s)", stale.name, stale.rich_menu_id)
                except Exception as e:
                    logger.warning("清除殘留 Rich Menu 失敗：%s", e)
        except Exception as e:
            logger.warning("取得 Rich Menu 清單失敗（忽略繼續）：%s", e)

        # ── 3. 建立新的單格 Rich Menu（2500×843）────────────────────────
        W, H = 2500, 843
        rich_menu = RichMenuRequest(
            size=RichMenuSize(width=W, height=H),
            selected=True,
            name=_RICH_MENU_NAME,
            chat_bar_text="開始報帳",
            areas=[
                RichMenuArea(
                    bounds=RichMenuBounds(x=0, y=0, width=W, height=H),
                    action=_URIAction(
                        label="開始報帳",
                        uri=_LIFF_URL,
                    ),
                ),
            ],
        )
        rich_menu_id: str = api.create_rich_menu(rich_menu).rich_menu_id
        logger.info("新 Rich Menu 已建立：%s", rich_menu_id)

        # ── 4. 上傳圖片（設計圖存在用設計圖；不存在自動生成佔位圖）────────
        image_bytes: bytes | None = None
        content_type = "image/jpeg"

        if _RICH_MENU_IMAGE_PATH.exists():
            image_bytes = _RICH_MENU_IMAGE_PATH.read_bytes()
            logger.info("使用設計圖：%s", _RICH_MENU_IMAGE_PATH)
        else:
            # 自動生成 2500×843 綠底佔位圖（LINE 要求上傳圖片才能 set default）
            try:
                from io import BytesIO

                from PIL import Image, ImageDraw, ImageFont

                img = Image.new("RGB", (2500, 843), color=(0, 166, 81))  # LINE 綠
                draw = ImageDraw.Draw(img)

                # 嘗試載入系統字型（Windows / Linux / macOS 路徑優先順序）
                _font_candidates = [
                    "C:/Windows/Fonts/msjh.ttc",    # Windows 微軟正黑體
                    "C:/Windows/Fonts/arial.ttf",    # Windows Arial
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
                    "/System/Library/Fonts/Helvetica.ttc",              # macOS
                ]
                font = None
                for _fp in _font_candidates:
                    try:
                        font = ImageFont.truetype(_fp, size=100)
                        break
                    except Exception:
                        continue
                if font is None:
                    font = ImageFont.load_default()

                # 畫白色圓角矩形 + 文字（純圖形，確保可辨識）
                label = "  確認送出  "
                try:
                    bbox = draw.textbbox((0, 0), label, font=font)
                    text_w = bbox[2] - bbox[0]
                    text_h = bbox[3] - bbox[1]
                    x = (2500 - text_w) // 2
                    y = (843 - text_h) // 2
                    # 白色背景框
                    pad = 30
                    draw.rounded_rectangle(
                        [x - pad, y - pad, x + text_w + pad, y + text_h + pad],
                        radius=20,
                        fill=(255, 255, 255),
                    )
                    draw.text((x, y), label, fill=(0, 166, 81), font=font)
                except Exception:
                    # 最後防線：純綠色空白圖，不畫文字
                    pass

                buf = BytesIO()
                img.save(buf, format="JPEG", quality=90)
                image_bytes = buf.getvalue()
                logger.info("設計圖不存在，已自動生成佔位圖（2500×843）")
            except Exception as e:
                logger.warning("佔位圖生成失敗：%s", e)

        if image_bytes:
            try:
                blob_api.set_rich_menu_image(
                    rich_menu_id=rich_menu_id,
                    body=image_bytes,
                    _headers={"Content-Type": content_type},
                )
                logger.info("Rich Menu 圖片上傳完成")
            except Exception as e:
                logger.warning("Rich Menu 圖片上傳失敗（不設 default）：%s", e)
                return rich_menu_id  # 無圖片不能 set default，提早返回
        else:
            logger.warning("無可用圖片，跳過 set_default_rich_menu")
            return rich_menu_id

        # ── 5. 設為 default Rich Menu（必須在圖片上傳成功後執行）──────────
        api.set_default_rich_menu(rich_menu_id)
        logger.info("Rich Menu 已設為 default，rich_menu_id=%s", rich_menu_id)

    return rich_menu_id


def push_text(line_user_id: str, text: str) -> None:
    """主動推播純文字訊息給 LINE 使用者（不需 reply_token）。"""
    try:
        req = PushMessageRequest(
            to=line_user_id,
            messages=[TextMessage(text=text)],
        )
        with ApiClient(_line_config) as api_client:
            MessagingApi(api_client).push_message(req)
    except Exception as e:
        logger.error("LINE push_text 失敗，line_user_id=%s: %s", line_user_id, e, exc_info=True)



def download_image(message_id: str, save_path: Path) -> Path:
    """
    使用官方 SDK 從 LINE Content API 下載圖片並儲存至本地。

    Args:
        message_id: 圖片事件的 LINE 訊息 ID。
        save_path: 儲存檔案的目標路徑。

    Returns:
        已儲存檔案的路徑。
    """
    with ApiClient(_line_config) as api_client:
        blob_api = MessagingApiBlob(api_client)
        content: bytes = blob_api.get_message_content(message_id)

    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(content)
    logger.info("圖片已儲存至 %s", save_path)
    return save_path
