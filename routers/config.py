"""公開設定端點 — 不需 JWT，供前端初始化時取得系統設定。"""

from __future__ import annotations

import json
from pathlib import Path
from fastapi import APIRouter

from core.config import settings

router = APIRouter(
    prefix="/api/v1/config",
    tags=["config"],
)

_CATEGORIES_PATH = Path(__file__).parent.parent / "config" / "expense_categories.json"


def _load_expense_categories() -> dict:
    return json.loads(_CATEGORIES_PATH.read_text(encoding="utf-8"))


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


@router.get("/expense-categories")
def get_expense_categories() -> dict:
    """回傳費用父子科目完整清單（由 config/expense_categories.json 控制）。"""
    data = _load_expense_categories()
    return {
        "status": "success",
        "data": {"parents": data["parents"]},
        "message": "",
    }


@router.get("/voucher-categories")
def get_voucher_categories() -> dict:
    """回傳憑證類別清單（由 config/expense_categories.json 控制）。"""
    data = _load_expense_categories()
    return {
        "status": "success",
        "data": {"voucher_categories": data["voucher_categories"]},
        "message": "",
    }
