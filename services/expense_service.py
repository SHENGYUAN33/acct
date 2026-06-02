"""Expense Service — CRUD operations and status machine for Expense records."""

import json
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal

logger = logging.getLogger(__name__)

from sqlalchemy import select, func, text, nullslast
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from models.expense import Expense, ExpenseStatus
from models.expense_image import ExpenseImage
from models.user import User
from schemas.ocr import KEY_AUDIT_FIELDS, KEY_FIELD_THRESHOLD, VoucherOCRResult


def _generate_serial_number(db: Session) -> str:
    """
    產生每月重置的案件編號。
    格式：EXP-{YYYYMM}-{當月流水號 4 位}，例：EXP-202604-0001。
    以 MAX 查詢當月最大序號，加 1 作為新序號。
    用 MAX 取代 COUNT，避免刪除記錄後序號重複的問題。
    race condition 由呼叫方的重試機制處理。
    """
    prefix = datetime.now().strftime('%Y%m')

    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        next_seq = db.execute(text("SELECT nextval('expense_serial_seq')")).scalar_one()
        return f"EXP-{prefix}-{int(next_seq):04d}"

    max_serial: str | None = db.scalar(
        select(func.max(Expense.serial_number)).where(
            Expense.serial_number.like(f"EXP-{prefix}-%")
        )
    )
    if max_serial:
        try:
            last_seq = int(max_serial.rsplit("-", 1)[-1])
        except (ValueError, IndexError):
            last_seq = 0
    else:
        last_seq = 0
    return f"EXP-{prefix}-{last_seq + 1:04d}"


# ---------------------------------------------------------------------------
# User helpers
# ---------------------------------------------------------------------------

def get_or_create_user(db: Session, line_user_id: str) -> User:
    """Return existing user or create a new one by LINE user ID."""
    user = db.scalar(select(User).where(User.line_user_id == line_user_id))
    if not user:
        user = User(line_user_id=line_user_id)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def update_user_department(db: Session, line_user_id: str, department: str) -> User:
    """Set or update the department for a user."""
    user = get_or_create_user(db, line_user_id)
    user.department = department
    db.commit()
    db.refresh(user)
    return user


def update_user_real_name(db: Session, line_user_id: str, real_name: str) -> User:
    """綁定或更新使用者的真實姓名。"""
    user = get_or_create_user(db, line_user_id)
    user.real_name = real_name
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Expense CRUD
# ---------------------------------------------------------------------------

def create_expense(
    db: Session,
    user_id: uuid.UUID,
    image_url: str | list[str],
    # System / LINE fields
    uploader_name: str | None = None,
    uploader_dept: str | None = None,
    submitter_name: str | None = None,
    submitter_dept: str | None = None,
    upload_date: datetime | None = None,
    # OCR-extracted fields
    item_description: str | None = None,
    expense_date: date | str | None = None,
    invoice_number: str | None = None,
    total_amount: Decimal | None = None,
    net_amount: Decimal | None = None,
    tax_amount: Decimal | None = None,
    seller_tax_id: str | None = None,
    seller_name: str | None = None,
    needs_manual_review: bool = False,
) -> Expense:
    """Create a new expense record."""
    status = ExpenseStatus.NEEDS_MANUAL_REVIEW if needs_manual_review else ExpenseStatus.PENDING

    parsed_expense_date: date | None = _parse_expense_date(expense_date)

    # 接受 str（LINE 上傳單張）或 list；統一轉為陣列
    image_urls: list[str] = [image_url] if isinstance(image_url, str) else image_url

    for _attempt in range(5):
        expense = Expense(
            user_id=user_id,
            serial_number=_generate_serial_number(db),
            image_url=image_urls,
            uploader_name=uploader_name,
            uploader_dept=uploader_dept,
            submitter_name=submitter_name,
            submitter_dept=submitter_dept,
            upload_date=upload_date,
            item_description=item_description,
            expense_date=parsed_expense_date,
            invoice_number=invoice_number,
            total_amount=total_amount,
            net_amount=net_amount,
            tax_amount=tax_amount,
            seller_tax_id=seller_tax_id,
            seller_name=seller_name,
            status=status,
        )
        db.add(expense)
        try:
            db.commit()
            db.refresh(expense)
            return expense
        except IntegrityError as exc:
            db.rollback()
            # 僅對 serial_number unique violation 重試，其餘錯誤直接拋出
            if "uq_expenses_serial_number" not in str(exc.orig):
                raise
    # 5 次重試全部失敗（極低機率），拋出原始錯誤
    raise RuntimeError("無法產生唯一案件流水號，請稍後再試")


def get_expense(db: Session, expense_id: uuid.UUID) -> Expense | None:
    return db.get(Expense, expense_id)


def get_expense_by_serial_number(db: Session, serial_number: str) -> Expense | None:
    """依案件流水號查詢單筆報帳。"""
    return db.scalar(select(Expense).where(Expense.serial_number == serial_number))


def get_recent_expenses_by_user(
    db: Session, user_id: uuid.UUID, limit: int = 3
) -> list[Expense]:
    """回傳指定使用者最近 N 筆報帳（依建立時間降冪）。"""
    return list(
        db.scalars(
            select(Expense)
            .where(Expense.user_id == user_id)
            .order_by(Expense.created_at.desc())
            .limit(limit)
        ).all()
    )


def find_expense_by_invoice_number(db: Session, invoice_number: str) -> Expense | None:
    """查詢是否已有相同發票號碼的報帳記錄（最新一筆）。"""
    return db.scalar(
        select(Expense)
        .where(Expense.invoice_number == invoice_number)
        .order_by(Expense.created_at.desc())
    )


def list_expenses(
    db: Session,
    status: ExpenseStatus | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
    include_inactive: bool = False,
    q: str | None = None,
    referenced_invoice_number: str | None = None,
    has_duplicate: bool | None = None,
    relation_type: str | None = None,
    # ── 進階多條件篩選（新增，所有條件 AND 疊加）──────────────────────
    serial_number_q: str | None = None,
    invoice_number_q: str | None = None,
    uploader_name_q: str | None = None,
    uploader_dept_q: str | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    voucher_category_q: str | None = None,
) -> tuple[int, list[Expense]]:
    """Return (total_count, expenses) with optional filters and pagination.

    include_inactive=False（預設）：排除 is_active=False 的作廢記錄，避免重覆計算。
    q：模糊搜尋案件編號或上傳者姓名（ILIKE）。
    referenced_invoice_number：精確篩選補件所參考的原始憑證號碼。
    has_duplicate=True：只回傳 possible_duplicate_of 非 null 的疑似重複記錄。
    relation_type：精確篩選補件類型（如 RETURN_SUPPLEMENT）。
    serial_number_q / invoice_number_q / uploader_name_q / uploader_dept_q：各欄位獨立模糊搜尋。
    amount_min / amount_max：金額範圍篩選（含邊界）。
    voucher_category_q：憑證類別篩選（比對 voucher_categories JSON 字串）。
    """
    stmt = select(Expense).order_by(
        nullslast(Expense.display_order),
        Expense.created_at.desc()
    )

    if not include_inactive:
        stmt = stmt.where(Expense.is_active == True)
    if status:
        stmt = stmt.where(Expense.status == status)
    if date_from:
        stmt = stmt.where(Expense.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Expense.created_at <= date_to)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            (Expense.serial_number.ilike(pattern)) | (Expense.uploader_name.ilike(pattern))
        )
    if referenced_invoice_number:
        stmt = stmt.where(Expense.referenced_invoice_number == referenced_invoice_number)
    if has_duplicate is True:
        stmt = stmt.where(Expense.possible_duplicate_of.isnot(None))
    if relation_type:
        stmt = stmt.where(Expense.relation_type == relation_type)
    # ── 進階多條件篩選（各條件獨立 AND 疊加，不影響上方既有條件）──────
    if serial_number_q:
        stmt = stmt.where(Expense.serial_number.ilike(f"%{serial_number_q}%"))
    if invoice_number_q:
        stmt = stmt.where(Expense.invoice_number.ilike(f"%{invoice_number_q}%"))
    if uploader_name_q:
        stmt = stmt.where(Expense.uploader_name.ilike(f"%{uploader_name_q}%"))
    if uploader_dept_q:
        stmt = stmt.where(Expense.uploader_dept.ilike(f"%{uploader_dept_q}%"))
    if amount_min is not None:
        stmt = stmt.where(Expense.total_amount >= amount_min)
    if amount_max is not None:
        stmt = stmt.where(Expense.total_amount <= amount_max)
    if voucher_category_q:
        stmt = stmt.where(Expense.voucher_categories.ilike(f'%"{voucher_category_q}"%'))

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return total or 0, list(items)


def create_expense_manual(
    db: Session,
    uploader_name: str | None = None,
    uploader_dept: str | None = None,
    submitter_name: str | None = None,
    submitter_dept: str | None = None,
    expense_date: date | None = None,
    invoice_number: str | None = None,
    total_amount: Decimal | None = None,
    net_amount: Decimal | None = None,
    tax_amount: Decimal | None = None,
    seller_tax_id: str | None = None,
    seller_name: str | None = None,
    item_description: str | None = None,
) -> Expense:
    """Dashboard 手動新增費用（不透過 LINE 上傳），image_url 初始為空陣列。"""
    for _attempt in range(5):
        expense = Expense(
            serial_number=_generate_serial_number(db),
            image_url=[],
            status=ExpenseStatus.PENDING,
            uploader_name=uploader_name,
            uploader_dept=uploader_dept,
            submitter_name=submitter_name,
            submitter_dept=submitter_dept,
            expense_date=expense_date,
            invoice_number=invoice_number,
            total_amount=total_amount,
            net_amount=net_amount,
            tax_amount=tax_amount,
            seller_tax_id=seller_tax_id,
            seller_name=seller_name,
            item_description=item_description,
        )
        db.add(expense)
        try:
            db.commit()
            db.refresh(expense)
            return expense
        except IntegrityError as exc:
            db.rollback()
            if "uq_expenses_serial_number" not in str(exc.orig):
                raise
    raise RuntimeError("無法產生唯一案件流水號，請稍後再試")


def delete_expense(db: Session, expense_id: uuid.UUID) -> bool:
    """刪除單筆費用紀錄。Returns False if not found."""
    expense = get_expense(db, expense_id)
    if not expense:
        return False
    # Bug 3：若刪除 VOID_REPLACE 補件，先還原被取代的原始憑證狀態
    if expense.relation_type == "VOID_REPLACE" and expense.parent_id:
        original = db.get(Expense, expense.parent_id)
        if original:
            original.is_active = True
            original.status = ExpenseStatus.WAITING_RETURN
            original.void_reason = None
            db.add(original)
    # 若為有發票號碼的憑證（WAITING_RETURN），連帶刪除所有以此發票號碼為 referenced_invoice_number 的 RETURN_SUPPLEMENT 補件
    if expense.invoice_number:
        supplements = list(db.scalars(
            select(Expense).where(
                Expense.relation_type == "RETURN_SUPPLEMENT",
                Expense.referenced_invoice_number == expense.invoice_number,
            )
        ).all())
        for sup in supplements:
            db.delete(sup)
    db.delete(expense)
    db.commit()
    return True


def get_expenses_for_export(
    db: Session,
    status: ExpenseStatus | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 10000,
    include_inactive: bool = False,
) -> list[Expense]:
    """回傳符合篩選條件的費用清單供 CSV 匯出（最多 limit 筆，預設 10,000）。"""
    stmt = select(Expense).order_by(Expense.created_at.desc())
    if not include_inactive:
        stmt = stmt.where(Expense.is_active == True)
    if status:
        stmt = stmt.where(Expense.status == status)
    if date_from:
        stmt = stmt.where(Expense.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Expense.created_at <= date_to)
    return list(db.scalars(stmt.limit(limit)).all())


def update_expense(
    db: Session,
    expense_id: uuid.UUID,
    updates: dict,
) -> Expense | None:
    """部分更新 Expense 欄位（Dashboard 審核表單儲存用）。Returns None if not found."""
    expense = get_expense(db, expense_id)
    if not expense:
        return None
    for field, value in updates.items():
        if hasattr(expense, field):
            setattr(expense, field, value)
    db.commit()
    db.refresh(expense)
    return expense


def append_expense_image(
    db: Session,
    expense_id: uuid.UUID,
    new_url: str,
    image_type: str,
) -> Expense | None:
    """追加一張圖片網址至陣列末尾。image_type: 'expense' | 'item'"""
    expense = get_expense(db, expense_id)
    if not expense:
        return None
    field = "image_url" if image_type == "expense" else "item_image_url"
    # 必須建立新 list 才能觸發 SQLAlchemy change detection
    current = list(getattr(expense, field) or [])
    current.append(new_url)
    setattr(expense, field, current)
    db.commit()
    db.refresh(expense)
    return expense


def replace_expense_image(
    db: Session,
    expense_id: uuid.UUID,
    new_url: str,
    image_type: str,
    index: int,
) -> Expense | None:
    """替換陣列中指定索引的圖片網址。索引越界時回傳 None。"""
    expense = get_expense(db, expense_id)
    if not expense:
        return None
    field = "image_url" if image_type == "expense" else "item_image_url"
    current = list(getattr(expense, field) or [])
    if index < 0 or index >= len(current):
        return None
    current[index] = new_url
    setattr(expense, field, current)
    db.commit()
    db.refresh(expense)
    return expense


# ---------------------------------------------------------------------------
# 批次報帳彙整
# ---------------------------------------------------------------------------

# 主憑證優先級（越前面優先級越高；CREDIT_NOTE 不作為主憑證）
_PRIMARY_VOUCHER_PRIORITY: list[str] = [
    "INVOICE",
    "RECEIPT",
    "LABOR_SERVICE",
    "INSURANCE",
    "RENTAL",
    "ACCOMMODATION",
    "UTILITY",
    "POSTAGE",
    "TRANSPORTATION",
]


def _has_low_confidence_audit_field(result: VoucherOCRResult) -> bool:
    """任一關鍵稽核欄位信心 < KEY_FIELD_THRESHOLD → 需人工覆核。"""
    return bool(set(result.low_confidence_fields) & KEY_AUDIT_FIELDS)


def _safe_decimal(value: float | int | None) -> Decimal | None:
    """安全轉換為 Decimal，失敗時回傳 None。"""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _fix_digit_confusion(yyyy: int, mm: int, dd: int) -> tuple[int, int, int] | None:
    """
    嘗試修正因視覺相似數字混淆導致的無效月份或日期。
    只替換一個位置，優先處理月份，再處理日期。
    相似對：1↔7、0↔6、3↔8、5↔6
    """
    SIMILAR: list[tuple[str, str]] = [("1", "7"), ("7", "1"), ("0", "6"), ("6", "0"), ("3", "8"), ("8", "3"), ("5", "6"), ("6", "5")]

    def try_fix(s: str) -> list[int]:
        results = []
        for i, ch in enumerate(s):
            for a, b in SIMILAR:
                if ch == a:
                    candidate = int(s[:i] + b + s[i + 1:])
                    results.append(candidate)
        return results

    # 月份無效 → 嘗試修正
    if not (1 <= mm <= 12):
        for new_mm in try_fix(f"{mm:02d}"):
            if 1 <= new_mm <= 12:
                if not (1 <= dd <= 31):
                    for new_dd in try_fix(f"{dd:02d}"):
                        if 1 <= new_dd <= 31:
                            return yyyy, new_mm, new_dd
                else:
                    return yyyy, new_mm, dd

    # 日期無效 → 嘗試修正
    if not (1 <= dd <= 31):
        for new_dd in try_fix(f"{dd:02d}"):
            if 1 <= new_dd <= 31 and 1 <= mm <= 12:
                return yyyy, mm, new_dd

    return None


def _normalize_date_str(raw: str) -> str | None:
    """
    將台灣常見日期格式正規化為 YYYY-MM-DD（西元）。

    支援：
    - YYYY-MM-DD / YYYY/MM/DD（西元，直接回傳）
    - YYY/MM/DD、YYY-MM-DD、YYY.MM.DD（民國三位數，+1911）
    - YYY年M月D日（民國漢字）
    - YY/MM/DD（兩位數，< 200 視為民國，+1911）
    """
    import re as _re
    s = raw.strip()

    # 西元 YYYY-MM-DD
    if _re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s

    # 西元或民國數字格式：分隔符為 / - .
    m = _re.match(r"^(\d{2,4})[/\-.](\d{1,2})[/\-.](\d{1,2})$", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 200:
            y += 1911
        return _build_date_str(y, mo, d)

    # 民國漢字：115年3月12日
    m = _re.match(r"^(\d{2,4})年(\d{1,2})月(\d{1,2})日?$", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 200:
            y += 1911
        return _build_date_str(y, mo, d)

    return None


def _build_date_str(y: int, mo: int, d: int) -> str | None:
    """組合日期字串，若月或日超出範圍則嘗試自動修正相似數字混淆。"""
    if 1 <= mo <= 12 and 1 <= d <= 31:
        return f"{y:04d}-{mo:02d}-{d:02d}"
    fixed = _fix_digit_confusion(y, mo, d)
    if fixed:
        fy, fmo, fd = fixed
        return f"{fy:04d}-{fmo:02d}-{fd:02d}"
    return None


def _parse_expense_date(date_str: str | None) -> date | None:
    """將各種日期格式（含民國）轉為 date 物件，無法解析時回傳 None。"""
    if not date_str:
        return None
    if isinstance(date_str, date):
        return date_str
    normalized = _normalize_date_str(str(date_str))
    if normalized:
        try:
            return datetime.strptime(normalized, "%Y-%m-%d").date()
        except ValueError:
            pass
    return None


def _pick_primary_fields(ocr_results: list[VoucherOCRResult]) -> dict:
    """
    依照主憑證優先級選出第一順位的 OCR 結果，
    直接從 VoucherOCRResult Pydantic 欄位萃取，回傳可填入 Expense 的 kwargs dict。
    """
    category_map: dict[str, VoucherOCRResult] = {}
    for result in ocr_results:
        if (
            result.success
            and result.is_voucher
            and result.voucher_category
            and result.voucher_category != "CREDIT_NOTE"
            and result.voucher_category not in category_map
        ):
            category_map[result.voucher_category] = result

    primary: VoucherOCRResult | None = None
    for category in _PRIMARY_VOUCHER_PRIORITY:
        if category in category_map:
            primary = category_map[category]
            break

    if primary is None:
        return {}

    kwargs: dict = {}

    # ── 通用欄位（各類別均可能有）──────────────────────────
    kwargs["expense_date"] = _parse_expense_date(primary.expense_date)
    kwargs["total_amount"] = _safe_decimal(primary.total_amount)
    kwargs["tax_amount"] = _safe_decimal(primary.tax_amount)
    kwargs["net_amount"] = _safe_decimal(primary.net_amount)

    cat = primary.voucher_category

    # ── INVOICE ────────────────────────────────────────────
    if cat == "INVOICE":
        kwargs["invoice_number"] = primary.invoice_number
        kwargs["seller_name"] = primary.seller_name
        kwargs["seller_tax_id"] = primary.seller_tax_id

    # ── RECEIPT ────────────────────────────────────────────
    elif cat == "RECEIPT":
        kwargs["seller_name"] = primary.seller_name
        kwargs["item_description"] = primary.item_description

    # ── LABOR_SERVICE ──────────────────────────────────────
    elif cat == "LABOR_SERVICE":
        kwargs["item_description"] = primary.labor_content

    # ── INSURANCE ──────────────────────────────────────────
    elif cat == "INSURANCE":
        kwargs["seller_name"] = primary.insurer_name
        kwargs["item_description"] = primary.insurance_type

    # ── UTILITY ────────────────────────────────────────────
    elif cat == "UTILITY":
        kwargs["seller_name"] = primary.seller_name
        kwargs["item_description"] = primary.billing_period

    # ── RENTAL ─────────────────────────────────────────────
    elif cat == "RENTAL":
        kwargs["seller_name"] = primary.landlord_name
        kwargs["item_description"] = primary.rental_subtype

    # ── ACCOMMODATION ──────────────────────────────────────
    elif cat == "ACCOMMODATION":
        kwargs["seller_name"] = primary.hotel_name
        kwargs["item_description"] = (
            f"{primary.check_in_date} ~ {primary.check_out_date}"
            if primary.check_in_date and primary.check_out_date
            else primary.check_in_date or primary.check_out_date
        )

    # ── POSTAGE ────────────────────────────────────────────
    elif cat == "POSTAGE":
        kwargs["item_description"] = primary.postage_type

    # ── TRANSPORTATION ─────────────────────────────────────
    elif cat == "TRANSPORTATION":
        if primary.route_from and primary.route_to:
            kwargs["item_description"] = f"{primary.route_from} → {primary.route_to}"
        elif primary.route_from or primary.route_to:
            kwargs["item_description"] = primary.route_from or primary.route_to

    return {k: v for k, v in kwargs.items() if v is not None}


def _extract_image_path(image_path: str | dict | list) -> str:
    """
    將 Sprint 3 的 dict/list 圖片格式降維為純字串路徑。

    支援格式：
    - str         → 直接回傳
    - dict        → 取 'path' 鍵值（e.g. {"path": "...", "timestamp": ..., "message_id": ...}）
    - list        → 遞迴取第一項的路徑
    """
    if isinstance(image_path, dict):
        return str(image_path.get("path", ""))
    if isinstance(image_path, list):
        if not image_path:
            return ""
        return _extract_image_path(image_path[0])
    return str(image_path)


def _pick_primary_invoice_number(ocr_results: list[VoucherOCRResult]) -> str | None:
    """Flow B helper：從 OCR 結果中取第一個有 invoice_number 的主憑證號碼。"""
    for r in ocr_results:
        if r.success and r.is_voucher and r.invoice_number:
            return r.invoice_number
    return None


def _detect_duplicate_invoice(
    db: Session,
    user_id: uuid.UUID,
    invoice_number: str,
) -> uuid.UUID | None:
    """偵測同一使用者是否已有相同 invoice_number 的有效報帳。

    排除 REPLACED_VOID（已作廢）；找到則回傳最新那筆的 id，否則回傳 None。
    """
    existing = db.scalar(
        select(Expense.id)
        .where(
            Expense.user_id == user_id,
            Expense.invoice_number == invoice_number,
            Expense.status != ExpenseStatus.REPLACED_VOID,
            Expense.is_active == True,
        )
        .order_by(Expense.created_at.desc())
        .limit(1)
    )
    return existing


def create_batch_expense(
    db: Session,
    user_id: uuid.UUID,
    pending_images: list,
    ocr_results: list[VoucherOCRResult],
    user_description: str,
    uploader_name: str,
    uploader_dept: str,
    trigger_by: str | None = None,
    group_id: uuid.UUID | None = None,
    skip_auto_link: bool = False,
) -> Expense:
    """
    批次報帳彙整：將多張發票/憑證圖片整合為單一 Expense 記錄。

    費用彙整規則：
    - 主憑證優先級：INVOICE > RECEIPT > LABOR_SERVICE > INSURANCE > RENTAL >
                    ACCOMMODATION > UTILITY > POSTAGE > TRANSPORTATION
      （取第一順位欄位填入 expenses；CREDIT_NOTE 不作為主憑證）
    - total_amount：加總所有 is_voucher=True 且 total_amount 非 null 的金額
      （CREDIT_NOTE 的 total_amount 已確保為負數，直接加總）
    - status：
        NEEDS_MANUAL_REVIEW if total_amount is None
                            OR 任一有效憑證的關鍵稽核欄位信心 < KEY_FIELD_THRESHOLD
        PENDING otherwise
    """
    # ── 0. Flow B：重複憑證偵測 ────────────────────────────────────
    # 若主憑證的 invoice_number 已存在於同 user 的某筆 WAITING_RETURN 單，
    # 則補交物品照片到舊單並直接回傳，避免重複建帳。
    from services.relation_service import find_waiting_return_by_invoice
    primary_invoice = _pick_primary_invoice_number(ocr_results)
    if primary_invoice and user_id:
        existing_waiting = find_waiting_return_by_invoice(db, user_id, primary_invoice)
        if existing_waiting:
            item_paths_for_existing = [
                _extract_image_path(img)
                for img, r in zip(pending_images, ocr_results)
                if not (r.success and r.is_voucher)
            ]
            existing_waiting.item_image_url = list(existing_waiting.item_image_url or []) + item_paths_for_existing
            existing_waiting.status = ExpenseStatus.COMPLETED
            db.commit()
            db.refresh(existing_waiting)
            logger.info(
                "create_batch_expense Flow B: duplicate invoice=%s → COMPLETED expense=%s",
                primary_invoice, existing_waiting.serial_number,
            )
            return existing_waiting

    # ── 0b. 重複憑證偵測（高精度：invoice_number 完全比對）────────────
    # 若主憑證號碼已存在於同 user 的有效報帳，標記 possible_duplicate_of，
    # 仍正常建立 Expense，由 Dashboard 管理員裁決。
    duplicate_of_id: uuid.UUID | None = None
    if primary_invoice and user_id:
        duplicate_of_id = _detect_duplicate_invoice(db, user_id, primary_invoice)
        if duplicate_of_id:
            logger.info(
                "create_batch_expense: 偵測到重複憑證 invoice=%s，將標記 possible_duplicate_of=%s",
                primary_invoice, duplicate_of_id,
            )

    # ── 1. 從主憑證提取主欄位 ──────────────────────────────────────
    primary_fields = _pick_primary_fields(ocr_results)

    # ── 2. 加總所有有效憑證的金額 ──────────────────────────────────
    total_amount: Decimal | None = None
    for result in ocr_results:
        if result.success and result.is_voucher and result.total_amount is not None:
            amount = _safe_decimal(result.total_amount)
            if amount is not None:
                total_amount = (total_amount or Decimal("0")) + amount

    # 以加總結果覆蓋 primary_fields 中的 total_amount（保持一致性）
    if total_amount is not None:
        primary_fields["total_amount"] = total_amount

    # ── 3. 收集去重後的憑證類別 / 子類型 / 費用科目清單 ────────────
    seen_categories: list[str] = []
    seen_subtypes: list[str] = []
    seen_expense_cats: list[str] = []

    for result in ocr_results:
        if result.success and result.is_voucher:
            if result.voucher_category and result.voucher_category not in seen_categories:
                seen_categories.append(result.voucher_category)
            if result.voucher_subtype and result.voucher_subtype not in seen_subtypes:
                seen_subtypes.append(result.voucher_subtype)
            if result.expense_category and result.expense_category not in seen_expense_cats:
                seen_expense_cats.append(result.expense_category)

    voucher_categories_json: str | None = (
        json.dumps(seen_categories, ensure_ascii=False) if seen_categories else None
    )
    voucher_subtypes_json: str | None = (
        json.dumps(seen_subtypes, ensure_ascii=False) if seen_subtypes else None
    )
    expense_categories_json: str | None = (
        json.dumps(seen_expense_cats, ensure_ascii=False) if seen_expense_cats else None
    )

    # ── 4. 判斷狀態（含信心評分路由）────────────────────────────────
    low_confidence_detected = any(
        _has_low_confidence_audit_field(r)
        for r in ocr_results
        if r.success and r.is_voucher
    )
    status = (
        ExpenseStatus.NEEDS_MANUAL_REVIEW
        if total_amount is None or low_confidence_detected
        else ExpenseStatus.PENDING
    )

    # ── 5. 分離憑證圖片（image_url）與物品影像（item_image_url）────
    # _extract_image_path 防禦 Sprint 3 新格式（dict/list），確保 PostgreSQL VARCHAR[] 收到純字串
    voucher_images: list[str] = []
    item_images: list[str] = []
    for image_path, ocr_result in zip(pending_images, ocr_results):
        path_str = _extract_image_path(image_path)
        if ocr_result.success and ocr_result.is_voucher:
            voucher_images.append(path_str)
        else:
            item_images.append(path_str)

    # ── 6. INSERT Expense（含重試機制）────────────────────────────
    ocr_item_description: str | None = primary_fields.get("item_description")
    effective_item_description: str | None = (
        user_description.strip() if user_description and user_description.strip()
        else ocr_item_description
    )

    for _attempt in range(5):
        expense = Expense(
            user_id=user_id,
            serial_number=_generate_serial_number(db),
            image_url=voucher_images,
            item_image_url=item_images,
            uploader_name=uploader_name,
            uploader_dept=uploader_dept,
            user_description=user_description,
            image_count=len(pending_images),
            voucher_categories=voucher_categories_json,
            voucher_subtypes=voucher_subtypes_json,
            expense_categories=expense_categories_json,
            status=status,
            trigger_by=trigger_by,
            group_id=group_id,
            possible_duplicate_of=duplicate_of_id,
            submitter_name=primary_fields.get("submitter_name"),
            item_description=effective_item_description,
            expense_date=primary_fields.get("expense_date"),
            invoice_number=primary_fields.get("invoice_number"),
            total_amount=primary_fields.get("total_amount"),
            net_amount=primary_fields.get("net_amount"),
            tax_amount=primary_fields.get("tax_amount"),
            seller_tax_id=primary_fields.get("seller_tax_id"),
            seller_name=primary_fields.get("seller_name"),
        )
        db.add(expense)
        try:
            db.flush()  # 取得 expense.id，但尚未 commit
            break
        except IntegrityError as exc:
            db.rollback()
            if "uq_expenses_serial_number" not in str(exc.orig):
                raise
    else:
        raise RuntimeError("無法產生唯一案件流水號，請稍後再試")

    # ── 7. INSERT N 筆 ExpenseImage ───────────────────────────────
    for seq, (image_path, ocr_result) in enumerate(
        zip(pending_images, ocr_results), start=1
    ):
        # 儲存完整 VoucherOCRResult（含推理說明與信心分數），排除後端控制欄位
        ocr_json: str | None = None
        if ocr_result.success:
            try:
                ocr_json = ocr_result.model_dump_json(
                    exclude={"success", "error", "raw_response"}
                )
            except Exception:
                ocr_json = None

        # pending_images 元素為 Sprint 3 新格式 dict（含 path/timestamp/message_id）
        # 需取出 path 字串，避免 psycopg2 無法序列化 dict
        image_url_str: str = image_path["path"] if isinstance(image_path, dict) else str(image_path)

        expense_image = ExpenseImage(
            expense_id=expense.id,
            image_url=image_url_str,
            is_voucher=ocr_result.is_voucher if ocr_result.success else False,
            voucher_category=ocr_result.voucher_category if ocr_result.success else None,
            voucher_subtype=ocr_result.voucher_subtype if ocr_result.success else None,
            expense_category=ocr_result.expense_category if ocr_result.success else None,
            ocr_confidence=ocr_result.overall_confidence if ocr_result.success else None,
            sequence_order=seq,
            ocr_result=ocr_json,
        )
        db.add(expense_image)

    db.commit()
    db.refresh(expense)

    # ── 8. 自動關聯（情境 2/3A/3B）── 在 commit 之後執行，失敗不影響已建立的報帳
    if not skip_auto_link:
        from services import relation_service
        expense = relation_service.auto_link_records(db, expense, ocr_results, user_description)

    return expense


def pair_expenses(
    db: Session,
    supplement_id: uuid.UUID,
    original_id: uuid.UUID,
) -> Expense:
    """配對退貨補件與原始費用，設定 parent_id 與 referenced_invoice_number。"""
    supplement = db.get(Expense, supplement_id)
    original = db.get(Expense, original_id)
    if not supplement or not original:
        raise ValueError(f"pair_expenses: 費用不存在 supplement={supplement_id} original={original_id}")
    supplement.parent_id = original.id
    if original.invoice_number and not supplement.referenced_invoice_number:
        supplement.referenced_invoice_number = original.invoice_number
    db.commit()
    db.refresh(supplement)
    logger.info(
        "pair_expenses: supplement=%s → original=%s",
        supplement.serial_number, original.serial_number,
    )
    return supplement


def get_expense_images(
    db: Session,
    expense_id: uuid.UUID,
) -> list[ExpenseImage]:
    """查詢指定費用的所有圖片，按 sequence_order ASC 排序。"""
    return list(
        db.scalars(
            select(ExpenseImage)
            .where(ExpenseImage.expense_id == expense_id)
            .order_by(ExpenseImage.sequence_order.asc())
        ).all()
    )


# ---------------------------------------------------------------------------
# 排序
# ---------------------------------------------------------------------------

def reorder_expenses(db: Session, ordered_ids: list[str]) -> None:
    """
    依照前端傳入的 ID 順序，將 display_order 依序寫入 0, 1, 2, ...
    未出現在 ordered_ids 的資料保持原值不動。
    """
    for position, expense_id in enumerate(ordered_ids):
        eid = uuid.UUID(expense_id)
        expense = db.get(Expense, eid)
        if expense:
            expense.display_order = position
    db.commit()


# ---------------------------------------------------------------------------
# 退回 & 補件
# ---------------------------------------------------------------------------

def reject_expense(
    db: Session,
    expense_id: str | uuid.UUID,
    reject_reason: str,
) -> Expense | None:
    """將指定報帳單狀態更新為 REPLACED_VOID（作廢），寫入退回原因。回傳含 user_id 的 Expense 物件。"""
    eid = uuid.UUID(expense_id) if isinstance(expense_id, str) else expense_id
    expense = db.get(Expense, eid)
    if not expense:
        return None
    expense.status = ExpenseStatus.REPLACED_VOID
    expense.reject_reason = reject_reason
    db.commit()
    db.refresh(expense)
    return expense


def reupload_expense(
    db: Session,
    expense_id: str,
    new_image_path: str,
    # OCR-extracted fields（補件後重新辨識的結果）
    submitter_name: str | None = None,
    item_description: str | None = None,
    expense_date: date | str | None = None,
    invoice_number: str | None = None,
    total_amount: Decimal | None = None,
    net_amount: Decimal | None = None,
    tax_amount: Decimal | None = None,
    seller_tax_id: str | None = None,
    seller_name: str | None = None,
    needs_manual_review: bool = False,
) -> Expense | None:
    """
    補件：將新照片覆蓋舊單的第一張圖片，更新 OCR 欄位，狀態改回 PENDING，清除退回原因。
    若原單不存在則回傳 None。
    """
    expense = db.get(Expense, uuid.UUID(expense_id))
    if not expense:
        return None

    # 更新圖片：以新圖片取代第一張，保留其餘（若原本為空則直接新增）
    current_images = list(expense.image_url or [])
    if current_images:
        current_images[0] = new_image_path
    else:
        current_images = [new_image_path]
    expense.image_url = current_images

    parsed_expense_date: date | None = _parse_expense_date(expense_date)

    # 更新 OCR 欄位
    expense.submitter_name = submitter_name
    expense.item_description = item_description
    expense.expense_date = parsed_expense_date
    expense.invoice_number = invoice_number
    expense.total_amount = total_amount
    expense.net_amount = net_amount
    expense.tax_amount = tax_amount
    expense.seller_tax_id = seller_tax_id
    expense.seller_name = seller_name

    # 重設狀態：補件成功 → SUPPLEMENTED；OCR 失敗 → NEEDS_MANUAL_REVIEW
    expense.status = ExpenseStatus.NEEDS_MANUAL_REVIEW if needs_manual_review else ExpenseStatus.SUPPLEMENTED
    expense.reject_reason = None

    db.commit()
    db.refresh(expense)
    return expense


# ---------------------------------------------------------------------------
# 圖片分類修正 / 批次組查詢 / 跨交易圖片搬移
# ---------------------------------------------------------------------------

def update_expense_image(
    db: Session,
    expense_id: uuid.UUID,
    image_id: uuid.UUID,
    updates: dict,
) -> ExpenseImage | None:
    """更新 ExpenseImage 的分類欄位，並同步 Expense 的 image_url / item_image_url 陣列。"""
    image = db.get(ExpenseImage, image_id)
    if not image or image.expense_id != expense_id:
        return None

    expense = db.get(Expense, expense_id)
    if not expense:
        return None

    old_is_voucher = image.is_voucher
    new_is_voucher = updates.get("is_voucher", old_is_voucher)

    for field, value in updates.items():
        setattr(image, field, value)

    # 若 is_voucher 改變，同步搬移 URL 於 Expense 的兩個陣列之間
    if new_is_voucher != old_is_voucher:
        if old_is_voucher:
            # True → False：從 image_url 移除，加入 item_image_url
            src_list = list(expense.image_url or [])
            dst_list = list(expense.item_image_url or [])
            if image.image_url in src_list:
                src_list.remove(image.image_url)
            dst_list.append(image.image_url)
            expense.image_url = src_list
            expense.item_image_url = dst_list
        else:
            # False → True：從 item_image_url 移除，加入 image_url
            src_list = list(expense.item_image_url or [])
            dst_list = list(expense.image_url or [])
            if image.image_url in src_list:
                src_list.remove(image.image_url)
            dst_list.append(image.image_url)
            expense.item_image_url = src_list
            expense.image_url = dst_list

    db.commit()
    db.refresh(image)
    return image


def get_batch_expenses(
    db: Session,
    expense_id: uuid.UUID,
) -> list[Expense]:
    """回傳與指定 expense 同一批次（相同 group_id）的所有 Expense，含 images 關聯。"""
    source = db.get(Expense, expense_id)
    if not source:
        return []

    if source.group_id is None:
        db.scalars(
            select(ExpenseImage).where(ExpenseImage.expense_id == expense_id)
        ).all()
        return [source]

    return list(
        db.scalars(
            select(Expense)
            .where(Expense.group_id == source.group_id)
            .options(selectinload(Expense.images))
            .order_by(Expense.created_at.asc())
        ).all()
    )


def move_expense_image(
    db: Session,
    source_expense_id: uuid.UUID,
    image_id: uuid.UUID,
    target_expense_id: uuid.UUID,
) -> ExpenseImage | None:
    """將 ExpenseImage 從一筆 Expense 搬移至另一筆，同步更新兩邊的 image_url / item_image_url 陣列。"""
    image = db.get(ExpenseImage, image_id)
    if not image or image.expense_id != source_expense_id:
        return None

    source = db.get(Expense, source_expense_id)
    target = db.get(Expense, target_expense_id)
    if not source or not target:
        return None

    src_field = "image_url" if image.is_voucher else "item_image_url"

    # 從 source 移除
    src_list = list(getattr(source, src_field) or [])
    if image.image_url in src_list:
        src_list.remove(image.image_url)
    setattr(source, src_field, src_list)

    # 更新 ownership
    image.expense_id = target_expense_id

    # 加入 target
    tgt_list = list(getattr(target, src_field) or [])
    tgt_list.append(image.image_url)
    setattr(target, src_field, tgt_list)

    # 重排 source 剩餘圖片的 sequence_order
    remaining = list(
        db.scalars(
            select(ExpenseImage)
            .where(ExpenseImage.expense_id == source_expense_id)
            .where(ExpenseImage.id != image_id)
            .order_by(ExpenseImage.sequence_order.asc())
        ).all()
    )
    for i, img in enumerate(remaining, start=1):
        img.sequence_order = i

    db.commit()
    db.refresh(image)
    return image
