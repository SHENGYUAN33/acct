from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class UserState(Base):
    __tablename__ = "user_states"

    line_user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    step: Mapped[str] = mapped_column(String(128), nullable=False)
    dept: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 多圖收集佇列（JSON array 字串，存放已上傳的圖片路徑）
    pending_images: Mapped[str] = mapped_column(
        String, nullable=False, default="[]", server_default="[]"
    )
    # 使用者對本次報帳的文字說明
    pending_description: Mapped[str] = mapped_column(
        String, nullable=False, default="", server_default=""
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<UserState line_user_id={self.line_user_id} step={self.step} dept={self.dept}>"
