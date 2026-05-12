"""SystemSetting ORM — 系統設定 key-value 儲存表。"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class SystemSetting(Base):
    """
    通用系統設定表（key-value 格式）。

    目前用途：
      - scheduler.enabled   → "true" / "false"
      - scheduler.times     → JSON array 字串，如 '["20:00","22:00"]'
      - scheduler.timezone  → 時區字串，如 "Asia/Taipei"
    """

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
