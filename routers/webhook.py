"""LINE Webhook 路由 — 接收並處理來自 LINE 平台的事件。"""

import json
import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from starlette.requests import ClientDisconnect
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import (
    ImageMessageContent,
    MessageEvent,
    PostbackEvent,
    TextMessageContent,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import settings
from core.database import SessionLocal, get_db
from models.user_state import UserState
from services import auto_split_service, auto_split_timer, expense_service, line_service, roster_service
from services.expense_service import create_batch_expense
from services.ocr_service import classify_and_extract_with_retry
from schemas.ocr import VoucherOCRResult

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhook"])

_parser = WebhookParser(settings.line_channel_secret)

DEPT_OPTIONS = set(settings.departments)


# ---------------------------------------------------------------------------
# 背景任務：批次 OCR + 建立 Expense（靜默，不推播 LINE 訊息）
# ---------------------------------------------------------------------------

async def _process_batch(
    line_user_id: str,
    pending_images: list,  # Sprint 3 新格式：list[dict]，含 path/timestamp/message_id
    user_description: str,
    uploader_name: str,
    uploader_dept: str,
    user_id: uuid.UUID,
    trigger_by: str = "manual_button",
) -> None:
    """批次報帳背景任務：並行 OCR → 以憑證為切割點建立多筆 Expense。"""
    import asyncio
    from services.auto_split_service import _ImageEntry, multi_split_logic_v2
    from services import relation_service as _rel_svc

    logger.info("_process_batch 開始 user=%s 圖片數=%d", line_user_id, len(pending_images))
    try:
        # 轉換為 _ImageEntry 以供切割邏輯使用
        entries = [
            _ImageEntry(
                path=img["path"] if isinstance(img, dict) else str(img),
                timestamp=img.get("timestamp", 0) if isinstance(img, dict) else 0,
                message_id=img.get("message_id", "") if isinstance(img, dict) else "",
            )
            for img in pending_images
        ]

        ocr_tasks = [classify_and_extract_with_retry(img) for img in pending_images]
        ocr_results: list[VoucherOCRResult] = list(await asyncio.gather(*ocr_tasks))
        logger.info(
            "_process_batch OCR 完成 user=%s 成功=%d 失敗=%d",
            line_user_id,
            sum(1 for r in ocr_results if r.success),
            sum(1 for r in ocr_results if not r.success),
        )

        # 以憑證為切割點，分割成多個群組
        groups, orphan_paths = multi_split_logic_v2(entries, ocr_results)
        logger.info(
            "_process_batch 切割結果 user=%s 群組數=%d 孤立物品圖=%d",
            line_user_id, len(groups), len(orphan_paths),
        )

        db = SessionLocal()
        try:
            batch_group_id = uuid.uuid4() if groups else None

            # 孤立物品圖（憑證前的物品圖）→ 嘗試補入 10 分鐘內最近一筆報帳
            if orphan_paths:
                resolved = _rel_svc.attach_orphan_images_to_recent_expense(
                    db, user_id, orphan_paths, window_minutes=10
                )
                if not resolved:
                    # 無可關聯的近期報帳 → 獨立建立一筆人工審核單
                    orphan_ocr = [r for r in ocr_results if not r.is_voucher][: len(orphan_paths)]
                    try:
                        create_batch_expense(
                            db=db, user_id=user_id, pending_images=orphan_paths,
                            ocr_results=orphan_ocr, user_description=user_description,
                            uploader_name=uploader_name, uploader_dept=uploader_dept,
                            trigger_by=trigger_by,
                        )
                    except Exception as exc:
                        logger.error("_process_batch orphan 建立失敗 user=%s: %s", line_user_id, exc, exc_info=True)

            # 每個憑證群組建立一筆 Expense
            for idx, (group_paths, group_ocr) in enumerate(groups, start=1):
                try:
                    expense = create_batch_expense(
                        db=db,
                        user_id=user_id,
                        pending_images=group_paths,
                        ocr_results=group_ocr,
                        user_description=user_description,
                        uploader_name=uploader_name,
                        uploader_dept=uploader_dept,
                        trigger_by=trigger_by,
                        group_id=batch_group_id,
                    )
                    logger.info(
                        "_process_batch 報帳建立成功 serial=%s group=%d/%d user=%s",
                        expense.serial_number, idx, len(groups), line_user_id,
                    )
                except Exception as exc:
                    logger.error(
                        "_process_batch 第 %d 群組建立失敗 user=%s: %s",
                        idx, line_user_id, exc, exc_info=True,
                    )
        finally:
            db.close()
    except Exception as exc:
        logger.error("_process_batch 意外失敗 user=%s: %s", line_user_id, exc, exc_info=True)


# ---------------------------------------------------------------------------
# Webhook 主路由
# ---------------------------------------------------------------------------

@router.post("/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
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

        # --- PostbackEvent ---
        if isinstance(event, PostbackEvent):
            logger.info("PostbackEvent data=%r", event.postback.data)
            reply_token: str = event.reply_token
            data: str = event.postback.data  # "action=xxx&..."
            try:
                params = dict(p.split("=", 1) for p in data.split("&") if "=" in p)
            except Exception:
                params = {}

            action = params.get("action", "")

            # ── 確認送出批次報帳 ──
            if action == "confirm_submit":
                # [Sprint 3] Priority Event：取消自動切割 Timer（若有）
                if settings.enable_auto_split:
                    auto_split_timer.cancel(line_user_id)

                user = expense_service.get_or_create_user(db, line_user_id)
                state = db.get(UserState, line_user_id)
                pending_images: list = json.loads(  # Sprint 3 新格式：list[dict]，含 path/timestamp/message_id
                    state.pending_images if state and state.pending_images else "[]"
                )

                if not pending_images:
                    # 空批次防護
                    line_service.reply_text(
                        reply_token,
                        "尚未收到任何照片，請先傳送發票照片 📷",
                    )
                    continue

                # 立即回應（< 500ms）
                line_service.reply_text(reply_token, "已送出報帳")

                # 取出 pending 後立即清空（防止重複送出）
                # pending_description 可能為 JSON array（新格式），展開為純文字再傳入
                raw_desc: str = (state.pending_description or "") if state else ""
                try:
                    desc_entries = json.loads(raw_desc) if raw_desc.startswith("[") else None
                    if isinstance(desc_entries, list) and desc_entries and isinstance(desc_entries[0], dict):
                        pending_description = "\n".join(e.get("text", "") for e in desc_entries if e.get("text"))
                    else:
                        pending_description = raw_desc
                except Exception:
                    pending_description = raw_desc
                if state:
                    state.pending_images = "[]"
                    state.pending_description = ""
                    try:
                        db.commit()
                        logger.info("confirm_submit: state 清空成功 user=%s", line_user_id)
                    except Exception as exc:
                        logger.error("confirm_submit: db.commit 失敗 user=%s: %s", line_user_id, exc, exc_info=True)

                # BackgroundTask 執行 OCR + 彙整 + push
                logger.info("confirm_submit: 加入 BackgroundTask user=%s 圖片數=%d", line_user_id, len(pending_images))
                background_tasks.add_task(
                    _process_batch,
                    line_user_id=line_user_id,
                    pending_images=pending_images,
                    user_description=pending_description,
                    uploader_name=user.real_name or user.name or line_user_id,
                    uploader_dept=user.department or "",
                    user_id=user.id,
                    trigger_by="manual_button",
                )
                logger.info("confirm_submit: BackgroundTask 已加入 user=%s", line_user_id)

            # ── 重新編輯（取消本次送出，保留 pending）──
            elif action == "edit_batch":
                pass  # 不回覆，靜默取消

            continue

        if not isinstance(event, MessageEvent):
            continue

        reply_token: str = event.reply_token

        # === Onboarding 偵測：任何 MessageEvent 進入前先檢查部門 ===
        user = expense_service.get_or_create_user(db, line_user_id)

        # --- 路徑 A：名冊預綁定模式 ---
        if settings.enable_roster_binding:
            if user.real_name and user.department:
                pass  # 已綁定，往下走報帳流程
            else:
                state = line_service.get_user_state(db, line_user_id)
                step = state.get("step", "") if state else ""

                if step == "BINDING_REAL_NAME" and isinstance(event.message, TextMessageContent):
                    name_input = event.message.text.strip()
                    if not name_input:
                        line_service.reply_text(reply_token, "⚠️ 姓名不可為空白，請重新輸入：")
                        continue

                    result = roster_service.bind_line_user_by_name(db, name_input, line_user_id)

                    if result is None:
                        # 名冊中找不到此姓名
                        line_service.reply_text(
                            reply_token,
                            f"⚠️ 名冊中找不到「{name_input}」，請確認姓名是否正確後重新輸入。\n"
                            f"（若有問題請聯繫製片組）",
                        )
                    elif isinstance(result, list):
                        # 同名多筆
                        line_service.reply_text(
                            reply_token,
                            f"⚠️ 找到多筆相同姓名「{name_input}」，請聯繫管理員協助綁定。",
                        )
                    else:
                        # 綁定成功
                        expense_service.update_user_real_name(db, line_user_id, result.name)
                        expense_service.update_user_department(db, line_user_id, result.department)
                        line_service.delete_user_state(db, line_user_id)
                        line_service.reply_text(
                            reply_token,
                            f"✅ 設定完成，{result.name}（{result.department}）您好！\n"
                            f"之後直接上傳發票照片即可報帳 📷",
                        )
                    continue
                else:
                    line_service.set_user_state(db, line_user_id, "BINDING_REAL_NAME")
                    line_service.reply_text(
                        reply_token,
                        "👋 歡迎使用劇組報帳系統！\n\n"
                        "初次使用請輸入您的【姓名】完成設定：",
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

        # === 部門已設定的使用者 ===

        # --- 文字訊息 ---
        if isinstance(event.message, TextMessageContent):
            text = event.message.text.strip()

            # ── 部門選擇（更換組別）──
            if text in DEPT_OPTIONS:
                expense_service.update_user_department(db, line_user_id, text)
                line_service.reply_text(
                    reply_token,
                    f"✅ 組別已更新為『{text}』！請直接上傳發票/收據照片開始報帳 📷",
                )
                continue

            # ── 進度查詢：指定單號（EXP-YYYYMM-NNNN）──
            if re.fullmatch(r"EXP-\d{6}-\d{4}", text, re.IGNORECASE):
                serial = text.upper()
                target = expense_service.get_expense_by_serial_number(db, serial)
                if not target:
                    line_service.reply_text(reply_token, f"❌ 查無單號「{serial}」，請確認後再試。")
                else:
                    status_map = {
                        "PENDING": "🔄 審核中",
                        "APPROVED": "✅ 已核准",
                        "REJECTED": "❌ 已退回",
                        "NEEDS_MANUAL_REVIEW": "⚠️ 人工審核中",
                        "SUPPLEMENTED": "⚠️ 已補件",
                        "WAITING_RETURN": "📦 待退貨（未結清）",
                        "COMPLETED": "✅ 已結清",
                        "REPLACED_VOID": "🚫 已作廢（換單）",
                    }
                    status_text = status_map.get(target.status.value, target.status.value)
                    reject_line = f"\n退回原因：{target.reject_reason}" if target.reject_reason else ""
                    line_service.reply_text(
                        reply_token,
                        f"📋 報帳查詢結果\n\n"
                        f"單號：{target.serial_number}\n"
                        f"金額：{target.total_amount or '未辨識'}\n"
                        f"日期：{target.expense_date or '未辨識'}\n"
                        f"狀態：{status_text}{reject_line}",
                    )
                continue

            # ── 進度查詢：最近 3 筆 ──
            if text in ("查詢進度", "查詢"):
                recent = expense_service.get_recent_expenses_by_user(db, user.id, limit=3)
                if not recent:
                    line_service.reply_text(
                        reply_token,
                        "目前尚無報帳紀錄。\n請直接上傳發票/收據照片開始報帳。",
                    )
                else:
                    status_map = {
                        "PENDING": "🔄 審核中",
                        "APPROVED": "✅ 已核准",
                        "REJECTED": "❌ 已退回",
                        "NEEDS_MANUAL_REVIEW": "⚠️ 人工審核中",
                        "SUPPLEMENTED": "⚠️ 已補件",
                        "WAITING_RETURN": "📦 待退貨（未結清）",
                        "COMPLETED": "✅ 已結清",
                        "REPLACED_VOID": "🚫 已作廢（換單）",
                    }
                    lines = ["📋 您的最近報帳紀錄：\n"]
                    num_icons = ["1️⃣", "2️⃣", "3️⃣"]
                    for i, e in enumerate(recent):
                        status_text = status_map.get(e.status.value, e.status.value)
                        lines.append(
                            f"{num_icons[i]} {e.serial_number}\n"
                            f"   💰 {e.total_amount or '未辨識'} ｜ 📅 {e.expense_date or '未辨識'}\n"
                            f"   狀態：{status_text}"
                        )
                    line_service.reply_text(reply_token, "\n\n".join(lines))
                continue

            # ── 文字確認送出（電腦版 LINE 無 Rich Menu 時使用）──
            if text in ("送出", "確認送出", "送出報帳", "確認"):
                if settings.enable_auto_split:
                    auto_split_timer.cancel(line_user_id)
                state = db.get(UserState, line_user_id)
                pending_images: list = json.loads(
                    state.pending_images if state and state.pending_images else "[]"
                )
                if not pending_images:
                    line_service.reply_text(reply_token, "尚未收到任何照片，請先傳送發票照片 📷")
                    continue
                line_service.reply_text(reply_token, "已送出報帳")
                raw_desc: str = (state.pending_description or "") if state else ""
                try:
                    desc_entries = json.loads(raw_desc) if raw_desc.startswith("[") else None
                    if isinstance(desc_entries, list) and desc_entries and isinstance(desc_entries[0], dict):
                        pending_description = "\n".join(e.get("text", "") for e in desc_entries if e.get("text"))
                    else:
                        pending_description = raw_desc
                except Exception:
                    pending_description = raw_desc
                if state:
                    state.pending_images = "[]"
                    state.pending_description = ""
                    try:
                        db.commit()
                    except Exception as exc:
                        logger.error("text confirm_submit: db.commit 失敗 user=%s: %s", line_user_id, exc, exc_info=True)
                background_tasks.add_task(
                    _process_batch,
                    line_user_id=line_user_id,
                    pending_images=pending_images,
                    user_description=pending_description,
                    uploader_name=user.real_name or user.name or line_user_id,
                    uploader_dept=user.department or "",
                    user_id=user.id,
                    trigger_by="manual_button",
                )
                continue

            # ── 非指令文字 → 累積備註（含時間戳，供 auto_split 依時序分配群組）──
            db_state = db.get(UserState, line_user_id)
            if db_state is None:
                db_state = UserState(
                    line_user_id=line_user_id,
                    step="COLLECTING",
                    dept=user.department,
                )
                db.add(db_state)
            # 新格式：JSON array of {text, timestamp}；向後相容舊純字串
            existing_raw = db_state.pending_description or ""
            try:
                text_entries: list = json.loads(existing_raw) if existing_raw.startswith("[") else []
            except Exception:
                text_entries = []
            text_entries.append({"text": text, "timestamp": event.timestamp})
            db_state.pending_description = json.dumps(text_entries, ensure_ascii=False)
            db.commit()
            # 不回覆，靜默累積備註

        # --- 圖片訊息 ---
        elif isinstance(event.message, ImageMessageContent):
            message_id = event.message.id
            save_dir = Path(settings.storage_path)
            save_path = save_dir / f"{uuid.uuid4()}.jpg"

            state = line_service.get_user_state(db, line_user_id)
            step = state.get("step", "") if state else ""

            # ── 一般批次收集模式（COLLECTING）──
            try:
                # 1. 下載圖片
                line_service.download_image(message_id, save_path)

                # 2. 累積至 pending_images（SELECT FOR UPDATE 防競態）
                with db.begin_nested():
                    db_state = db.execute(
                        select(UserState)
                        .where(UserState.line_user_id == line_user_id)
                        .with_for_update()
                    ).scalar_one_or_none()
                    if db_state is None:
                        db_state = UserState(
                            line_user_id=line_user_id,
                            step="COLLECTING",
                            dept=user.department,
                        )
                        db.add(db_state)
                    images: list = json.loads(db_state.pending_images or "[]")
                    # [Sprint 3] 新格式：含 timestamp + message_id，供 auto_split 排序與追蹤
                    images.append({
                        "path": str(save_path),
                        "timestamp": event.timestamp,
                        "message_id": message_id,
                    })
                    db_state.pending_images = json.dumps(images, ensure_ascii=False)
                db.commit()

                # [Sprint 3] 若自動切割開關開啟，排程滑動視窗 Timer
                if settings.enable_auto_split:
                    _captured_user_id = user.id
                    _captured_name = user.real_name or user.name or line_user_id
                    _captured_dept = user.department or ""
                    _captured_uid = line_user_id

                    async def _auto_split_callback() -> None:
                        await auto_split_service.auto_split_process(
                            line_user_id=_captured_uid,
                            user_id=_captured_user_id,
                            uploader_name=_captured_name,
                            uploader_dept=_captured_dept,
                        )

                    auto_split_timer.schedule(
                        line_user_id,
                        float(settings.auto_split_debounce_seconds),
                        _auto_split_callback,
                    )

                # 不回覆，靜默累積圖片

            except Exception as exc:
                logger.error("Webhook image collect error: %s", exc, exc_info=True)

        # --- 貼圖、語音、影片等不支援的訊息類型：靜默忽略 ---
        else:
            pass

    return {"status": "ok"}
