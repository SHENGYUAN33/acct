"""員工名冊 ORM Model。"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID

from core.database import Base


class StaffRoster(Base):
    __tablename__ = "staff_roster"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)                              # 真實姓名
    department = Column(String(100), nullable=False)                        # 所屬組別
    employee_id = Column(String(50), unique=True, nullable=True)            # 員工編號（使用者輸入匹配用）
    line_user_id = Column(String(100), unique=True, nullable=True)          # LINE ID（綁定後自動填入）
    is_bound = Column(Boolean, default=False, nullable=False)               # 是否已完成綁定
    bound_at = Column(DateTime, nullable=True)                              # 綁定時間
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)  # 建立時間
