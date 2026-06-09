"""公開設定端點 — 不需 JWT，供前端初始化時取得系統設定。"""

from __future__ import annotations

import json
from pathlib import Path
from fastapi import APIRouter

from core.config import settings
from core.expense_categories import EXPENSE_CATEGORIES
from core.response import ok

router = APIRouter(
    prefix="/api/v1/config",
    tags=["config"],
)

_VOUCHER_PATH = Path(__file__).parent.parent / "config" / "expense_categories.json"


def _load_voucher_categories() -> list[dict]:
    data = json.loads(_VOUCHER_PATH.read_text(encoding="utf-8"))
    return data.get("voucher_categories", [])


@router.get("/departments")
def get_departments() -> dict:
    """回傳目前系統設定的組別清單（由 .env DEPARTMENTS 控制）。"""
    return ok(data={"departments": settings.departments})


@router.get("/account-roles")
def get_account_roles() -> dict:
    """回傳目前系統設定的帳號角色清單（由 .env ACCOUNT_ROLES 控制）。"""
    return ok(data={"account_roles": settings.account_roles})


@router.get("/expense-categories")
def get_expense_categories() -> dict:
    """回傳費用科目平面清單（從 core/expense_categories.py 單一來源衍生）。"""
    return ok(data={"categories": EXPENSE_CATEGORIES})


@router.get("/voucher-categories")
def get_voucher_categories() -> dict:
    """回傳憑證類別清單（由 config/expense_categories.json 控制）。"""
    return ok(data={"voucher_categories": _load_voucher_categories()})
