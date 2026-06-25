import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, model_validator

from core.expense_categories import key_to_label
from models.expense import ExpenseStatus
from schemas.expense_image import ExpenseImageRead


class ExpenseRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    image_url: list[str] = []
    item_image_url: list[str] = []

    # System / LINE fields
    uploader_name: str | None
    uploader_dept: str | None
    submitter_name: str | None
    submitter_dept: str | None
    upload_date: datetime | None

    # AI-extracted fields
    item_description: str | None
    expense_date: date | None
    invoice_number: str | None
    total_amount: Decimal | None
    net_amount: Decimal | None
    tax_amount: Decimal | None
    seller_tax_id: str | None
    seller_name: str | None

    # 案件編號
    serial_number: str

    # Sprint 2 — 批次報帳新增欄位
    user_description: str | None = None
    image_count: int = 1
    voucher_categories: str | None = None   # JSON 陣列字串，如 '["INVOICE","RECEIPT"]'
    # Sprint 3 — 觸發來源（manual_button / auto_split / null 表示舊資料）
    trigger_by: str | None = None
    # GenAI OCR 擴充 — 子類型與費用科目彙總
    voucher_subtypes: str | None = None     # JSON 陣列字串，如 '["HSR_TICKET","PARKING"]'
    # DB 存 key 陣列，回傳前自動翻成 label 陣列（由 model_validator 處理）
    expense_categories: str | None = None

    # Workflow
    status: ExpenseStatus
    reject_reason: str | None
    created_at: datetime
    updated_at: datetime

    # 關聯鏈欄位（情境 2/3/4）
    group_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    relation_type: str | None = None
    is_active: bool = True
    void_reason: str | None = None
    referenced_invoice_number: str | None = None
    return_record: str | None = None
    possible_duplicate_of: uuid.UUID | None = None
    dismissed_from_waiting_return: bool = False
    voided_at: datetime | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def translate_expense_categories(self) -> "ExpenseRead":
        if self.expense_categories:
            try:
                keys: list[str] = json.loads(self.expense_categories)
                labels = [key_to_label(k) or k for k in keys]
                self.expense_categories = json.dumps(labels, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                pass
        return self


class ExpenseStatusUpdate(BaseModel):
    status: ExpenseStatus
    reason: str | None = None


class ExpenseUpdate(BaseModel):
    """Dashboard 審核表單的部分更新欄位（全部可選）。"""
    submitter_name: str | None = None
    submitter_dept: str | None = None
    upload_date: datetime | None = None
    expense_date: date | None = None
    invoice_number: str | None = None
    total_amount: Decimal | None = None
    net_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    seller_tax_id: str | None = None
    seller_name: str | None = None
    item_description: str | None = None
    status: ExpenseStatus | None = None
    reject_reason: str | None = None
    # 關聯鏈欄位（可手動修正 AI 判斷錯誤）
    group_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    relation_type: str | None = None
    is_active: bool | None = None
    void_reason: str | None = None
    referenced_invoice_number: str | None = None
    return_record: str | None = None
    dismissed_from_waiting_return: bool | None = None
    voucher_categories: str | None = None


class ExpenseCreate(BaseModel):
    """Dashboard 手動新增費用（不透過 LINE）。"""
    uploader_name: str | None = None
    uploader_dept: str | None = None
    submitter_name: str | None = None
    submitter_dept: str | None = None
    expense_date: date | None = None
    invoice_number: str | None = None
    total_amount: Decimal | None = None
    net_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    seller_tax_id: str | None = None
    seller_name: str | None = None
    item_description: str | None = None


class ExpenseListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ExpenseRead]


class ExpenseWithImages(ExpenseRead):
    """ExpenseRead + 已 eager load 的 ExpenseImage 清單，用於批次組 API 回應。"""
    images: list[ExpenseImageRead] = []
