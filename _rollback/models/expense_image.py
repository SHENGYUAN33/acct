import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class ExpenseImage(Base):
    __tablename__ = "expense_images"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    expense_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("expenses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    image_url: Mapped[str] = mapped_column(String(512), nullable=False)
    is_voucher: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 頂層文件類型：INVOICE / RECEIPT / LABOR_SERVICE / TRANSPORTATION /
    #               CREDIT_NOTE / INSURANCE / UTILITY / RENTAL / ACCOMMODATION / POSTAGE
    voucher_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 子類型：HSR_TICKET / FUEL / EXEMPT_INVOICE / WORK_INJURY / WATER 等
    voucher_subtype: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 費用科目：MEAL / STATIONERY / TRANSPORTATION / INSURANCE / UTILITY 等
    expense_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # JSON 字串格式的完整 OCR 結果（VoucherOCRResult.model_dump_json 序列化）
    ocr_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Gemini overall_confidence 分數（0.000–1.000）
    ocr_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    expense: Mapped["Expense"] = relationship("Expense", back_populates="images")

    def __repr__(self) -> str:
        return (
            f"<ExpenseImage id={self.id} expense_id={self.expense_id} "
            f"sequence_order={self.sequence_order} is_voucher={self.is_voucher}>"
        )
