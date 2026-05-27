"""員工名冊路由 — 管理員 Dashboard 操作員工名冊的 API（需 JWT 認證）。"""

from __future__ import annotations

import logging
import math
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database import get_db
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
    return {
        "status": "success",
        "data": RosterListResponse(
            content=[RosterRead.model_validate(item) for item in items],
            page=page,
            size=size,
            total_elements=total,
            total_pages=total_pages,
        ).model_dump(),
        "message": "ok",
    }


# ── POST /roster（新增單筆）─────────────────────────────────────────
@router.post("", response_model=dict, status_code=201)
def create_roster(
    body: RosterCreate,
    db: Session = Depends(get_db),
) -> dict:
    """新增單筆員工至名冊。"""
    # 若 employee_id 已存在，回傳 409
    if body.employee_id:
        existing = roster_service.get_roster_by_employee_id(db, body.employee_id)
        if existing:
            raise HTTPException(status_code=409, detail=f"員工編號「{body.employee_id}」已存在")

    entry = roster_service.create_roster_entry(
        db,
        name=body.name,
        department=body.department,
        employee_id=body.employee_id,
    )
    return {
        "status": "success",
        "data": RosterRead.model_validate(entry).model_dump(),
        "message": "新增成功",
    }


# ── POST /roster/import（CSV 批次匯入）—— 必須在 /{roster_id} 前定義 ──
@router.post("/import", response_model=dict)
async def import_roster_csv(
    file: UploadFile = File(..., description="CSV 檔案（欄位：name, department, employee_id）"),
    db: Session = Depends(get_db),
) -> dict:
    """批次匯入員工名冊 CSV。

    CSV 格式規範：
    - 必要欄位：name, department
    - 選填欄位：employee_id
    - 支援 UTF-8 with BOM（Excel 匯出格式）
    - employee_id 相同時 upsert（更新 name/department，不重置綁定狀態）
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="請上傳 .csv 格式的檔案")

    raw_bytes = await file.read()
    # 支援 UTF-8 with BOM（Excel 匯出時常帶 BOM）
    csv_content = raw_bytes.decode("utf-8-sig")

    result = roster_service.import_from_csv(db, csv_content)
    return {
        "status": "success",
        "data": RosterImportResult(**result).model_dump(),
        "message": f"匯入完成：新增 {result['created']} 筆，更新 {result['updated']} 筆，錯誤 {len(result['errors'])} 筆",
    }


# ── PATCH /roster/{roster_id}（修改）───────────────────────────────
@router.patch("/{roster_id}", response_model=dict)
def update_roster(
    roster_id: UUID,
    body: RosterUpdate,
    db: Session = Depends(get_db),
) -> dict:
    """修改員工名冊資料（只更新有傳入的欄位）。"""
    # 若要更新 employee_id，檢查是否與其他記錄衝突
    if body.employee_id:
        existing = roster_service.get_roster_by_employee_id(db, body.employee_id)
        if existing and existing.id != roster_id:
            raise HTTPException(status_code=409, detail=f"員工編號「{body.employee_id}」已被其他記錄使用")

    entry = roster_service.update_roster_entry(
        db,
        roster_id=roster_id,
        name=body.name,
        department=body.department,
        employee_id=body.employee_id,
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="找不到指定的員工名冊記錄")

    return {
        "status": "success",
        "data": RosterRead.model_validate(entry).model_dump(),
        "message": "更新成功",
    }


# ── DELETE /roster/{roster_id}（刪除）──────────────────────────────
@router.delete("/{roster_id}", response_model=dict)
def delete_roster(
    roster_id: UUID,
    db: Session = Depends(get_db),
) -> dict:
    """刪除員工名冊記錄。已綁定 LINE 的員工無法刪除，回傳 400。"""
    success = roster_service.delete_roster_entry(db, roster_id)
    if success is False:
        # 先確認記錄存在，以區分「找不到」與「已綁定」兩種情況
        entry = roster_service.get_roster_by_id(db, roster_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="找不到指定的員工名冊記錄")
        raise HTTPException(status_code=400, detail="該員工已完成 LINE 綁定，無法刪除。如需刪除請先解除綁定。")

    return {
        "status": "success",
        "data": None,
        "message": "刪除成功",
    }


# ── POST /roster/{roster_id}/unbind（解除綁定）─────────────────────
@router.post("/{roster_id}/unbind", response_model=dict)
def unbind_roster(
    roster_id: UUID,
    db: Session = Depends(get_db),
) -> dict:
    """解除員工的 LINE 綁定狀態（清空 line_user_id / is_bound=False / bound_at=None）。"""
    # 先取得 line_user_id，解除後才能回去清 users 表
    roster_entry = roster_service.get_roster_by_id(db, roster_id)
    if roster_entry is None:
        raise HTTPException(status_code=404, detail="找不到指定的員工名冊記錄")

    bound_line_user_id = roster_entry.line_user_id

    entry = roster_service.unbind_roster_entry(db, roster_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="找不到指定的員工名冊記錄")

    # 同步清空 users 表的 real_name / department，讓 LIFF 與 Webhook 生效
    if bound_line_user_id:
        user = db.scalar(select(User).where(User.line_user_id == bound_line_user_id))
        if user:
            user.real_name = None
            user.department = None
            db.commit()
            logger.info("unbind_roster: cleared real_name/department for line_user_id=%s", bound_line_user_id)

    return {
        "status": "success",
        "data": RosterRead.model_validate(entry).model_dump(),
        "message": "已解除 LINE 綁定",
    }
