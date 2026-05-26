"""LIFF 批次上傳 Session ORM。

UploadSession  — 一次 LIFF 上傳流程的容器（TTL 30 分鐘）
SessionImage   — 單張圖片及其 sequence_order、is_voucher 狀態
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class UploadSession(Base):
    __tablename__ = "liff_upload_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    line_user_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # uploading | submitted | expired
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="uploading", server_default="uploading"
    )
    # 背景 OCR / 建帳任務狀態：pending | processing | done | failed
    processing_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    images: Mapped[list["SessionImage"]] = relationship(
        "SessionImage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionImage.sequence_order",
    )

    def __repr__(self) -> str:
        return (
            f"<UploadSession id={self.id} "
            f"user={self.line_user_id} status={self.status}>"
        )


class SessionImage(Base):
    __tablename__ = "liff_session_images"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("liff_upload_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 前端在按下「送出」瞬間凍結的排列順序（0-based），決定 auto_split 的切割順序
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)
    # 本地儲存路徑，格式同 uploads/{uuid}.jpg
    image_path: Mapped[str] = mapped_column(String(512), nullable=False)
    # True=憑證 False=物品照 None=尚未辨識（OCR 尚未完成）
    is_voucher: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # 使用者手動切換過類型（優先於 OCR 判斷）
    manually_set: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # 完整 VoucherOCRResult JSON（add_image 時寫入，submit_session 時還原）
    ocr_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped["UploadSession"] = relationship(
        "UploadSession", back_populates="images"
    )

    def __repr__(self) -> str:
        return (
            f"<SessionImage seq={self.sequence_order} "
            f"is_voucher={self.is_voucher} path={self.image_path}>"
        )
