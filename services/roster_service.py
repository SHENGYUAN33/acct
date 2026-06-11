"""員工名冊服務 — 封裝所有 StaffRoster 業務邏輯。"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.staff_roster import StaffRoster
from models.user import User

logger = logging.getLogger(__name__)

_UNSET = object()  # sentinel：區分「未傳入」與「明確設為 None（清除）」


def get_all_roster(
    db: Session,
    is_bound: bool | None = None,
    page: int = 0,
    size: int = 20,
) -> tuple[list[StaffRoster], int]:
    """查詢名冊清單，支援 is_bound 過濾與分頁。"""
    query = select(StaffRoster)
    count_query = select(func.count()).select_from(StaffRoster)

    if is_bound is not None:
        query = query.where(StaffRoster.is_bound == is_bound)
        count_query = count_query.where(StaffRoster.is_bound == is_bound)

    total: int = db.scalar(count_query) or 0
    items: list[StaffRoster] = list(
        db.scalars(query.order_by(StaffRoster.created_at.desc()).offset(page * size).limit(size))
    )
    return items, total


def get_roster_by_id(db: Session, roster_id: UUID) -> StaffRoster | None:
    """依 ID 查詢單筆員工名冊記錄。"""
    return db.get(StaffRoster, roster_id)


def get_roster_by_line_user_id(db: Session, line_user_id: str) -> StaffRoster | None:
    """依 LINE User ID 查詢名冊記錄。"""
    return db.scalar(select(StaffRoster).where(StaffRoster.line_user_id == line_user_id))


def create_roster_entry(
    db: Session,
    name: str,
    department: str,
    line_id: str | None = None,
    account_role: str | None = None,
    line_name: str | None = None,
    email: str | None = None,
    is_petty_cash_target: bool = False,
    bank_account: str | None = None,
    job_title: str | None = None,
) -> StaffRoster:
    """新增單筆員工至名冊。"""
    entry = StaffRoster(
        name=name,
        department=department,
        line_id=line_id or None,
        account_role=account_role or None,
        line_name=line_name or None,
        email=email or None,
        is_petty_cash_target=is_petty_cash_target,
        bank_account=bank_account or None,
        job_title=job_title or None,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    logger.info("roster_service.create_roster_entry: created id=%s name=%s", entry.id, name)
    return entry


def update_roster_entry(
    db: Session,
    roster_id: UUID,
    name: object = _UNSET,
    department: object = _UNSET,
    line_id: object = _UNSET,
    account_role: object = _UNSET,
    line_name: object = _UNSET,
    email: object = _UNSET,
    is_petty_cash_target: object = _UNSET,
    bank_account: object = _UNSET,
    job_title: object = _UNSET,
) -> StaffRoster | None:
    """修改員工名冊資料（只更新有傳入的欄位）。

    傳入 None 表示明確清除；未傳入（_UNSET）則不動原值。
    """
    entry = db.get(StaffRoster, roster_id)
    if entry is None:
        return None

    if name is not _UNSET:
        entry.name = name  # type: ignore[assignment]
    if department is not _UNSET:
        entry.department = department  # type: ignore[assignment]
    if line_id is not _UNSET:
        entry.line_id = line_id  # type: ignore[assignment]
    if account_role is not _UNSET:
        entry.account_role = account_role  # type: ignore[assignment]
    if line_name is not _UNSET:
        entry.line_name = line_name  # type: ignore[assignment]
    if email is not _UNSET:
        entry.email = email  # type: ignore[assignment]
    if is_petty_cash_target is not _UNSET:
        entry.is_petty_cash_target = is_petty_cash_target  # type: ignore[assignment]
    if bank_account is not _UNSET:
        entry.bank_account = bank_account  # type: ignore[assignment]
    if job_title is not _UNSET:
        entry.job_title = job_title  # type: ignore[assignment]

    db.commit()
    db.refresh(entry)
    logger.info("roster_service.update_roster_entry: updated id=%s", roster_id)

    # 若已綁定 LINE，同步更新 users 表的 real_name / department
    if entry.line_user_id and (name is not _UNSET or department is not _UNSET):
        user = db.scalar(select(User).where(User.line_user_id == entry.line_user_id))
        if user:
            if name is not _UNSET:
                user.real_name = entry.name
            if department is not _UNSET:
                user.department = entry.department
            db.commit()
            logger.info(
                "roster_service.update_roster_entry: synced user real_name/department for line_user_id=%s",
                entry.line_user_id,
            )

    return entry


def delete_roster_entry(db: Session, roster_id: UUID) -> bool:
    """刪除員工名冊記錄。已綁定者拒絕並回傳 False。"""
    entry = db.get(StaffRoster, roster_id)
    if entry is None:
        return False
    if entry.is_bound:
        logger.warning(
            "roster_service.delete_roster_entry: rejected—already bound id=%s line_user_id=%s",
            roster_id,
            entry.line_user_id,
        )
        return False

    db.delete(entry)
    db.commit()
    logger.info("roster_service.delete_roster_entry: deleted id=%s", roster_id)
    return True


def bind_line_user_by_name(
    db: Session,
    name: str,
    line_user_id: str,
    line_display_name: str | None = None,
) -> StaffRoster | list[StaffRoster] | None:
    """核心方法：使用者輸入姓名時呼叫，完成 LINE 身分綁定（以姓名查名冊）。

    - 找到唯一一筆 → 設定 line_user_id / is_bound=True / bound_at=now()，回傳 StaffRoster
    - 找到多筆同名 → 回傳 list[StaffRoster]（由呼叫端處理同名提示）
    - 找不到        → 回傳 None

    line_display_name 若有值，且名冊的 line_name 尚未設定，則自動填入。
    """
    name = name.strip()
    all_matches: list[StaffRoster] = list(
        db.scalars(select(StaffRoster).where(StaffRoster.name == name).with_for_update())
    )

    if not all_matches:
        logger.info("roster_service.bind_line_user_by_name: name=%r not found", name)
        return None

    already_mine = next((m for m in all_matches if m.line_user_id == line_user_id), None)
    if already_mine:
        logger.info("roster_service.bind_line_user_by_name: name=%r already bound to same UID, idempotent", name)
        return already_mine

    candidates: list[StaffRoster] = [m for m in all_matches if not m.is_bound]

    if not candidates:
        logger.info("roster_service.bind_line_user_by_name: name=%r all entries already bound to other UIDs", name)
        return None

    if len(candidates) > 1:
        logger.warning(
            "roster_service.bind_line_user_by_name: found %d unbound entries with name=%r, returning list",
            len(candidates),
            name,
        )
        return candidates

    entry = candidates[0]
    entry.line_user_id = line_user_id
    entry.is_bound = True
    entry.bound_at = datetime.now(timezone.utc)
    if line_display_name and not entry.line_name:
        entry.line_name = line_display_name
    db.commit()
    db.refresh(entry)
    logger.info(
        "roster_service.bind_line_user_by_name: bound name=%r to line_user_id=%s",
        name,
        line_user_id,
    )
    return entry


def unbind_roster_entry(db: Session, roster_id: UUID) -> StaffRoster | None:
    """解除員工的 LINE 綁定狀態。"""
    entry = db.get(StaffRoster, roster_id)
    if entry is None:
        return None

    entry.line_user_id = None
    entry.is_bound = False
    entry.bound_at = None
    db.commit()
    db.refresh(entry)
    logger.info("roster_service.unbind_roster_entry: unbound id=%s", roster_id)
    return entry


_HEADER_ALIASES: dict[str, str] = {
    "姓名": "name",
    "line名稱": "line_name",
    "line id": "line_id",
    "組別": "department",
    "職稱": "job_title",
    "email": "email",
    "帳號權限": "account_role",
    "匯款零用金": "is_petty_cash_target",
    "匯款帳號": "bank_account",
}


def _normalize_row(row: dict) -> dict:
    """將中文或大小寫不一致的欄位名統一轉為英文 key。"""
    return {
        _HEADER_ALIASES.get(k.strip().lower(), k.strip()): v
        for k, v in row.items()
    }


def _parse_bool(value: str) -> bool:
    """CSV 布林值解析：true / 1 / yes / 是 → True，其餘 → False。"""
    return value.strip().lower() in {"true", "1", "yes", "是"}


def _get_roster_by_name(db: Session, name: str) -> StaffRoster | None:
    """依姓名查詢名冊記錄（CSV upsert 用）。"""
    return db.scalar(select(StaffRoster).where(StaffRoster.name == name))


def import_from_csv(db: Session, csv_content: str) -> dict:
    """CSV 批次匯入員工名冊。

    必要欄位：name, department
    選填欄位：line_id, account_role, line_name, email, is_petty_cash_target, bank_account
    支援 UTF-8 with BOM（呼叫端傳入前應先以 'utf-8-sig' decode）。
    name 相同時進行 upsert（更新資料欄位，不重置 is_bound 狀態）。
    """
    created: int = 0
    updated: int = 0
    errors: list[dict] = []

    reader = csv.DictReader(io.StringIO(csv_content))
    for row_index, row in enumerate(reader, start=2):
        try:
            row = _normalize_row(row)
            name = (row.get("name") or "").strip()
            department = (row.get("department") or "").strip()
            line_id = (row.get("line_id") or "").strip() or None
            account_role = (row.get("account_role") or "").strip() or None
            line_name = (row.get("line_name") or "").strip() or None
            email = (row.get("email") or "").strip() or None
            is_petty_cash_target = _parse_bool(row.get("is_petty_cash_target") or "")
            bank_account = (row.get("bank_account") or "").strip() or None
            job_title = (row.get("job_title") or "").strip() or None

            if not name:
                errors.append({"row": row_index, "reason": "name 欄位不可為空"})
                continue
            if not department:
                errors.append({"row": row_index, "reason": "department 欄位不可為空"})
                continue

            existing = _get_roster_by_name(db, name)
            if existing:
                existing.department = department
                existing.line_id = line_id
                existing.account_role = account_role
                existing.line_name = line_name
                existing.email = email
                existing.is_petty_cash_target = is_petty_cash_target
                existing.bank_account = bank_account
                existing.job_title = job_title
                db.commit()
                updated += 1
                logger.info("import_from_csv: updated name=%s row=%d", name, row_index)
                continue

            entry = StaffRoster(
                name=name,
                department=department,
                line_id=line_id,
                account_role=account_role,
                line_name=line_name,
                email=email,
                is_petty_cash_target=is_petty_cash_target,
                bank_account=bank_account,
                job_title=job_title,
            )
            db.add(entry)
            db.commit()
            created += 1
            logger.info("import_from_csv: created name=%s row=%d", name, row_index)

        except Exception as exc:
            logger.error("import_from_csv: row=%d error=%s", row_index, exc, exc_info=True)
            errors.append({"row": row_index, "reason": str(exc)})
            db.rollback()

    return {"created": created, "updated": updated, "errors": errors}
