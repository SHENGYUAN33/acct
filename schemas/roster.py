"""員工名冊相關 Pydantic Schema。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class RosterCreate(BaseModel):
    name: str
    department: str
    line_id: str | None = None
    account_role: str | None = None
    line_name: str | None = None
    email: str | None = None
    is_petty_cash_target: bool = False
    bank_account: str | None = None
    job_title: str | None = None


class RosterUpdate(BaseModel):
    name: str | None = None
    department: str | None = None
    line_id: str | None = None
    account_role: str | None = None
    line_name: str | None = None
    email: str | None = None
    is_petty_cash_target: bool | None = None
    bank_account: str | None = None
    job_title: str | None = None


class RosterRead(BaseModel):
    id: UUID
    name: str
    department: str
    line_id: str | None
    account_role: str | None
    line_name: str | None
    email: str | None
    is_petty_cash_target: bool
    bank_account: str | None
    job_title: str | None
    line_user_id: str | None
    is_bound: bool
    bound_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RosterListResponse(BaseModel):
    content: list[RosterRead]
    page: int
    size: int
    total_elements: int
    total_pages: int


class RosterImportResult(BaseModel):
    created: int
    updated: int
    errors: list[dict]
