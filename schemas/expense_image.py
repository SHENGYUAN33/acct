"""ExpenseImage schema — Pydantic models for expense_images API responses."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class ExpenseImageRead(BaseModel):
    id: uuid.UUID
    expense_id: uuid.UUID
    image_url: str
    is_voucher: bool
    voucher_category: str | None
    # 子類型：HSR_TICKET / FUEL / EXEMPT_INVOICE 等
    voucher_subtype: str | None = None
    # 費用科目中文名稱（對應 config/expense_categories.json categories[].label）
    expense_category: str | None = None
    sequence_order: int
    # JSON 字串，對應完整 VoucherOCRResult（含推理說明與信心分數）
    ocr_result: str | None
    # Gemini overall_confidence 分數 0.000–1.000（新增欄位）
    ocr_confidence: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ExpenseImageUpdate(BaseModel):
    is_voucher: bool | None = None
    voucher_category: str | None = None
    voucher_subtype: str | None = None
    expense_category: str | None = None


class MoveImageRequest(BaseModel):
    target_expense_id: uuid.UUID
