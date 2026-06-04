"""公開設定端點 — 不需 JWT，供前端初始化時取得系統設定。"""

from __future__ import annotations

from fastapi import APIRouter

from core.config import settings

router = APIRouter(
    prefix="/api/v1/config",
    tags=["config"],
)


@router.get("/departments")
def get_departments() -> dict:
    """回傳目前系統設定的組別清單（由 .env DEPARTMENTS 控制）。"""
    return {
        "status": "success",
        "data": {"departments": settings.departments},
        "message": "",
    }


@router.get("/account-roles")
def get_account_roles() -> dict:
    """回傳目前系統設定的帳號角色清單（由 .env ACCOUNT_ROLES 控制）。"""
    return {
        "status": "success",
        "data": {"account_roles": settings.account_roles},
        "message": "",
    }
