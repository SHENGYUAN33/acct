"""
Relation Service — 劇組報帳關聯邏輯

處理四種情境：
  情境 1：WAITING_RETURN — 使用者標記「待退貨」，物品照補傳後自動結清
  情境 2：VOID_REPLACE   — 換貨換單，舊單作廢，新單以 parent_id 串聯
  情境 3A：CREDIT_NOTE   — 折讓單自動連結原始發票，計算淨額
  情境 3B：SUPPLEMENT    — 差額補足，以日期 + 金額 + 店家名稱模糊比對原單
"""

import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from core.config import settings
from models.expense import Expense, ExpenseStatus
from schemas.ocr import VoucherOCRResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 情境 1：WAITING_RETURN 關鍵字偵測
# ---------------------------------------------------------------------------

_WAITING_RETURN_KEYWORDS = {"待退貨", "待退", "退貨中", "退貨未完成"}


def detect_waiting_return(user_description: str | None) -> bool:
    """若 user_description 含「待退貨」相關關鍵字，回傳 True。"""
    if not user_description:
        return False
    return any(kw in user_description for kw in _WAITING_RETURN_KEYWORDS)


def attach_item_photos_to_waiting_return(
    db: Session,
    user_id: uuid.UUID,
    item_paths: list[str],
    invoice_number: str | None = None,
) -> Expense | None:
    """
    情境 1 自動結清：找到該使用者的 WAITING_RETURN 單，補入物品照片並切換為 COMPLETED。

    搜尋優先級：
    1. invoice_number 精準比對（Flow A：說明文字寫裸號碼 AB-12345678）
    2. 同 user 最新一筆 WAITING_RETURN（fallback）
    """
    base = and_(
        Expense.user_id == user_id,
        Expense.status == ExpenseStatus.WAITING_RETURN,
        Expense.is_active == True,
    )

    waiting: Expense | None = None
    if invoice_number:
        waiting = db.scalar(
            select(Expense)
            .where(and_(base, Expense.invoice_number == invoice_number))
            .order_by(Expense.created_at.desc())
        )

    if not waiting:
        waiting = db.scalar(
            select(Expense).where(base).order_by(Expense.created_at.desc())
        )

    if not waiting:
        return None

    waiting.item_image_url = list(waiting.item_image_url or []) + item_paths
    waiting.status = ExpenseStatus.COMPLETED
    db.commit()
    db.refresh(waiting)
    logger.info(
        "attach_item_photos_to_waiting_return: COMPLETED expense=%s user=%s (invoice_hint=%s)",
        waiting.serial_number, user_id, invoice_number,
    )
    return waiting


def find_waiting_return_by_invoice(
    db: Session,
    user_id: uuid.UUID,
    invoice_number: str | None,
) -> Expense | None:
    """
    Flow B：重複上傳原始憑證時，以發票號碼精準查詢同 user 的 WAITING_RETURN 單。
    """
    if not invoice_number:
        return None
    return db.scalar(
        select(Expense)
        .where(and_(
            Expense.user_id == user_id,
            Expense.invoice_number == invoice_number,
            Expense.status == ExpenseStatus.WAITING_RETURN,
            Expense.is_active == True,
        ))
        .order_by(Expense.created_at.desc())
    )


# ---------------------------------------------------------------------------
# 情境 2：作廢原因提取
# ---------------------------------------------------------------------------

_VOID_REASON_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"換貨|換單"), "換貨換單"),
    (re.compile(r"打錯統編|統編錯誤"), "統編填寫錯誤"),
    (re.compile(r"金額錯誤|打錯金額"), "金額填寫錯誤"),
    (re.compile(r"作廢|重開"), "作廢重開"),
]


def _extract_void_reason(user_description: str | None) -> str | None:
    """從說明文字 regex 比對作廢原因，回傳人類可讀標籤。"""
    if not user_description:
        return None
    for pattern, label in _VOID_REASON_PATTERNS:
        if pattern.search(user_description):
            return label
    return None


# ---------------------------------------------------------------------------
# 情境 2/3A：從 OCR 結果與說明文字提取關聯訊號
# ---------------------------------------------------------------------------

_INVOICE_REF_PATTERN = re.compile(r"\[([A-Z]{2}-\d{8})\]")

# 待退貨偵測：匹配「待退貨 AB-12345678」或「待退貨 AB12345678」
_RETURN_SUPPLEMENT_PATTERN = re.compile(r"待退貨\s*([A-Z]{2}-?\d{8})")


def _detect_return_supplement_invoice(user_description: str | None) -> str | None:
    """
    偵測說明文字中的待退貨憑證號碼。
    格式：「待退貨 AB-12345678」或「待退貨 AB12345678」
    回傳正規化後的發票號碼（含連字號），或 None。
    """
    if not user_description:
        return None
    match = _RETURN_SUPPLEMENT_PATTERN.search(user_description)
    if not match:
        return None
    raw = match.group(1)
    # 正規化：無連字號者補上（AB12345678 → AB-12345678）
    if "-" not in raw and len(raw) == 10:
        return f"{raw[:2]}-{raw[2:]}"
    return raw


def _extract_relation(
    ocr_results: list[VoucherOCRResult],
    user_description: str | None,
) -> dict | None:
    """
    偵測是否為換單或折讓情境。

    回傳 {'type': 'VOID_REPLACE'|'CREDIT_NOTE', 'invoice_number': str}，
    或 None（無關聯訊號）。

    優先順序：
    1. Gemini 辨識出 CREDIT_NOTE 且有 original_invoice_number → CREDIT_NOTE
    2. 說明文字含括號發票格式 [AB-12345678] → VOID_REPLACE
    """
    for result in ocr_results:
        if (
            result.success
            and result.is_voucher
            and result.voucher_category == "CREDIT_NOTE"
            and result.original_invoice_number
        ):
            return {"type": "CREDIT_NOTE", "invoice_number": result.original_invoice_number}

    if user_description:
        match = _INVOICE_REF_PATTERN.search(user_description)
        if match:
            return {"type": "VOID_REPLACE", "invoice_number": match.group(1)}

    return None


# ---------------------------------------------------------------------------
# 情境 3B：差額補足提示解析
# ---------------------------------------------------------------------------

_SUPPLEMENT_PATTERN = re.compile(
    r"(?:之前收據|補差額|差額補足|原單).*?日期\s*[：:]\s*(\d{4}-\d{2}-\d{2}).*?金額\s*[：:]\s*(\d+(?:\.\d+)?)",
    re.DOTALL,
)


def _detect_supplement_hint(user_description: str | None) -> dict | None:
    """
    解析說明文字中的差額補足提示。
    回傳 {'date': date, 'amount': Decimal} 或 None。

    範例可解析文字：「之前收據日期：2024-01-15、金額：500」
    """
    if not user_description:
        return None
    match = _SUPPLEMENT_PATTERN.search(user_description)
    if not match:
        return None
    try:
        return {
            "date": datetime.strptime(match.group(1), "%Y-%m-%d").date(),
            "amount": Decimal(match.group(2)),
        }
    except (ValueError, Exception):
        return None


# ---------------------------------------------------------------------------
# 情境 3B：三維模糊搜尋（日期 × 金額 × 店家名稱）
# ---------------------------------------------------------------------------

def search_fuzzy_expense(
    db: Session,
    user_id: uuid.UUID,
    ref_date: date,
    ref_amount: Decimal,
    ref_seller: str | None = None,
    date_tolerance_days: int = 3,
    amount_tolerance_pct: float = 0.10,
) -> Expense | None:
    """
    三維模糊搜尋：日期 ±3 天 + 金額 ±10% + 店家名稱比對。

    搜尋策略（由精到粗）：
    1. 符合日期、金額、完整 seller_name → 最高信心
    2. 符合日期、金額、seller_name 前 4 字元前綴 → 處理縮寫（「小林」→「小林器材有限公司」）
    3. 符合日期、金額（無 seller_name） → fallback
    """
    lower = ref_amount * Decimal(str(1 - amount_tolerance_pct))
    upper = ref_amount * Decimal(str(1 + amount_tolerance_pct))
    date_min = ref_date - timedelta(days=date_tolerance_days)
    date_max = ref_date + timedelta(days=date_tolerance_days)

    base_filters = and_(
        Expense.user_id == user_id,
        Expense.is_active == True,
        Expense.status != ExpenseStatus.REPLACED_VOID,
        Expense.expense_date >= date_min,
        Expense.expense_date <= date_max,
        Expense.total_amount >= lower,
        Expense.total_amount <= upper,
    )

    if ref_seller:
        # Step 1: 完整名稱比對
        result = db.scalar(
            select(Expense)
            .where(and_(base_filters, Expense.seller_name == ref_seller))
            .order_by(Expense.created_at.desc())
        )
        if result:
            return result

        # Step 2: 前 4 字元前綴比對
        prefix = ref_seller[:4]
        result = db.scalar(
            select(Expense)
            .where(and_(base_filters, Expense.seller_name.like(f"{prefix}%")))
            .order_by(Expense.created_at.desc())
        )
        if result:
            return result

    # Step 3: Fallback（無 seller_name 或前兩步未找到）
    return db.scalar(
        select(Expense).where(base_filters).order_by(Expense.created_at.desc())
    )


# ---------------------------------------------------------------------------
# 共用 DB 查詢工具
# ---------------------------------------------------------------------------

def find_active_expense_by_invoice_number(
    db: Session, invoice_number: str
) -> Expense | None:
    """依發票號碼查詢最新的 is_active=True 報帳。"""
    return db.scalar(
        select(Expense)
        .where(and_(
            Expense.invoice_number == invoice_number,
            Expense.is_active == True,
        ))
        .order_by(Expense.created_at.desc())
    )


def _find_by_seller_within_days(
    db: Session,
    seller_name: str | None,
    ref_date: date | None,
    days: int = 7,
) -> Expense | None:
    """依店家名稱（前綴比對）在 days 天內搜尋最新的有效報帳。"""
    if not seller_name or not ref_date:
        return None
    date_min = ref_date - timedelta(days=days)
    prefix = seller_name[:4]
    return db.scalar(
        select(Expense)
        .where(and_(
            Expense.seller_name.like(f"{prefix}%"),
            Expense.is_active == True,
            Expense.expense_date >= date_min,
            Expense.expense_date <= ref_date,
            Expense.status != ExpenseStatus.REPLACED_VOID,
        ))
        .order_by(Expense.expense_date.desc())
    )


# ---------------------------------------------------------------------------
# 主入口：auto_link_records（create_batch_expense 提交後呼叫）
# ---------------------------------------------------------------------------

def auto_link_records(
    db: Session,
    new_expense: Expense,
    ocr_results: list[VoucherOCRResult],
    user_description: str | None,
) -> Expense:
    """
    報帳建立後自動偵測關聯訊號，執行以下三種處理：

    VOID_REPLACE：找到舊單 → 舊單 is_active=False + REPLACED_VOID，新單 parent_id 指向舊單
    CREDIT_NOTE ：找到原始發票 → 建立折讓關聯，調整原單 net_amount
    SUPPLEMENT  ：模糊搜尋原單 → 建立補差額關聯

    任何例外只 log，不影響已提交的新報帳。
    """
    try:
        # 待退貨偵測（enable_waiting_return_text_mode=True 時生效）
        if settings.enable_waiting_return_text_mode:
            rs_invoice = _detect_return_supplement_invoice(user_description)
            if rs_invoice:
                # 「待退貨 AB-12345678」→ 補件（物品照）
                new_expense.relation_type = "RETURN_SUPPLEMENT"
                new_expense.referenced_invoice_number = rs_invoice
                db.commit()
                logger.info(
                    "auto_link_records RETURN_SUPPLEMENT: new=%s invoice=%s",
                    new_expense.serial_number, rs_invoice,
                )
                db.refresh(new_expense)
                return new_expense
            elif detect_waiting_return(user_description):
                # 「待退貨」無發票號碼 → 原始待退貨憑證
                new_expense.status = ExpenseStatus.WAITING_RETURN
                db.commit()
                logger.info(
                    "auto_link_records WAITING_RETURN: new=%s",
                    new_expense.serial_number,
                )
                db.refresh(new_expense)
                return new_expense

        relation = _extract_relation(ocr_results, user_description)

        if relation:
            ref_inv = relation["invoice_number"]
            original = find_active_expense_by_invoice_number(db, ref_inv)

            if relation["type"] == "VOID_REPLACE" and original:
                # 作廢舊單
                original.status = ExpenseStatus.REPLACED_VOID
                original.is_active = False
                original.void_reason = _extract_void_reason(user_description) or "換貨換單"
                # 串聯新單
                new_expense.parent_id = original.id
                new_expense.relation_type = "VOID_REPLACE"
                new_expense.referenced_invoice_number = ref_inv
                db.commit()
                logger.info(
                    "auto_link_records VOID_REPLACE: new=%s → old=%s",
                    new_expense.serial_number, original.serial_number,
                )

            elif relation["type"] == "CREDIT_NOTE":
                # 折讓：優先比對發票號碼，備援比對店家名稱 + 7 天內
                target = original or _find_by_seller_within_days(
                    db, new_expense.seller_name, new_expense.expense_date, days=7
                )
                if target:
                    new_expense.parent_id = target.id
                    new_expense.relation_type = "CREDIT_NOTE"
                    new_expense.referenced_invoice_number = ref_inv
                    # 折讓單 total_amount 為負數，加總後為淨額
                    if target.total_amount is not None and new_expense.total_amount is not None:
                        target.net_amount = target.total_amount + new_expense.total_amount
                    db.commit()
                    logger.info(
                        "auto_link_records CREDIT_NOTE: new=%s → original=%s",
                        new_expense.serial_number, target.serial_number,
                    )

        else:
            # 情境 3B：差額補足
            hint = _detect_supplement_hint(user_description)
            if hint and new_expense.user_id:
                target = search_fuzzy_expense(
                    db,
                    user_id=new_expense.user_id,
                    ref_date=hint["date"],
                    ref_amount=hint["amount"],
                    ref_seller=new_expense.seller_name,
                )
                if target:
                    new_expense.parent_id = target.id
                    new_expense.relation_type = "SUPPLEMENT"
                    db.commit()
                    logger.info(
                        "auto_link_records SUPPLEMENT: new=%s → original=%s",
                        new_expense.serial_number, target.serial_number,
                    )

    except Exception as exc:
        logger.error("auto_link_records failed: %s", exc, exc_info=True)

    db.refresh(new_expense)
    return new_expense


# ---------------------------------------------------------------------------
# 情境 4：孤立物品圖向前關聯（auto_split_service 呼叫）
# ---------------------------------------------------------------------------

def attach_orphan_images_to_recent_expense(
    db: Session,
    user_id: uuid.UUID,
    orphan_paths: list[str],
    window_minutes: int = 10,
) -> Expense | None:
    """
    將 batch 開頭的孤立物品圖（無憑證先行）補入同用戶 window_minutes 分鐘內的最新報帳。
    回傳更新後的 Expense，或 None（無可關聯的最近記錄）。
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=window_minutes)
    recent = db.scalar(
        select(Expense)
        .where(and_(
            Expense.user_id == user_id,
            Expense.is_active == True,
            Expense.upload_date >= cutoff,
        ))
        .order_by(Expense.upload_date.desc())
    )
    if not recent:
        return None

    recent.item_image_url = list(recent.item_image_url or []) + orphan_paths
    db.commit()
    db.refresh(recent)
    logger.info(
        "attach_orphan_images: attached %d image(s) to expense=%s",
        len(orphan_paths), recent.serial_number,
    )
    return recent
