"""ExpenseImage schema — Pydantic models for expense_images API responses."""

import uuid
from datetime import datetime

from pydantic import BaseModel, model_validator

from core.expense_categories import key_to_label


class ExpenseImageRead(BaseModel):
    id: uuid.UUID
    expense_id: uuid.UUID
    image_url: str
    is_voucher: bool
    voucher_category: str | None
    voucher_subtype: str | None = None
    # DB 存 key（如 TRANS_TAXI），回傳前自動翻成 label（如 勞-交通費-計程車資）
    expense_category: str | None = None
    sequence_order: int
    ocr_result: str | None
    ocr_confidence: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def translate_expense_category(self) -> "ExpenseImageRead":
        self.expense_category = key_to_label(self.expense_category)
        return self


class ExpenseImageUpdate(BaseModel):
    is_voucher: bool | None = None
    voucher_category: str | None = None
    voucher_subtype: str | None = None
    # 接受 label 或 key，service 層統一 normalize 成 key 再存入 DB
    expense_category: str | None = None


class MoveImageRequest(BaseModel):
    target_expense_id: uuid.UUID
