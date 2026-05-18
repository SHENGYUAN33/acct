"""LINE Service —下載內容與發送回覆訊息的輔助函式。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.expense import Expense
    from schemas.ocr import VoucherOCRResult

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    FlexBubble,
    FlexBox,
    FlexButton,
    FlexMessage,
    FlexText,
    MessageAction,
    MessagingApi,
    MessagingApiBlob,
    PostbackAction,
    PushMessageRequest,
    QuickReply,
    QuickReplyItem,
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


def get_line_api() -> MessagingApi:
    return MessagingApi(ApiClient(_line_config))


def reply_text(reply_token: str, text: str) -> None:
    """回覆純文字訊息給 LINE 使用者。"""
    api = get_line_api()
    req = ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(text=text)],
    )
    api.reply_message(req)


def reply_with_dept_selection(reply_token: str) -> None:
    """發送附有組別 Quick Reply 按鈕的文字訊息。"""
    from core.config import settings

    api = get_line_api()
    quick_reply = QuickReply(
        items=[
            QuickReplyItem(action=MessageAction(label=dept, text=dept))
            for dept in settings.departments
        ]
    )
    req = ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(text="請選擇您所屬的組別 👇", quick_reply=quick_reply)],
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

        api = get_line_api()
        message_text = (
            f"上傳日期：{upload_date or '無'}\n"
            f"憑證類別：{categories_display}\n"
            f"發票號碼：{invoice_number or '無'}\n"
            f"發票金額：{total_amount or '無'}\n\n"
            "此發票已退回"
        )
        req = PushMessageRequest(
            to=line_user_id,
            messages=[TextMessage(text=message_text)],
        )
        api.push_message(req)
        logger.info("退回通知（純文字）已推播給 line_user_id=%s", line_user_id)
    except Exception as e:
        logger.error(
            "LINE 推播退回通知失敗，line_user_id=%s: %s", line_user_id, e, exc_info=True
        )


_RICH_MENU_NAME = "AcctAssist Main Menu v5 (LIFF)"
_LIFF_URL = "https://liff.line.me/2010115806-blToY7nZ"
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
        api = get_line_api()
        req = PushMessageRequest(
            to=line_user_id,
            messages=[TextMessage(text=text)],
        )
        api.push_message(req)
    except Exception as e:
        logger.error("LINE push_text 失敗，line_user_id=%s: %s", line_user_id, e, exc_info=True)


async def push_batch_summary(
    line_user_id: str,
    expense: "Expense",
    ocr_results: list["VoucherOCRResult"],
) -> None:
    """
    批次報帳完成後 push 摘要 Flex Message 給使用者。

    依照 G1 通過設計稿（static/mockup/sprint2/flex_message_design.html）：
    Hero 區 + 憑證類型明細列表 + 合計金額 + 組別 / 備註 / 案件編號 + 確認/重新編輯按鈕。
    """
    from decimal import Decimal

    # 憑證類型對應 emoji 與中文標籤（新增 10 個頂層類別）
    CATEGORY_META: dict[str, tuple[str, str]] = {
        "INVOICE":        ("🧾", "發票"),
        "RECEIPT":        ("📋", "收據"),
        "LABOR_SERVICE":  ("👤", "勞報單"),
        "TRANSPORTATION": ("🚌", "交通費"),
        "CREDIT_NOTE":    ("↩️", "退貨折讓"),
        "INSURANCE":      ("🛡️", "保險費"),
        "UTILITY":        ("💡", "水電費"),
        "RENTAL":         ("🏢", "租金"),
        "ACCOMMODATION":  ("🏨", "住宿費"),
        "POSTAGE":        ("📮", "郵資"),
    }

    # 統計各類別數量與金額小計
    category_count: dict[str, int] = {}
    category_amount: dict[str, Decimal] = {}
    non_voucher_count: int = 0

    for result in ocr_results:
        if not result.success:
            continue
        if not result.is_voucher or not result.voucher_category:
            non_voucher_count += 1
            continue
        cat = result.voucher_category
        category_count[cat] = category_count.get(cat, 0) + 1
        if result.total_amount is not None:
            try:
                category_amount[cat] = (
                    category_amount.get(cat, Decimal("0")) + Decimal(str(result.total_amount))
                )
            except Exception:
                pass

    # 合計（直接使用 Expense 已彙整的值，確保與 DB 一致）
    total_amount: Decimal | None = expense.total_amount

    # ── 建立憑證明細行（FlexBox per row）──────────────────────────
    voucher_rows: list[FlexBox] = []
    for cat, (icon, label) in CATEGORY_META.items():
        if cat not in category_count:
            continue
        count = category_count[cat]
        amt = category_amount.get(cat)
        if amt is not None:
            amt_str = f"NT${amt:,.0f}"
            amt_color = "#dc2626" if amt < 0 else "#111111"
        else:
            amt_str = "未辨識"
            amt_color = "#9ca3af"

        voucher_rows.append(
            FlexBox(
                layout="horizontal",
                spacing="sm",
                contents=[
                    FlexText(text=icon, size="md", flex=0),
                    FlexText(text=label, size="sm", weight="bold", flex=2, color="#111111"),
                    FlexText(text=f"× {count} 張", size="sm", color="#6b7280", flex=1, align="center"),
                    FlexText(text=amt_str, size="sm", weight="bold", color=amt_color, flex=2, align="end"),
                ],
            )
        )

    # 非憑證照片行（如有）
    if non_voucher_count > 0:
        voucher_rows.append(
            FlexBox(
                layout="horizontal",
                spacing="sm",
                contents=[
                    FlexText(text="📦", size="md", flex=0),
                    FlexText(text="品項照片（非憑證）", size="sm", weight="bold", flex=3, color="#6b7280"),
                    FlexText(text=f"× {non_voucher_count} 張", size="sm", color="#6b7280", flex=1, align="center"),
                    FlexText(text="不計金額", size="xs", color="#9ca3af", flex=2, align="end"),
                ],
            )
        )

    # 若完全沒有任何行，補一個佔位說明
    if not voucher_rows:
        voucher_rows.append(
            FlexText(text="（無法辨識憑證類型，待人工確認）", size="sm", color="#9ca3af", wrap=True)
        )

    # 合計金額顯示
    total_str = f"NT${total_amount:,.0f}" if total_amount is not None else "待人工確認"

    # 備註（截取至 50 字防止過長）
    description = (expense.user_description or "").strip()
    if len(description) > 50:
        description = description[:50] + "…"

    # ── 組裝 Flex Bubble ───────────────────────────────────────────
    detail_rows: list[FlexBox] = [
        FlexBox(
            layout="horizontal",
            spacing="sm",
            contents=[
                FlexText(text="所屬組別", size="xs", color="#9ca3af", flex=2),
                FlexText(
                    text=expense.uploader_dept or "未設定",
                    size="sm",
                    weight="bold",
                    color="#1d4ed8",
                    flex=5,
                ),
            ],
        ),
        FlexBox(
            layout="horizontal",
            spacing="sm",
            contents=[
                FlexText(text="案件編號", size="xs", color="#9ca3af", flex=2),
                FlexText(text=expense.serial_number, size="sm", color="#374151", flex=5),
            ],
        ),
    ]
    if description:
        detail_rows.insert(
            1,
            FlexBox(
                layout="horizontal",
                spacing="sm",
                contents=[
                    FlexText(text="備　　註", size="xs", color="#9ca3af", flex=2),
                    FlexText(text=description, size="sm", color="#111111", flex=5, wrap=True),
                ],
            ),
        )

    bubble = FlexBubble(
        header=FlexBox(
            layout="horizontal",
            background_color="#06c755",
            spacing="md",
            contents=[
                FlexText(text="📊", size="xxl", flex=0),
                FlexBox(
                    layout="vertical",
                    flex=1,
                    contents=[
                        FlexText(text="批次報帳摘要", weight="bold", size="lg", color="#ffffff"),
                        FlexText(text="請確認以下明細", size="xs", color="#ffffff"),
                    ],
                ),
            ],
        ),
        body=FlexBox(
            layout="vertical",
            spacing="none",
            padding_all="none",
            contents=[
                # 憑證明細區
                FlexBox(
                    layout="vertical",
                    spacing="sm",
                    padding_all="16px",
                    contents=[
                        FlexText(text="憑證明細", size="xs", weight="bold", color="#9ca3af"),
                        *voucher_rows,
                    ],
                ),
                # 分隔線
                FlexBox(layout="vertical", height="1px", background_color="#f0f0f0", contents=[]),
                # 合計金額區
                FlexBox(
                    layout="horizontal",
                    spacing="sm",
                    padding_all="14px",
                    background_color="#f9fafb",
                    contents=[
                        FlexText(text="合計金額", size="sm", weight="bold", color="#374151", flex=1),
                        FlexText(text=total_str, size="xl", weight="bold", color="#06c755", align="end"),
                    ],
                ),
                # 分隔線
                FlexBox(layout="vertical", height="1px", background_color="#f0f0f0", contents=[]),
                # 詳情區：組別 / 備註 / 案件編號
                FlexBox(
                    layout="vertical",
                    spacing="sm",
                    padding_all="14px",
                    contents=detail_rows,
                ),
            ],
        ),
        footer=FlexBox(
            layout="vertical",
            spacing="none",
            contents=[
                FlexButton(
                    action=PostbackAction(label="✅ 確認送出", data="action=confirm_submit"),
                    style="primary",
                    color="#06c755",
                    height="sm",
                ),
                FlexButton(
                    action=PostbackAction(label="✏️ 重新編輯", data="action=edit_batch"),
                    style="secondary",
                    height="sm",
                ),
            ],
        ),
    )

    try:
        api = get_line_api()
        req = PushMessageRequest(
            to=line_user_id,
            messages=[FlexMessage(alt_text="批次報帳摘要，請開啟查看明細", contents=bubble)],
        )
        api.push_message(req)
        logger.info(
            "push_batch_summary 完成 line_user_id=%s serial=%s",
            line_user_id, expense.serial_number,
        )
    except Exception as e:
        logger.error(
            "push_batch_summary 失敗 line_user_id=%s: %s", line_user_id, e, exc_info=True
        )


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
