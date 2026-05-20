"""Expenses Router — Dashboard API for listing and reviewing expense records."""

import csv
import io
import logging
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.config import settings
from core.database import get_db
from routers.auth import get_current_user
from models.expense import Expense, ExpenseStatus
from models.user import User
from schemas.expense import ExpenseCreate, ExpenseListResponse, ExpenseRead, ExpenseUpdate, ExpenseWithImages
from schemas.expense_image import ExpenseImageRead, ExpenseImageUpdate, MoveImageRequest
from schemas.ocr import VoucherOCRResult
from services import expense_service, line_service
from services.ocr_service import classify_and_extract_with_retry
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1",
    tags=["expenses"],
    dependencies=[Depends(get_current_user)],
)

UPLOADS_DIR = Path("uploads")
UPLOADS_DIR.mkdir(exist_ok=True)

# CSV 匯出欄位定義
CSV_HEADERS = [
    "案件編號", "ID", "上傳者", "上傳者組別", "費用提報者", "費用提報者組別",
    "上傳日期", "費用日期", "發票號碼", "含稅金額", "未稅金額", "營業稅額",
    "賣方統編", "賣方公司", "項目說明", "憑證狀態", "退件原因",
    "建立時間", "更新時間",
]


# ── GET /expenses（列表）────────────────────────────────────────────
@router.get("/expenses", response_model=dict)
def list_expenses(
    status: ExpenseStatus | None = Query(default=None, description="Filter by status"),
    date_from: datetime | None = Query(default=None, description="Filter from date (ISO 8601)"),
    date_to: datetime | None = Query(default=None, description="Filter to date (ISO 8601)"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    include_inactive: bool = Query(default=False, description="是否包含已作廢（REPLACED_VOID）記錄"),
    db: Session = Depends(get_db),
) -> dict:
    total, items = expense_service.list_expenses(
        db, status=status, date_from=date_from, date_to=date_to,
        page=page, page_size=page_size, include_inactive=include_inactive,
    )
    return {
        "status": "success",
        "data": ExpenseListResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[ExpenseRead.model_validate(i) for i in items],
        ).model_dump(),
        "message": "ok",
    }


# ── GET /expenses/export（CSV 匯出）────────────────────────────────
# ⚠️ 必須在 /{expense_id} 之前定義，否則 "export" 會被解析為 UUID
@router.get("/expenses/export")
def export_expenses(
    status: ExpenseStatus | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """匯出符合篩選條件的費用清單為 CSV 檔案。"""
    items = expense_service.get_expenses_for_export(
        db, status=status, date_from=date_from, date_to=date_to, include_inactive=False
    )

    buf = io.StringIO()
    # 加 BOM 讓 Excel 正確識別 UTF-8
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(CSV_HEADERS)
    for e in items:
        writer.writerow([
            e.serial_number,
            str(e.id),
            e.uploader_name or "",
            e.uploader_dept or "",
            e.submitter_name or "",
            e.submitter_dept or "",
            e.upload_date.strftime("%Y-%m-%d %H:%M") if e.upload_date else "",
            str(e.expense_date) if e.expense_date else "",
            e.invoice_number or "",
            str(e.total_amount) if e.total_amount is not None else "",
            str(e.net_amount) if e.net_amount is not None else "",
            str(e.tax_amount) if e.tax_amount is not None else "",
            e.seller_tax_id or "",
            e.seller_name or "",
            e.item_description or "",
            e.status.value,
            e.reject_reason or "",
            e.created_at.strftime("%Y-%m-%d %H:%M"),
            e.updated_at.strftime("%Y-%m-%d %H:%M"),
        ])

    csv_content = buf.getvalue()
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=expenses.csv"},
    )


# ── POST /expenses（手動新增）──────────────────────────────────────
@router.post("/expenses", response_model=dict, status_code=201)
def create_expense(body: ExpenseCreate, db: Session = Depends(get_db)) -> dict:
    """Dashboard 手動新增費用（不透過 LINE）。"""
    expense = expense_service.create_expense_manual(db, **body.model_dump(exclude_none=True))
    return {
        "status": "success",
        "data": ExpenseRead.model_validate(expense).model_dump(),
        "message": "Expense created",
    }


# ── GET /expenses/{id}/related（查詢關聯報帳）────────────────────
# ⚠️ 必須在 /{expense_id} 之前定義，否則 "related" 會被解析為 UUID
@router.get("/expenses/{expense_id}/related", response_model=dict)
def get_related_expenses(expense_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    """查詢以此報帳為 parent 的所有關聯記錄（換單、折讓、補差額）。"""
    children = list(db.scalars(
        select(Expense).where(Expense.parent_id == expense_id)
    ).all())
    return {
        "status": "success",
        "data": [ExpenseRead.model_validate(c).model_dump() for c in children],
        "message": "ok",
    }


# ── GET /expenses/{id}/batch（批次組查詢）────────────────────────
@router.get("/expenses/{expense_id}/batch", response_model=dict)
def get_expense_batch(
    expense_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict:
    """回傳與指定 expense 同一批次（相同 group_id）的所有 Expense，含 images 子清單。"""
    expenses = expense_service.get_batch_expenses(db, expense_id)
    return {
        "status": "success",
        "data": {"expenses": [ExpenseWithImages.model_validate(e).model_dump() for e in expenses]},
        "message": "ok",
    }


# ── GET /expenses/{id}（單筆查詢）─────────────────────────────────
@router.get("/expenses/{expense_id}", response_model=dict)
def get_expense(expense_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    expense = expense_service.get_expense(db, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    return {
        "status": "success",
        "data": ExpenseRead.model_validate(expense).model_dump(),
        "message": "ok",
    }


# ── PATCH /expenses/reorder（拖曳排序持久化）─────────────────────
# ⚠️ 必須定義在 PATCH /expenses/{expense_id} 之前，避免 "reorder" 被當成 UUID 路徑參數
class ReorderRequest(BaseModel):
    ordered_ids: list[str]


@router.patch("/expenses/reorder", response_model=dict)
def reorder_expenses(
    body: ReorderRequest,
    db: Session = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    """
    依照前端傳入的 ID 清單順序，將 display_order 寫入 DB。
    前端完整傳入排列後的所有 ID，後端依序 0, 1, 2... 儲存。
    """
    expense_service.reorder_expenses(db, body.ordered_ids)
    return {"status": "success", "data": None, "message": "排序已儲存"}


# ── PATCH /expenses/{id}（部分更新欄位）───────────────────────────
@router.patch("/expenses/{expense_id}", response_model=dict)
def update_expense(
    expense_id: uuid.UUID,
    body: ExpenseUpdate,
    db: Session = Depends(get_db),
) -> dict:
    """Dashboard 審核表單儲存：部分更新 Expense 欄位（含可選的 status 變更）。"""
    updates = body.model_dump(exclude_none=True)
    expense = expense_service.update_expense(db, expense_id, updates)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    return {
        "status": "success",
        "data": ExpenseRead.model_validate(expense).model_dump(),
        "message": "Expense updated",
    }


# ── DELETE /expenses/{id}（刪除）──────────────────────────────────
@router.delete("/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    """刪除單筆費用紀錄。"""
    deleted = expense_service.delete_expense(db, expense_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Expense not found")


# ── PATCH /expenses/{id}/reject（退回單據 + LINE 推播）──────────
class RejectRequest(BaseModel):
    reason: str = ""


@router.patch("/expenses/{expense_id}/reject", response_model=dict)
def reject_expense(
    expense_id: uuid.UUID,
    body: RejectRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    退回指定報帳單：更新 DB 狀態為 REJECTED，寫入退回原因，
    並依 ENABLE_LINE_PUSH_REJECT 開關決定是否發送 LINE 推播通知。
    """
    expense = expense_service.reject_expense(db, str(expense_id), body.reason)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    # LINE 推播（功能開關控制，異常不影響 API 回應）
    if settings.enable_line_push_reject and expense.user_id:
        user = db.get(User, expense.user_id)
        if user and user.line_user_id:
            line_service.push_reject_notification(
                line_user_id=user.line_user_id,
                upload_date=str(expense.upload_date.strftime("%Y-%m-%d %H:%M")) if expense.upload_date else None,
                invoice_number=expense.invoice_number,
                total_amount=str(expense.total_amount) if expense.total_amount is not None else None,
                voucher_categories=expense.voucher_categories,
            )

    return {"status": "success", "data": None, "message": "單據已退回"}


# ── POST /expenses/{id}/images（追加補件圖片）────────────────────
@router.post("/expenses/{expense_id}/images", response_model=dict)
async def upload_expense_image(
    expense_id: uuid.UUID,
    file: UploadFile = File(...),
    image_type: Literal["expense", "item"] = Form(...),
    db: Session = Depends(get_db),
) -> dict:
    """
    追加補件圖片至對應陣列末尾：
    - image_type='expense' → 追加至 image_url[]
    - image_type='item'    → 追加至 item_image_url[]
    """
    expense = expense_service.get_expense(db, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="只允許上傳圖片檔案")

    ext = Path(file.filename or "image.jpg").suffix or ".jpg"
    filename = f"{uuid.uuid4()}{ext}"
    dest = UPLOADS_DIR / filename

    try:
        content = await file.read()
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"檔案超過大小限制（上限 {settings.max_upload_bytes // (1024 * 1024)} MB）",
            )
        dest.write_bytes(content)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"圖片儲存失敗：{e}", exc_info=True)
        raise HTTPException(status_code=500, detail="圖片儲存失敗，請稍後再試")

    updated = expense_service.append_expense_image(
        db, expense_id, f"uploads/{filename}", image_type
    )
    return {
        "status": "success",
        "data": ExpenseRead.model_validate(updated).model_dump(),
        "message": f"{image_type} image appended",
    }


# ── POST /expenses/{id}/images/replace（替換指定索引圖片）──────────
@router.post("/expenses/{expense_id}/images/replace", response_model=dict)
async def replace_expense_image(
    expense_id: uuid.UUID,
    file: UploadFile = File(...),
    image_type: Literal["expense", "item"] = Form(...),
    index: int = Form(...),
    db: Session = Depends(get_db),
) -> dict:
    """替換費用中指定索引的圖片（index 為陣列位置，從 0 開始）。"""
    expense = expense_service.get_expense(db, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="只允許上傳圖片檔案")

    ext = Path(file.filename or "image.jpg").suffix or ".jpg"
    filename = f"{uuid.uuid4()}{ext}"
    dest = UPLOADS_DIR / filename

    try:
        content = await file.read()
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"檔案超過大小限制（上限 {settings.max_upload_bytes // (1024 * 1024)} MB）",
            )
        dest.write_bytes(content)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"圖片儲存失敗：{e}", exc_info=True)
        raise HTTPException(status_code=500, detail="圖片儲存失敗，請稍後再試")

    updated = expense_service.replace_expense_image(
        db, expense_id, f"uploads/{filename}", image_type, index
    )
    if not updated:
        raise HTTPException(status_code=400, detail="索引越界或費用不存在")

    return {
        "status": "success",
        "data": ExpenseRead.model_validate(updated).model_dump(),
        "message": f"{image_type} image replaced at index {index}",
    }


# ── PATCH /expenses/{id}/images/{image_id}（修正圖片分類）────────
@router.patch("/expenses/{expense_id}/images/{image_id}", response_model=dict)
def update_expense_image_classification(
    expense_id: uuid.UUID,
    image_id: uuid.UUID,
    body: ExpenseImageUpdate,
    db: Session = Depends(get_db),
) -> dict:
    """修正 ExpenseImage 的分類欄位（is_voucher / voucher_category / expense_category 等）。"""
    image = expense_service.update_expense_image(
        db, expense_id, image_id, body.model_dump(exclude_none=True)
    )
    if not image:
        raise HTTPException(status_code=404, detail="Image not found or does not belong to this expense")
    return {
        "status": "success",
        "data": ExpenseImageRead.model_validate(image).model_dump(),
        "message": "分類已更新",
    }


# ── POST /expenses/{id}/images/{image_id}/move（跨交易搬移圖片）──
@router.post("/expenses/{expense_id}/images/{image_id}/move", response_model=dict)
def move_expense_image(
    expense_id: uuid.UUID,
    image_id: uuid.UUID,
    body: MoveImageRequest,
    db: Session = Depends(get_db),
) -> dict:
    """將 ExpenseImage 從一筆 Expense 搬移至同批次的另一筆。"""
    if body.target_expense_id == expense_id:
        raise HTTPException(status_code=400, detail="來源與目標 Expense 相同")
    image = expense_service.move_expense_image(db, expense_id, image_id, body.target_expense_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found or expense not found")
    return {
        "status": "success",
        "data": ExpenseImageRead.model_validate(image).model_dump(),
        "message": "圖片已搬移",
    }


# ── GET /expenses/{id}/images（查詢圖片清單）─────────────────────
@router.get("/expenses/{expense_id}/images", response_model=dict)
def get_expense_images(
    expense_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict:
    """查詢指定費用的所有圖片，按 sequence_order ASC 排序。"""
    expense = expense_service.get_expense(db, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    images = expense_service.get_expense_images(db, expense_id)
    return {
        "status": "success",
        "data": {
            "expense_id": str(expense_id),
            "images": [ExpenseImageRead.model_validate(img).model_dump() for img in images],
        },
        "message": "成功",
    }


# ── POST /expenses/{id}/reocr（重新辨識）─────────────────────────
@router.post("/expenses/{expense_id}/reocr", response_model=dict)
async def reocr_expense(
    expense_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict:
    """
    重新對費用影像執行 OCR，並將辨識結果更新至 DB 中的對應欄位。
    使用與 LINE Webhook 相同的 classify_and_extract_with_retry 流程。
    """
    expense = expense_service.get_expense(db, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    # 取第一張費用影像路徑（格式：uploads/xxx.jpg）
    image_urls: list = expense.image_url or []
    if not image_urls:
        raise HTTPException(status_code=400, detail="此費用無可辨識的影像")

    image_path = image_urls[0]

    # 複用 ocr_service（與 LINE 端完全相同的 OCR 流程）
    ocr: VoucherOCRResult = await classify_and_extract_with_retry(image_path)

    if not ocr.success:
        logger.error("reocr_expense 辨識失敗 expense_id=%s: %s", expense_id, ocr.error)
        raise HTTPException(status_code=422, detail=f"OCR 辨識失敗：{ocr.error}")

    # 只更新有值的欄位，避免覆蓋原有人工填寫內容
    updates: dict = {}
    if ocr.expense_date:
        updates["expense_date"] = ocr.expense_date
    if ocr.invoice_number:
        updates["invoice_number"] = ocr.invoice_number
    if ocr.total_amount is not None:
        updates["total_amount"] = Decimal(str(ocr.total_amount))
    if ocr.net_amount is not None:
        updates["net_amount"] = Decimal(str(ocr.net_amount))
    if ocr.tax_amount is not None:
        updates["tax_amount"] = Decimal(str(ocr.tax_amount))
    if ocr.seller_tax_id:
        updates["seller_tax_id"] = ocr.seller_tax_id
    if ocr.seller_name:
        updates["seller_name"] = ocr.seller_name
    if ocr.item_description:
        updates["item_description"] = ocr.item_description

    updated_expense = expense_service.update_expense(db, expense_id, updates)

    return {
        "status": "success",
        "data": ExpenseRead.model_validate(updated_expense).model_dump(),
        "message": "重新辨識完成",
    }
