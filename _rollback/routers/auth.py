"""Auth Router — Dashboard 登入與 JWT 管理。"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database import get_db
from core.security import create_access_token, decode_access_token, hash_password, verify_password
from models.admin_user import AdminUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# ── Dependency：驗證 Bearer Token，回傳當前 username ──────────────
def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    username = decode_access_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="未授權，請重新登入")
    return username


# ── POST /auth/login ──────────────────────────────────────────────
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=dict)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> dict:
    """帳號密碼登入，成功回傳 JWT access_token。"""
    user = db.scalar(select(AdminUser).where(AdminUser.username == form.username))
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")

    token = create_access_token(subject=user.username)
    logger.info("Admin login: username=%s", user.username)
    return {
        "status": "success",
        "data": {
            "access_token": token,
            "token_type": "bearer",
            "username": user.username,
            "display_name": user.display_name or user.username,
            "employee_id": user.employee_id or "",
        },
        "message": "登入成功",
    }


# ── POST /auth/register（建立管理員帳號）────────────────────────────
class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str | None = None   # 姓名（選填，建議填寫）
    employee_id: str | None = None    # 工號（選填，唯一）


@router.post("/register", response_model=dict, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    """
    建立新管理員帳號（含姓名與工號）。
    ⚠️ 此端點建議在正式環境部署後透過 config 關閉（enable_register=False）。
    """
    # 帳號重複檢查
    if db.scalar(select(AdminUser).where(AdminUser.username == body.username)):
        raise HTTPException(status_code=409, detail="帳號已存在")

    # 工號重複檢查（僅在有填工號時）
    if body.employee_id:
        if db.scalar(select(AdminUser).where(AdminUser.employee_id == body.employee_id)):
            raise HTTPException(status_code=409, detail="工號已被其他帳號使用")

    admin = AdminUser(
        username=body.username,
        hashed_password=hash_password(body.password),
        display_name=body.display_name,
        employee_id=body.employee_id or None,
    )
    db.add(admin)
    db.commit()
    logger.info("New admin registered: username=%s employee_id=%s", body.username, body.employee_id)
    return {
        "status": "success",
        "data": {
            "username": body.username,
            "display_name": body.display_name,
            "employee_id": body.employee_id,
        },
        "message": "管理員帳號建立成功",
    }
