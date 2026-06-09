"""LIFF 批次上傳服務。

職責：
  1. create_session        — 建立 UploadSession，驗證 LINE ID token
  2. save_image            — 儲存圖片至 uploads/，建立 SessionImage 記錄，非同步 OCR
  3. patch_image_type      — 手動切換 is_voucher（優先於 OCR 判斷）
  4. get_session_preview   — 依 sequence_order ASC 重建費用群組預覽（純讀取）
  5. submit_session        — 鎖定 session → 呼叫 multi_split_logic_v2 → create_batch_expense
"""

import asyncio
import logging
import re
import shutil
import uuid
from datetime import datetime, timedelta, timezone

_LINE_UID_RE = re.compile(r"^U[0-9a-f]{32}$")
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import settings
from core.database import SessionLocal
from models.liff_session import SessionImage, UploadSession
from models.user import User
from schemas.liff import (
    ExpenseGroupPreview,
    PreviewImageItem,
    SessionPreviewResponse,
    SubmitSessionResponse,
    CreatedExpenseItem,
)
from schemas.ocr import VoucherOCRResult
from services import expense_service, line_service, ocr_service, relation_service
from services.storage_service import save_image as _save_image
from services.auto_split_service import (
    _ImageEntry,
    multi_split_logic_v2,
)

logger = logging.getLogger(__name__)

# LIFF Session TTL（分鐘），由 LIFF_SESSION_TTL_MINUTES 環境變數控制
LIFF_SESSION_TTL_MINUTES: int = settings.liff_session_ttl_minutes


# ---------------------------------------------------------------------------
# 1. 建立 Session
# ---------------------------------------------------------------------------

def create_session(
    db: Session,
    line_user_id: str,
) -> UploadSession:
    """
    建立 UploadSession，並確保 User 記錄存在。

    注意：LINE ID Token 驗證由 router 層完成（透過 liff.getIDToken()），
    service 層只負責 DB 操作，不重複驗證。
    """
    # 確保 User 記錄存在（若首次使用則新建）
    expense_service.get_or_create_user(db, line_user_id)

    # 查詢 user_id（FK）
    user = db.scalar(select(User).where(User.line_user_id == line_user_id))

    # 名冊綁定檢查：real_name 為 null 表示尚未完成綁定
    if not user or not user.real_name:
        line_service.set_user_state(db, line_user_id, "BINDING_REAL_NAME")
        if _LINE_UID_RE.match(line_user_id):
            line_service.push_text(
                line_user_id,
                "請聯繫管理員",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="尚未完成身分設定\n請回到 LINE 對話視窗，輸入您的姓名完成設定。\n若姓名未登記，請聯繫管理員。",
        )

    now = datetime.now(tz=timezone.utc)
    session = UploadSession(
        id=uuid.uuid4(),
        line_user_id=line_user_id,
        user_id=user.id if user else None,
        status="uploading",
        created_at=now,
        expires_at=now + timedelta(minutes=LIFF_SESSION_TTL_MINUTES),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    logger.info("liff_service.create_session: session=%s user=%s", session.id, line_user_id)
    return session


# ---------------------------------------------------------------------------
# 2. 儲存圖片 + 觸發 OCR
# ---------------------------------------------------------------------------

def _get_session_or_404(db: Session, session_id: uuid.UUID) -> UploadSession:
    """取得 UploadSession，若不存在或已過期則拋出 HTTPException。"""
    session = db.get(UploadSession, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session 不存在")
    now = datetime.now(tz=timezone.utc)
    # expires_at 可能為 naive datetime（無 tzinfo），統一轉換
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if now > expires_at:
        session.status = "expired"
        db.commit()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=f"Session 已過期（TTL {LIFF_SESSION_TTL_MINUTES} 分鐘）")
    if session.status == "submitted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session 已送出，不可再上傳圖片")
    return session


async def save_uploaded_file(upload_file: UploadFile) -> str:
    """將 UploadFile 存至 storage_path，回傳相對路徑 uploads/{uuid}.ext。"""
    return await _save_image(upload_file)


async def add_image(
    db: Session,
    session_id: uuid.UUID,
    upload_file: UploadFile,
    sequence_order: int,
) -> tuple[SessionImage, bool, None]:
    """
    儲存圖片至 uploads/ 並建立 SessionImage 記錄。
    OCR 不在此執行，由 submit 後的背景任務統一處理。

    回傳：(SessionImage, ocr_completed=False, is_voucher=None)
    """
    session = _get_session_or_404(db, session_id)

    # 驗證 sequence_order 不重複
    existing_orders = {img.sequence_order for img in session.images}
    if sequence_order in existing_orders:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"sequence_order={sequence_order} 已存在於此 session",
        )

    # 儲存檔案
    image_path = await save_uploaded_file(upload_file)

    # 建立 SessionImage 記錄（is_voucher=None，等待背景任務 OCR 後填入）
    img_record = SessionImage(
        id=uuid.uuid4(),
        session_id=session_id,
        sequence_order=sequence_order,
        image_path=image_path,
        is_voucher=None,
        manually_set=False,
    )
    db.add(img_record)
    db.commit()
    db.refresh(img_record)

    logger.info(
        "liff_service.add_image: session=%s seq=%d path=%s",
        session_id, sequence_order, image_path,
    )
    return img_record, False, None


# ---------------------------------------------------------------------------
# 3. 手動切換圖片類型
# ---------------------------------------------------------------------------

def patch_image_type(
    db: Session,
    session_id: uuid.UUID,
    image_id: uuid.UUID,
    is_voucher: bool,
) -> SessionImage:
    """使用者手動切換 is_voucher（設定 manually_set=True，優先於 OCR 判斷）。"""
    session = _get_session_or_404(db, session_id)

    img = db.scalar(
        select(SessionImage).where(
            SessionImage.id == image_id,
            SessionImage.session_id == session_id,
        )
    )
    if not img:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="圖片記錄不存在")

    img.is_voucher = is_voucher
    img.manually_set = True
    db.commit()
    db.refresh(img)
    logger.info(
        "liff_service.patch_image_type: session=%s image=%s is_voucher=%s (manual)",
        session_id, image_id, is_voucher,
    )
    return img


# ---------------------------------------------------------------------------
# 4. 確認頁預覽
# ---------------------------------------------------------------------------

def get_session_preview(
    db: Session,
    session_id: uuid.UUID,
) -> SessionPreviewResponse:
    """
    依 sequence_order ASC 重建費用群組預覽。

    群組規則與 multi_split_logic_v2 一致：
      - is_voucher=True 的圖片作為群組起點
      - 第一張 voucher 之前的物品圖歸入 orphan_images
      - is_voucher=None（OCR 尚未完成）的圖片暫時視為非憑證
    """
    session = _get_session_or_404(db, session_id)
    images: list[SessionImage] = sorted(session.images, key=lambda x: x.sequence_order)

    def _to_preview_item(img: SessionImage) -> PreviewImageItem:
        return PreviewImageItem(
            image_id=img.id,
            sequence_order=img.sequence_order,
            image_path=img.image_path,
            is_voucher=img.is_voucher,
            manually_set=img.manually_set,
        )

    # 套用與 auto_split_service 相同的切割邏輯
    voucher_indices = [
        i for i, img in enumerate(images)
        if img.is_voucher is True
    ]

    if not voucher_indices:
        # 全部圖片皆為物品照或尚未辨識 → 全歸 orphan
        return SessionPreviewResponse(
            session_id=session_id,
            status=session.status,
            groups=[],
            orphan_images=[_to_preview_item(img) for img in images],
            total_images=len(images),
        )

    first_voucher_idx = voucher_indices[0]
    orphan_images = [_to_preview_item(images[i]) for i in range(first_voucher_idx)]

    groups: list[ExpenseGroupPreview] = []
    current_voucher: SessionImage | None = None
    current_items: list[SessionImage] = []
    group_idx = 0

    for i in range(first_voucher_idx, len(images)):
        img = images[i]
        if img.is_voucher is True:
            if current_voucher is not None:
                groups.append(ExpenseGroupPreview(
                    group_index=group_idx,
                    voucher_image=_to_preview_item(current_voucher),
                    item_images=[_to_preview_item(x) for x in current_items],
                ))
                group_idx += 1
            current_voucher = img
            current_items = []
        else:
            current_items.append(img)

    if current_voucher is not None:
        groups.append(ExpenseGroupPreview(
            group_index=group_idx,
            voucher_image=_to_preview_item(current_voucher),
            item_images=[_to_preview_item(x) for x in current_items],
        ))

    return SessionPreviewResponse(
        session_id=session_id,
        status=session.status,
        groups=groups,
        orphan_images=orphan_images,
        total_images=len(images),
    )


# ---------------------------------------------------------------------------
# 5. 確認送出
# ---------------------------------------------------------------------------

def submit_session(
    db: Session,
    session_id: uuid.UUID,
    group_descriptions: dict[int, str],  # noqa: ARG001（由背景任務使用，此處僅驗證 session 狀態）
    waiting_return_ref: str | None = None,  # noqa: ARG001
) -> SubmitSessionResponse:
    """
    鎖定 session（status → submitted）並立即回傳。
    OCR、切割、建帳由 process_session_background() 背景任務執行。

    group_descriptions / waiting_return_ref 由 router 直接傳入背景任務，
    此函式不使用，但保留同樣的簽名以維持呼叫介面一致。
    """
    session = _get_session_or_404(db, session_id)
    session.status = "submitted"
    session.processing_status = "pending"
    db.commit()
    return SubmitSessionResponse(
        session_id=session_id,
        created_expenses=[],
        message="上傳已接受，費用建立中",
    )


async def process_session_background(
    session_id: uuid.UUID,
    group_descriptions: dict[int, str],
    waiting_return_ref: str | None,
    is_return_supplement: bool = False,
    wr_original_invoice: str | None = None,
    wr_original_date: str | None = None,
    wr_original_amount: float | None = None,
) -> None:
    """
    背景任務：對 session 所有圖片執行 OCR → multi_split_logic_v2 → create_batch_expense。
    使用獨立的 SessionLocal() session，與 HTTP request 的 db session 完全隔離。
    """
    db = SessionLocal()
    try:
        session = db.get(UploadSession, session_id)
        if not session:
            logger.error("process_session_background: session %s not found", session_id)
            return
        session.processing_status = "processing"
        db.commit()

        images: list[SessionImage] = sorted(session.images, key=lambda x: x.sequence_order)
        if not images:
            session.processing_status = "done"
            db.commit()
            logger.info("process_session_background: session=%s 無圖片，跳過建帳", session_id)
            return

        user = db.scalar(select(User).where(User.line_user_id == session.line_user_id))
        if not user:
            logger.error(
                "process_session_background: user not found session=%s line_user_id=%s",
                session_id, session.line_user_id,
            )
            session.processing_status = "failed"
            db.commit()
            return

        uploader_name: str = user.real_name or user.name or session.line_user_id
        uploader_dept: str = user.department or ""

        # 向後相容：舊版 waiting_return_ref → 新版退貨補件欄位橋接
        # 注意：waiting_return_ref 代表退貨物品照，對應 RETURN_SUPPLEMENT
        # 不可設 wr_original_invoice（那會觸發 VOID_REPLACE 換貨換單路徑）
        if not is_return_supplement and waiting_return_ref:
            is_return_supplement = True

        # 對所有 is_voucher=None 的圖片執行 OCR（add_image 不再執行 OCR，故全部需補跑）
        pending_ocr_tasks: list[tuple[int, SessionImage]] = [
            (i, img) for i, img in enumerate(images) if img.is_voucher is None
        ]
        if pending_ocr_tasks:
            ocr_coros = [
                ocr_service.classify_and_extract_with_retry(img.image_path)
                for _, img in pending_ocr_tasks
            ]
            # return_exceptions=True 確保單張失敗不中斷其餘圖片
            extra_results: list[VoucherOCRResult | BaseException] = list(
                await asyncio.gather(*ocr_coros, return_exceptions=True)
            )
            for (_, img), result in zip(pending_ocr_tasks, extra_results):
                if isinstance(result, BaseException):
                    logger.error(
                        "process_session_background: OCR failed session=%s seq=%d: %s",
                        session_id, img.sequence_order, result,
                    )
                    continue
                if result.success:
                    img.is_voucher = result.is_voucher
                    img.ocr_result = result.model_dump_json(
                        exclude={"success", "error", "raw_response"}
                    )
                else:
                    img.is_voucher = False
            db.commit()

        # 重新讀取（confirm after commit）
        db.refresh(session)
        images = sorted(session.images, key=lambda x: x.sequence_order)

        # 準備 _ImageEntry 清單（timestamp=0，LIFF 以 sequence_order 排序，不依賴時序）
        entries = [
            _ImageEntry(path=img.image_path, timestamp=0, message_id=str(img.id))
            for img in images
        ]

        # 從 SessionImage.ocr_result 還原完整 VoucherOCRResult
        ocr_stubs: list[VoucherOCRResult] = []
        for img in images:
            if img.ocr_result:
                try:
                    r = VoucherOCRResult.model_validate_json(img.ocr_result)
                    ocr_stubs.append(r)
                    continue
                except Exception as exc:
                    logger.warning(
                        "process_session_background: 還原 OCR JSON 失敗 session=%s seq=%d: %s",
                        session_id, img.sequence_order, exc,
                    )
            ocr_stubs.append(VoucherOCRResult(
                success=img.is_voucher is not None,
                is_voucher=img.is_voucher if img.is_voucher is not None else False,
            ))

        # 情境B：偵測到折讓單時，強制所有圖片合併為單一群組（不拆分）
        has_credit_note = is_return_supplement and any(
            r.voucher_category in ("RETURN", "CREDIT_NOTE") and r.original_invoice_number
            for r in ocr_stubs
        )

        # 切割模式：batch = 依憑證斷點切割；single = 全部視為一群組
        if has_credit_note:
            groups_raw = [([e.path for e in entries], ocr_stubs)]
            orphan_paths = []
            logger.info(
                "process_session_background: CREDIT_NOTE detected session=%s, force single group",
                session_id,
            )
        elif settings.liff_submit_mode == "batch":
            groups_raw, orphan_paths = multi_split_logic_v2(entries, ocr_stubs)
        else:
            groups_raw = [([e.path for e in entries], ocr_stubs)]
            orphan_paths = []

        # 退貨補件模式：孤立圖片不自動接合到近期報帳，直接併入 groups
        if orphan_paths and is_return_supplement:
            groups_raw.append((
                orphan_paths,
                [VoucherOCRResult(success=False, is_voucher=False)] * len(orphan_paths),
            ))
            orphan_paths = []
            logger.info(
                "process_session_background: is_return_supplement=True, redirect %d orphan image(s) into groups",
                len(groups_raw[-1][0]),
            )

        batch_group_id = uuid.uuid4() if groups_raw else None

        # 處理孤立物品圖
        if orphan_paths:
            resolved = relation_service.attach_orphan_images_to_recent_expense(
                db, user.id, orphan_paths, window_minutes=settings.orphan_window_minutes
            )
            if not resolved:
                try:
                    expense_service.create_batch_expense(
                        db=db,
                        user_id=user.id,
                        pending_images=orphan_paths,
                        ocr_results=[VoucherOCRResult(success=False, is_voucher=False)] * len(orphan_paths),
                        user_description="",
                        uploader_name=uploader_name,
                        uploader_dept=uploader_dept,
                        trigger_by="liff_orphan",
                    )
                except Exception as exc:
                    logger.error(
                        "process_session_background: orphan create_batch_expense failed session=%s: %s",
                        session_id, exc, exc_info=True,
                    )

        # 每個群組建立一筆 Expense
        for group_idx, (group_paths, group_ocr_stubs) in enumerate(groups_raw):
            description = group_descriptions.get(group_idx, "")
            try:
                expense = expense_service.create_batch_expense(
                    db=db,
                    user_id=user.id,
                    pending_images=group_paths,
                    ocr_results=group_ocr_stubs,
                    user_description=description,
                    uploader_name=uploader_name,
                    uploader_dept=uploader_dept,
                    trigger_by="liff",
                    group_id=batch_group_id,
                    skip_auto_link=is_return_supplement,
                )
                if is_return_supplement:
                    # 情境B：OCR 偵測到折讓單
                    if any(r.voucher_category in ("RETURN", "CREDIT_NOTE") and r.original_invoice_number for r in group_ocr_stubs):
                        expense.relation_type = "CREDIT_NOTE"
                    # 情境A：使用者填了舊發票號碼
                    elif wr_original_invoice:
                        expense.relation_type = "VOID_REPLACE"
                        expense.referenced_invoice_number = wr_original_invoice
                    # 情境C：填了日期＋金額
                    elif wr_original_date and wr_original_amount:
                        expense.relation_type = "RETURN_SUPPLEMENT"
                        extra = f"換貨收據，原收據日期：{wr_original_date} 金額：{wr_original_amount}"
                        expense.item_description = f"{description} | {extra}" if description else extra
                    # 未知：僅勾選補件但未填詳細資料，或舊 API waiting_return_ref 橋接
                    else:
                        expense.relation_type = "RETURN_SUPPLEMENT"
                        if waiting_return_ref:
                            expense.referenced_invoice_number = waiting_return_ref
                            ref_note = f"退貨物品照，原憑證：{waiting_return_ref}"
                            expense.item_description = (
                                f"{description} | {ref_note}" if description else ref_note
                            )
                    db.commit()
                    logger.info(
                        "process_session_background: %s group=%d serial=%s",
                        expense.relation_type, group_idx, expense.serial_number,
                    )
                logger.info(
                    "process_session_background: created expense group=%d serial=%s session=%s",
                    group_idx, expense.serial_number, session_id,
                )
            except Exception as exc:
                logger.error(
                    "process_session_background: create_batch_expense failed group=%d session=%s: %s",
                    group_idx, session_id, exc, exc_info=True,
                )

        session.processing_status = "done"
        db.commit()
        logger.info("process_session_background: session=%s done", session_id)

    except Exception as exc:
        logger.error(
            "process_session_background: FATAL session=%s: %s",
            session_id, exc, exc_info=True,
        )
        try:
            s = db.get(UploadSession, session_id)
            if s:
                s.processing_status = "failed"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
