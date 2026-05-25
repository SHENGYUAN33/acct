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
import shutil
import uuid
from datetime import datetime, timedelta, timezone
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
from services import expense_service, ocr_service, relation_service
from services.auto_split_service import (
    _ImageEntry,
    multi_split_logic_v2,
)

logger = logging.getLogger(__name__)

# LIFF Session TTL（分鐘），預設 30 分鐘
LIFF_SESSION_TTL_MINUTES: int = 30


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
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Session 已過期（TTL 30 分鐘）")
    if session.status == "submitted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session 已送出，不可再上傳圖片")
    return session


def save_uploaded_file(upload_file: UploadFile) -> str:
    """將 UploadFile 存至 uploads/ 目錄，回傳相對路徑 uploads/{uuid}.jpg。"""
    ext = Path(upload_file.filename or "image.jpg").suffix or ".jpg"
    filename = f"{uuid.uuid4()}{ext}"
    dest = Path(settings.storage_path) / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        shutil.copyfileobj(upload_file.file, f)
    return str(dest)


async def add_image(
    db: Session,
    session_id: uuid.UUID,
    upload_file: UploadFile,
    sequence_order: int,
) -> tuple[SessionImage, bool, bool | None]:
    """
    儲存圖片並執行 OCR。

    回傳：
        (SessionImage, ocr_completed, is_voucher)
        ocr_completed=True 時 is_voucher 有值，False 時為 None
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
    image_path = save_uploaded_file(upload_file)

    # 建立 SessionImage 記錄（is_voucher=None 表示 OCR 尚未完成）
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

    # 同步執行 OCR（classify_and_extract_with_retry 已包含 retry + Semaphore 限速）
    try:
        ocr_result: VoucherOCRResult = await ocr_service.classify_and_extract_with_retry(image_path)
        img_record.is_voucher = ocr_result.is_voucher if ocr_result.success else None
        if ocr_result.success:
            img_record.ocr_result = ocr_result.model_dump_json(
                exclude={"success", "error", "raw_response"}
            )
        db.commit()
        db.refresh(img_record)
        return img_record, True, img_record.is_voucher
    except Exception as exc:
        logger.error(
            "liff_service.add_image: OCR failed session=%s seq=%d: %s",
            session_id, sequence_order, exc, exc_info=True,
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

async def submit_session(
    db: Session,
    session_id: uuid.UUID,
    group_descriptions: dict[int, str],
    waiting_return_ref: str | None = None,
) -> SubmitSessionResponse:
    """
    鎖定 session → 依 sequence_order 重跑 OCR（若 is_voucher 仍為 None）
    → multi_split_logic_v2 → create_batch_expense。

    group_descriptions: { group_index: description_text }
    waiting_return_ref: 若使用者在 LIFF 勾選「待退貨物品照」，帶入原始憑證號碼
    """
    session = _get_session_or_404(db, session_id)

    # 鎖定，防止重複送出
    session.status = "submitted"
    db.commit()

    images: list[SessionImage] = sorted(session.images, key=lambda x: x.sequence_order)
    if not images:
        return SubmitSessionResponse(
            session_id=session_id,
            created_expenses=[],
            message="Session 無圖片，跳過建帳",
        )

    # 取得 User 資訊（供 create_batch_expense 使用）
    user = db.scalar(select(User).where(User.line_user_id == session.line_user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="使用者資料不存在")

    uploader_name: str = user.real_name or user.name or session.line_user_id
    uploader_dept: str = user.department or ""

    # 針對 is_voucher=None 的圖片補跑 OCR
    pending_ocr_tasks: list[tuple[int, SessionImage]] = [
        (i, img) for i, img in enumerate(images) if img.is_voucher is None
    ]
    if pending_ocr_tasks:
        ocr_coros = [
            ocr_service.classify_and_extract_with_retry(img.image_path)
            for _, img in pending_ocr_tasks
        ]
        extra_results: list[VoucherOCRResult] = list(await asyncio.gather(*ocr_coros))
        for (_, img), result in zip(pending_ocr_tasks, extra_results):
            if result.success:
                img.is_voucher = result.is_voucher
        db.commit()

    # 重新讀取（confirm after commit）
    db.refresh(session)
    images = sorted(session.images, key=lambda x: x.sequence_order)

    # 準備 _ImageEntry 清單（timestamp=0，LIFF 以 sequence_order 排序，不依賴時序）
    entries = [
        _ImageEntry(path=img.image_path, timestamp=0, message_id=str(img.id))
        for img in images
    ]

    # 從 SessionImage.ocr_result 還原完整 VoucherOCRResult，
    # 確保 create_batch_expense 能正確萃取金額、發票號碼等欄位
    ocr_stubs: list[VoucherOCRResult] = []
    for img in images:
        if img.ocr_result:
            try:
                r = VoucherOCRResult.model_validate_json(img.ocr_result)
                ocr_stubs.append(r)
                continue
            except Exception as exc:
                logger.warning(
                    "liff_service.submit_session: 還原 OCR JSON 失敗 session=%s seq=%d: %s",
                    session_id, img.sequence_order, exc,
                )
        ocr_stubs.append(VoucherOCRResult(
            success=img.is_voucher is not None,
            is_voucher=img.is_voucher if img.is_voucher is not None else False,
        ))

    # 切割模式：batch = 依憑證斷點切割；single = 全部視為一群組
    if settings.liff_submit_mode == "batch":
        groups_raw, orphan_paths = multi_split_logic_v2(entries, ocr_stubs)
    else:
        groups_raw = [([ e.path for e in entries ], ocr_stubs)]
        orphan_paths = []

    # 待退貨補件模式：孤立圖片不自動接合到近期報帳，直接併入 groups 建立 RETURN_SUPPLEMENT
    if orphan_paths and waiting_return_ref:
        groups_raw.append((
            orphan_paths,
            [VoucherOCRResult(success=False, is_voucher=False)] * len(orphan_paths),
        ))
        orphan_paths = []
        logger.info(
            "liff_service.submit_session: waiting_return_ref=%s, redirect %d orphan image(s) into groups",
            waiting_return_ref, len(groups_raw[-1][0]),
        )

    batch_group_id = uuid.uuid4() if groups_raw else None
    created_expenses: list[CreatedExpenseItem] = []

    # 處理孤立物品圖（waiting_return_ref 時已提前清空 orphan_paths，此區塊不執行）
    orphan_attached = False
    if orphan_paths:
        resolved = relation_service.attach_orphan_images_to_recent_expense(
            db, user.id, orphan_paths, window_minutes=10
        )
        if resolved:
            orphan_attached = True
        else:
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
                    "liff_service.submit_session: orphan create_batch_expense failed session=%s: %s",
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
            )
            # LIFF Mode 2：使用者明確標記此批次為退貨物品照
            if waiting_return_ref:
                expense.relation_type = "RETURN_SUPPLEMENT"
                expense.referenced_invoice_number = waiting_return_ref
                # 將備註與待退貨憑證號碼寫入 item_description，解除配對後仍可追溯原始憑證來源
                ref_note = f"待退貨補件，原始憑證：{waiting_return_ref}"
                expense.item_description = f"{description} | {ref_note}" if description else ref_note
                db.commit()
                logger.info(
                    "liff_service.submit_session: RETURN_SUPPLEMENT group=%d serial=%s invoice=%s",
                    group_idx, expense.serial_number, waiting_return_ref,
                )
            created_expenses.append(CreatedExpenseItem(
                group_index=group_idx,
                expense_id=expense.id,
                serial_number=expense.serial_number,
            ))
            logger.info(
                "liff_service.submit_session: created expense group=%d serial=%s session=%s",
                group_idx, expense.serial_number, session_id,
            )
        except Exception as exc:
            logger.error(
                "liff_service.submit_session: create_batch_expense failed group=%d session=%s: %s",
                group_idx, session_id, exc, exc_info=True,
            )

    return SubmitSessionResponse(
        session_id=session_id,
        created_expenses=created_expenses,
        orphan_attached=orphan_attached,
        message=f"成功建立 {len(created_expenses)} 筆報帳",
    )
