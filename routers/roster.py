"""員工名冊路由 — 管理員 Dashboard 操作員工名冊的 API（需 JWT 認證）。"""

from __future__ import annotations

import csv
import io
import logging
import math
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database import get_db
from core.response import ok
from routers.auth import get_current_user
from schemas.roster import RosterCreate, RosterImportResult, RosterListResponse, RosterRead, RosterUpdate
from models.user import User
from services import roster_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/roster",
    tags=["roster"],
    dependencies=[Depends(get_current_user)],
)


# ── GET /roster（查詢名冊清單）──────────────────────────────────────
@router.get("", response_model=dict)
def list_roster(
    is_bound: bool | None = Query(default=None, description="過濾綁定狀態：true=已綁定，false=未綁定，省略=全部"),
    page: int = Query(default=0, ge=0, description="頁碼（從 0 開始）"),
    size: int = Query(default=20, ge=1, le=1000, description="每頁筆數"),
    db: Session = Depends(get_db),
) -> dict:
    """查詢員工名冊清單，支援 is_bound 過濾與分頁。"""
    items, total = roster_service.get_all_roster(db, is_bound=is_bound, page=page, size=size)
    total_pages = math.ceil(total / size) if size > 0 else 0
    return ok(
        data=RosterListResponse(
            content=[RosterRead.model_validate(item) for item in items],
            page=page,
            size=size,
            total_elements=total,
            total_pages=total_pages,
        ).model_dump(),
    )


# ── POST /roster（新增單筆）─────────────────────────────────────────
@router.post("", response_model=dict, status_code=201)
def create_roster(
    body: RosterCreate,
    db: Session = Depends(get_db),
) -> dict:
    """新增單筆員工至名冊。"""
    entry = roster_service.create_roster_entry(
        db,
        name=body.name,
        department=body.department,
        line_id=body.line_id,
        account_role=body.account_role,
        line_name=body.line_name,
        email=body.email,
        is_petty_cash_target=body.is_petty_cash_target,
        bank_account=body.bank_account,
        job_title=body.job_title,
    )
    return ok(data=RosterRead.model_validate(entry).model_dump(), message="新增成功")


# ── GET /roster/export（匯出現有名冊 CSV）── 必須在 /{roster_id} 前定義 ──
@router.get("/export")
def export_roster_csv(
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """匯出現有員工名冊為 CSV（UTF-8 with BOM，供 Excel 直接開啟）。

    欄位順序與匯入樣板一致：name, department, line_id, account_role,
    line_name, email, is_petty_cash_target, bank_account。
    綁定相關欄位（line_user_id, is_bound 等）不包含在內。
    """
    items, _ = roster_service.get_all_roster(db, page=0, size=10000)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "姓名", "LINE名稱", "LINE ID", "組別", "職稱",
        "Email", "帳號權限", "匯款零用金", "匯款帳號", "綁定狀態", "綁定時間",
    ])
    for item in items:
        if item.bound_at:
            bound_str = item.bound_at.strftime("%Y-%m-%d %H:%M")
        else:
            bound_str = ""
        writer.writerow([
            item.name,
            item.line_name or "",
            item.line_id or "",
            item.department,
            item.job_title or "",
            item.email or "",
            item.account_role or "",
            "是" if item.is_petty_cash_target else "否",
            item.bank_account or "",
            "已綁定" if item.is_bound else "未綁定",
            bound_str,
        ])

    bom = "﻿"
    content = bom + output.getvalue()

    return StreamingResponse(
        iter([content.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=roster_export.csv"},
    )


# ── POST /roster/import（CSV 批次匯入）—— 必須在 /{roster_id} 前定義 ──
@router.post("/import", response_model=dict)
async def import_roster_csv(
    file: UploadFile = File(
        ...,
        description="CSV 檔案（欄位：name, department, line_id, account_role, line_name, email, is_petty_cash_target, bank_account）",
    ),
    db: Session = Depends(get_db),
) -> dict:
    """批次匯入員工名冊 CSV。

    CSV 格式規範：
    - 必要欄位：name, department
    - 選填欄位：line_id, account_role, line_name, email, is_petty_cash_target, bank_account
    - 支援 UTF-8 with BOM（Excel 匯出格式）
    - name 相同時 upsert（更新資料欄位，不重置綁定狀態）
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="請上傳 .csv 格式的檔案")

    raw_bytes = await file.read()
    csv_content = raw_bytes.decode("utf-8-sig")

    result = roster_service.import_from_csv(db, csv_content)
    return ok(
        data=RosterImportResult(**result).model_dump(),
        message=f"匯入完成：新增 {result['created']} 筆，更新 {result['updated']} 筆，錯誤 {len(result['errors'])} 筆",
    )


# ── PATCH /roster/{roster_id}（修改）───────────────────────────────
@router.patch("/{roster_id}", response_model=dict)
def update_roster(
    roster_id: UUID,
    body: RosterUpdate,
    db: Session = Depends(get_db),
) -> dict:
    """修改員工名冊資料（只更新有傳入的欄位）。

    各欄位明確傳入 null 表示清除；未傳入該欄位則不動原值。
    """
    kwargs: dict = {}
    for field in ("name", "department", "line_id", "account_role", "line_name", "email",
                  "is_petty_cash_target", "bank_account", "job_title"):
        if field in body.model_fields_set:
            kwargs[field] = getattr(body, field)

    entry = roster_service.update_roster_entry(db, roster_id=roster_id, **kwargs)
    if entry is None:
        raise HTTPException(status_code=404, detail="找不到指定的員工名冊記錄")

    return ok(data=RosterRead.model_validate(entry).model_dump(), message="更新成功")


# ── DELETE /roster/{roster_id}（刪除）──────────────────────────────
@router.delete("/{roster_id}", response_model=dict)
def delete_roster(
    roster_id: UUID,
    db: Session = Depends(get_db),
) -> dict:
    """刪除員工名冊記錄。已綁定 LINE 的員工無法刪除，回傳 400。"""
    success = roster_service.delete_roster_entry(db, roster_id)
    if success is False:
        entry = roster_service.get_roster_by_id(db, roster_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="找不到指定的員工名冊記錄")
        raise HTTPException(status_code=400, detail="該員工已完成 LINE 綁定，無法刪除。如需刪除請先解除綁定。")

    return ok(data=None, message="刪除成功")


# ── POST /roster/{roster_id}/unbind（解除綁定）─────────────────────
@router.post("/{roster_id}/unbind", response_model=dict)
def unbind_roster(
    roster_id: UUID,
    db: Session = Depends(get_db),
) -> dict:
    """解除員工的 LINE 綁定狀態（清空 line_user_id / is_bound=False / bound_at=None）。"""
    roster_entry = roster_service.get_roster_by_id(db, roster_id)
    if roster_entry is None:
        raise HTTPException(status_code=404, detail="找不到指定的員工名冊記錄")

    bound_line_user_id = roster_entry.line_user_id

    entry = roster_service.unbind_roster_entry(db, roster_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="找不到指定的員工名冊記錄")

    if bound_line_user_id:
        user = db.scalar(select(User).where(User.line_user_id == bound_line_user_id))
        if user:
            user.real_name = None
            user.department = None
            db.commit()
            logger.info("unbind_roster: cleared real_name/department for line_user_id=%s", bound_line_user_id)

    return ok(data=RosterRead.model_validate(entry).model_dump(), message="已解除 LINE 綁定")
