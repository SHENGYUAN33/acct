import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class ExpenseStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"
    WAITING_RETURN = "WAITING_RETURN"
    REPLACED_VOID = "REPLACED_VOID"


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # System / LINE fields
    uploader_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    uploader_dept: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submitter_dept: Mapped[str | None] = mapped_column(String(64), nullable=True)
    upload_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )

    # Image references (ARRAY of paths, e.g. ["uploads/abc.jpg", "uploads/def.jpg"])
    image_url: Mapped[list[str]] = mapped_column(
        ARRAY(String(512)), nullable=False, server_default='{}', default=list
    )
    item_image_url: Mapped[list[str]] = mapped_column(
        ARRAY(String(512)), nullable=False, server_default='{}', default=list
    )

    # AI-extracted fields (nullable — may fail OCR)
    submitter_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    item_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    expense_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    seller_tax_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    seller_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Legacy field — kept for DB compatibility, no longer written by application
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # 案件編號（由 PostgreSQL sequence 自動產生，格式：EXP-YYYYMM-NNNN）
    serial_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)

    # Workflow
    status: Mapped[ExpenseStatus] = mapped_column(
        Enum(ExpenseStatus, name="expense_status"),
        nullable=False,
        default=ExpenseStatus.PENDING,
        index=True,
    )
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Multi-image batch fields
    user_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_count: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    # JSON array 字串，記錄此次報帳包含哪些憑證類型
    voucher_categories: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON array 字串，記錄各圖片的憑證子類型，e.g. '["HSR_TICKET","PARKING"]'
    voucher_subtypes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON array 字串，記錄各圖片的費用科目，e.g. '["TRANSPORTATION","MEAL"]'
    expense_categories: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 觸發來源：'manual_button'（使用者按鈕）| 'auto_split'（60 秒自動切割）| null（舊資料）
    trigger_by: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # ── 關聯鏈（情境 2/3：換單、折讓、補差額）──────────────────────────
    # 同批次報帳共用 group_id，Dashboard 可整捆操作（情境 4）
    group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    # 指向被取代/被折讓的原始報帳（self-referential FK）
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 重複憑證偵測：指向同 user、相同 invoice_number 的先前 Expense（非 null 時 Dashboard 顯示警示）
    possible_duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True
    )

    # 關聯類型：'VOID_REPLACE' | 'CREDIT_NOTE' | 'SUPPLEMENT'
    relation_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 軟刪除：False 表示已作廢，Dashboard 金額加總時排除
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # 作廢原因（人類可讀，如「換貨換單」、「統編填寫錯誤」）
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 從說明文字或 OCR 提取的參考發票號碼（格式：AB-12345678）
    referenced_invoice_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 退貨紀錄追蹤碼（換新發票/折讓單：原發票號碼；換貨收據/改金額：原日期+金額，如 "2026-06-01 / $500"）
    return_record: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Dashboard 手動排序（數值越小越前面；null 表示未設定，排在最後）
    display_order: Mapped[int | None] = mapped_column(nullable=True)
    # 已從待退貨管理移出（保留資料與 relation_type badge，僅隱藏於孤立補件清單）
    dismissed_from_waiting_return: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # 沖銷/退貨確認時間（REPLACED_VOID / VOID_ORIGINAL / WAITING_RETURN 已配對）
    # CSV 匯出以此欄位決定沖銷分錄落在哪個報表期間，避免跨期污染
    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="expenses")
    images: Mapped[list["ExpenseImage"]] = relationship(
        "ExpenseImage", back_populates="expense", cascade="all, delete-orphan"
    )
    parent: Mapped["Expense | None"] = relationship(
        "Expense", remote_side="Expense.id", foreign_keys=[parent_id]
    )

    def __repr__(self) -> str:
        return f"<Expense id={self.id} status={self.status} total_amount={self.total_amount}>"
