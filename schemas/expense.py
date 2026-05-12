import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from models.expense import ExpenseStatus


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
    # GenAI OCR 擴充 — 子類型與費用科目彙總（新增欄位）
    voucher_subtypes: str | None = None     # JSON 陣列字串，如 '["HSR_TICKET","PARKING"]'
    expense_categories: str | None = None   # JSON 陣列字串，如 '["TRANSPORTATION","MEAL"]'

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

    model_config = {"from_attributes": True}


class ExpenseStatusUpdate(BaseModel):
    status: ExpenseStatus
    reason: str | None = None


class ExpenseUpdate(BaseModel):
    """Dashboard 審核表單的部分更新欄位（全部可選）。"""
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
    status: ExpenseStatus | None = None
    reject_reason: str | None = None
    # 關聯鏈欄位（可手動修正 AI 判斷錯誤）
    group_id: uuid.UUID | None = None
    relation_type: str | None = None
    is_active: bool | None = None
    void_reason: str | None = None
    referenced_invoice_number: str | None = None


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
