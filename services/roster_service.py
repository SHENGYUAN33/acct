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

logger = logging.getLogger(__name__)

_UNSET = object()  # sentinel：區分「未傳入」與「明確設為 None（清除）」


def get_all_roster(
    db: Session,
    is_bound: bool | None = None,
    page: int = 0,
    size: int = 20,
) -> tuple[list[StaffRoster], int]:
    """查詢名冊清單，支援 is_bound 過濾與分頁。

    Args:
        db: SQLAlchemy Session。
        is_bound: 若指定，則過濾已綁定（True）或未綁定（False）員工；None 表示不過濾。
        page: 頁碼（從 0 開始）。
        size: 每頁筆數。

    Returns:
        (items, total_count) 的 tuple，items 為當頁資料列表，total_count 為符合條件的總筆數。
    """
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
    """依 ID 查詢單筆員工名冊記錄。

    Args:
        db: SQLAlchemy Session。
        roster_id: 目標記錄的 UUID。

    Returns:
        找到則回傳 StaffRoster 實例，否則回傳 None。
    """
    return db.get(StaffRoster, roster_id)


def get_roster_by_employee_id(db: Session, employee_id: str) -> StaffRoster | None:
    """依員工編號查詢名冊記錄。

    Args:
        db: SQLAlchemy Session。
        employee_id: 員工編號字串。

    Returns:
        找到則回傳 StaffRoster 實例，否則回傳 None。
    """
    return db.scalar(select(StaffRoster).where(StaffRoster.employee_id == employee_id))


def get_roster_by_line_user_id(db: Session, line_user_id: str) -> StaffRoster | None:
    """依 LINE User ID 查詢名冊記錄。

    Args:
        db: SQLAlchemy Session。
        line_user_id: LINE 平台使用者識別碼。

    Returns:
        找到則回傳 StaffRoster 實例，否則回傳 None。
    """
    return db.scalar(select(StaffRoster).where(StaffRoster.line_user_id == line_user_id))


def create_roster_entry(
    db: Session,
    name: str,
    department: str,
    employee_id: str | None = None,
) -> StaffRoster:
    """新增單筆員工至名冊。

    Args:
        db: SQLAlchemy Session。
        name: 員工真實姓名。
        department: 所屬組別。
        employee_id: 員工編號（選填，唯一值）。

    Returns:
        新建立的 StaffRoster 實例。
    """
    entry = StaffRoster(
        name=name,
        department=department,
        employee_id=employee_id or None,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    logger.info("roster_service.create_roster_entry: created id=%s employee_id=%s", entry.id, employee_id)
    return entry


def update_roster_entry(
    db: Session,
    roster_id: UUID,
    name: object = _UNSET,
    department: object = _UNSET,
    employee_id: object = _UNSET,
) -> StaffRoster | None:
    """修改員工名冊資料（只更新有傳入的欄位）。

    employee_id 傳入 None 表示明確清除；未傳入（_UNSET）則不動原值。

    Args:
        db: SQLAlchemy Session。
        roster_id: 目標記錄的 UUID。
        name: 新的真實姓名；_UNSET 表示不更新。
        department: 新的所屬組別；_UNSET 表示不更新。
        employee_id: 新的員工編號；None 表示清除；_UNSET 表示不更新。

    Returns:
        更新後的 StaffRoster 實例；找不到則回傳 None。
    """
    entry = db.get(StaffRoster, roster_id)
    if entry is None:
        return None

    if name is not _UNSET:
        entry.name = name  # type: ignore[assignment]
    if department is not _UNSET:
        entry.department = department  # type: ignore[assignment]
    if employee_id is not _UNSET:
        entry.employee_id = employee_id  # type: ignore[assignment]  None = 清除

    db.commit()
    db.refresh(entry)
    logger.info("roster_service.update_roster_entry: updated id=%s", roster_id)
    return entry


def delete_roster_entry(db: Session, roster_id: UUID) -> bool:
    """刪除員工名冊記錄。

    若該員工已完成 LINE 綁定（is_bound=True），則拒絕刪除並回傳 False。

    Args:
        db: SQLAlchemy Session。
        roster_id: 目標記錄的 UUID。

    Returns:
        成功刪除回傳 True；找不到或已綁定回傳 False。
    """
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
) -> StaffRoster | list[StaffRoster] | None:
    """核心方法：使用者輸入姓名時呼叫，完成 LINE 身分綁定（以姓名查名冊）。

    - 找到唯一一筆 → 設定 line_user_id / is_bound=True / bound_at=now()，回傳 StaffRoster
    - 找到多筆同名 → 回傳 list[StaffRoster]（由呼叫端處理同名提示）
    - 找不到        → 回傳 None

    Args:
        db: SQLAlchemy Session。
        name: 使用者輸入的姓名（完全匹配）。
        line_user_id: 要綁定的 LINE 使用者識別碼。

    Returns:
        唯一匹配回傳 StaffRoster；多筆同名回傳 list；找不到回傳 None。
    """
    name = name.strip()
    # FOR UPDATE 確保同名同時綁定時，第二個請求等第一個 commit 後才看到最新 is_bound 狀態
    all_matches: list[StaffRoster] = list(
        db.scalars(select(StaffRoster).where(StaffRoster.name == name).with_for_update())
    )

    if not all_matches:
        logger.info("roster_service.bind_line_user_by_name: name=%r not found", name)
        return None

    # 若此 line_user_id 已綁定至其中一筆，視為重複綁定，直接回傳（冪等）
    already_mine = next((m for m in all_matches if m.line_user_id == line_user_id), None)
    if already_mine:
        logger.info("roster_service.bind_line_user_by_name: name=%r already bound to same UID, idempotent", name)
        return already_mine

    # 只考慮尚未綁定的名冊項目作為候選
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
        return candidates  # 由 webhook 層回覆同名提示

    entry = candidates[0]
    entry.line_user_id = line_user_id
    entry.is_bound = True
    entry.bound_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(entry)
    logger.info(
        "roster_service.bind_line_user_by_name: bound name=%r to line_user_id=%s",
        name,
        line_user_id,
    )
    return entry


def bind_line_user(
    db: Session,
    employee_id: str,
    line_user_id: str,
) -> StaffRoster | None:
    """核心方法：使用者輸入員工編號時呼叫，完成 LINE 身分綁定。

    查詢 employee_id → 設定 line_user_id / is_bound=True / bound_at=now()。
    找不到 employee_id 則回傳 None（不拋例外）。
    若此 line_user_id 已綁定至同一筆記錄，視為冪等操作直接回傳（不覆寫 bound_at）。

    Args:
        db: SQLAlchemy Session。
        employee_id: 使用者輸入的員工編號。
        line_user_id: 要綁定的 LINE 使用者識別碼。

    Returns:
        綁定成功回傳更新後的 StaffRoster；找不到員工編號則回傳 None。
    """
    entry = get_roster_by_employee_id(db, employee_id)
    if entry is None:
        logger.info(
            "roster_service.bind_line_user: employee_id=%s not found, returning None",
            employee_id,
        )
        return None

    # 冪等：同一個 line_user_id 已綁定至此記錄，直接回傳
    if entry.line_user_id == line_user_id:
        logger.info(
            "roster_service.bind_line_user: employee_id=%s already bound to same UID, idempotent",
            employee_id,
        )
        return entry

    entry.line_user_id = line_user_id
    entry.is_bound = True
    entry.bound_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(entry)
    logger.info(
        "roster_service.bind_line_user: bound employee_id=%s to line_user_id=%s",
        employee_id,
        line_user_id,
    )
    return entry


def unbind_roster_entry(db: Session, roster_id: UUID) -> StaffRoster | None:
    """解除員工的 LINE 綁定狀態。

    清空 line_user_id / is_bound=False / bound_at=None。

    Args:
        db: SQLAlchemy Session。
        roster_id: 目標記錄的 UUID。

    Returns:
        解除後的 StaffRoster 實例；找不到則回傳 None。
    """
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


def import_from_csv(db: Session, csv_content: str) -> dict:
    """CSV 批次匯入員工名冊。

    欄位格式：name, department, employee_id（需含標題列）。
    employee_id 相同時進行 upsert（更新 name/department，不重置 is_bound 狀態）。
    每筆錯誤單獨記錄，不中斷整批作業。

    支援 UTF-8 with BOM（呼叫端傳入前應先以 'utf-8-sig' decode）。

    Args:
        db: SQLAlchemy Session。
        csv_content: CSV 純文字內容。

    Returns:
        字典包含 {"created": N, "updated": N, "errors": [{"row": N, "reason": "..."}]}。
    """
    created: int = 0
    updated: int = 0
    errors: list[dict] = []

    reader = csv.DictReader(io.StringIO(csv_content))
    for row_index, row in enumerate(reader, start=2):  # 第 1 行為標題，資料從第 2 行起
        try:
            name = (row.get("name") or "").strip()
            department = (row.get("department") or "").strip()
            employee_id_raw = (row.get("employee_id") or "").strip()
            employee_id = employee_id_raw if employee_id_raw else None

            if not name:
                errors.append({"row": row_index, "reason": "name 欄位不可為空"})
                continue
            if not department:
                errors.append({"row": row_index, "reason": "department 欄位不可為空"})
                continue

            # upsert：若 employee_id 有值且已存在，則更新 name/department
            if employee_id:
                existing = get_roster_by_employee_id(db, employee_id)
                if existing:
                    existing.name = name
                    existing.department = department
                    # 不重置 is_bound / line_user_id / bound_at
                    db.commit()
                    updated += 1
                    logger.info("import_from_csv: updated employee_id=%s row=%d", employee_id, row_index)
                    continue

            # 新增
            entry = StaffRoster(
                name=name,
                department=department,
                employee_id=employee_id,
            )
            db.add(entry)
            db.commit()
            created += 1
            logger.info("import_from_csv: created employee_id=%s row=%d", employee_id, row_index)

        except Exception as exc:
            logger.error("import_from_csv: row=%d error=%s", row_index, exc, exc_info=True)
            errors.append({"row": row_index, "reason": str(exc)})
            db.rollback()

    return {"created": created, "updated": updated, "errors": errors}
