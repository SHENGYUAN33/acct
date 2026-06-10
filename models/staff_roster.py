"""員工名冊 ORM Model。"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID

from core.database import Base


class StaffRoster(Base):
    __tablename__ = "staff_roster"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)                                          # 真實姓名
    department = Column(String(100), nullable=False)                                    # 所屬組別
    line_id = Column(String(100), nullable=True)                                        # 公開 LINE ID
    account_role = Column(String(50), nullable=True)                                    # 帳號權限
    line_name = Column(String(128), nullable=True)                                      # LINE 顯示名稱
    email = Column(String(255), nullable=True)                                          # 電子郵件
    is_petty_cash_target = Column(Boolean, default=False, nullable=False)               # 公司匯款零用金對象
    job_title = Column(String(100), nullable=True)                                       # 職稱
    bank_account = Column(String(100), nullable=True)                                   # 匯款帳號
    line_user_id = Column(String(100), unique=True, nullable=True)                      # LINE 內部 UID（綁定後自動填入）
    is_bound = Column(Boolean, default=False, nullable=False)                           # 是否已完成綁定
    bound_at = Column(DateTime(timezone=True), nullable=True)                           # 綁定時間（TIMESTAMPTZ）
    created_at = Column(                                                                # 建立時間（TIMESTAMPTZ）
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
