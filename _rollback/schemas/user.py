import uuid
from datetime import datetime

from pydantic import BaseModel


class UserBase(BaseModel):
    line_user_id: str
    name: str | None = None
    department: str | None = None


class UserCreate(UserBase):
    pass


class UserRead(UserBase):
    id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}
