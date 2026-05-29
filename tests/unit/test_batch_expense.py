"""
Unit tests for services.expense_service.create_batch_expense()

費用彙整邏輯驗證。直接 mock DB session，不依賴真實資料庫連線。
"""

# ---------------------------------------------------------------------------
# 最早期 patch：在所有 import 之前，注入假的 psycopg2 至 sys.modules
# 這樣 core/database.py 的 create_engine（PostgreSQL dialect）才能順利 import
# ---------------------------------------------------------------------------

import sys
from unittest.mock import MagicMock

# 注入假 psycopg2（讓 SQLAlchemy PostgreSQL dialect 可以 import，但不真的連線）
_fake_psycopg2 = MagicMock()
_fake_psycopg2.extensions = MagicMock()
_fake_psycopg2.__version__ = "2.9.9"
sys.modules.setdefault("psycopg2", _fake_psycopg2)
sys.modules.setdefault("psycopg2.extensions", _fake_psycopg2.extensions)
sys.modules.setdefault("psycopg2.extras", MagicMock())

# ---------------------------------------------------------------------------
# 標準 import
# ---------------------------------------------------------------------------

import json
import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest

# 在 core.database 的 engine 建立之前替換 settings，避免真實 PG 連線
# （但 core/database.py 在 module level 就 create_engine，
#   所以我們在這裡先設定 mock psycopg2，讓 dialect import 成功；
#   engine.connect() 的真實呼叫才會失敗，但我們 mock 了 session 所以不會呼叫到）
from models.expense import ExpenseStatus
from schemas.ocr import VoucherOCRResult


# ---------------------------------------------------------------------------
# Helper：建立 VoucherOCRResult
# ---------------------------------------------------------------------------

def make_ocr_result(
    is_voucher: bool = True,
    category: str = "INVOICE",
    total_amount: float | None = 1000.0,
    success: bool = True,
    extra_fields: dict | None = None,
) -> VoucherOCRResult:
    """建立測試用 VoucherOCRResult。"""
    if not is_voucher:
        return VoucherOCRResult(
            is_voucher=False,
            success=success,
            error=None if success else "OCR failed",
        )

    if not success:
        return VoucherOCRResult(
            is_voucher=False,
            success=False,
            error="OCR failed",
        )

    base: dict = {
        "invoice_number": "AB-12345678",
        "seller_name": "測試商行",
        "seller_tax_id": "12345678",
        "total_amount": total_amount,
        "expense_date": "2026-04-01",
    }
    if extra_fields:
        base.update(extra_fields)

    return VoucherOCRResult(
        is_voucher=True,
        voucher_category=category,
        success=True,
        **base,
    )


# ---------------------------------------------------------------------------
# Helper：呼叫 create_batch_expense，完全 mock DB session
# ---------------------------------------------------------------------------

def _call_create_batch(
    ocr_results: list[VoucherOCRResult],
    pending_images: list[str] | None = None,
    serial_number: str = "EXP-202604-0001",
):
    """
    呼叫 create_batch_expense，mock 掉 DB session 與流水號產生。
    回傳被建立的 Expense 物件。
    """
    from services.expense_service import create_batch_expense

    if pending_images is None:
        pending_images = [f"uploads/test_{i}.jpg" for i in range(len(ocr_results))]

    # 建立 mock DB session（不真的連接 DB）
    db = MagicMock()
    db.flush.return_value = None
    db.commit.return_value = None
    db.add.return_value = None
    db.refresh.return_value = None

    user_id = uuid.uuid4()

    with patch(
        "services.expense_service._generate_serial_number",
        return_value=serial_number,
    ), patch(
        "services.relation_service.find_waiting_return_by_invoice",
        return_value=None,
    ), patch(
        "services.expense_service._detect_duplicate_invoice",
        return_value=None,
    ):
        result = create_batch_expense(
            db=db,
            user_id=user_id,
            pending_images=pending_images,
            ocr_results=ocr_results,
            user_description="測試備註",
            uploader_name="王小明",
            uploader_dept="攝影組",
            skip_auto_link=True,
        )

    return result


# ---------------------------------------------------------------------------
# 測試案例 1：多財務憑證加總
# ---------------------------------------------------------------------------

def test_batch_multiple_invoices_total_amount() -> None:
    """3 張 INVOICE 憑證，total_amount 應正確累加。"""
    ocr_results = [
        make_ocr_result(category="INVOICE", total_amount=1000.0),
        make_ocr_result(category="INVOICE", total_amount=2000.0),
        make_ocr_result(category="INVOICE", total_amount=500.0),
    ]
    expense = _call_create_batch(ocr_results)

    assert expense.total_amount == Decimal("3500.00"), (
        f"預期 3500.00，實際 {expense.total_amount}"
    )
    assert expense.status == ExpenseStatus.PENDING


# ---------------------------------------------------------------------------
# 測試案例 2：CREDIT_NOTE 負數自動扣除
# ---------------------------------------------------------------------------

def test_batch_credit_note_deduction() -> None:
    """INVOICE 2000 + CREDIT_NOTE -350 → 合計 1650。"""
    ocr_results = [
        make_ocr_result(category="INVOICE", total_amount=2000.0),
        make_ocr_result(
            category="CREDIT_NOTE",
            total_amount=-350.0,
            extra_fields={
                "invoice_number": "CD-87654321",
                "seller_name": "退貨商行",
                "expense_date": "2026-04-07",
            },
        ),
    ]
    expense = _call_create_batch(ocr_results)

    assert expense.total_amount == Decimal("1650.00"), (
        f"預期 1650.00（含折讓扣除），實際 {expense.total_amount}"
    )
    assert expense.status == ExpenseStatus.PENDING


# ---------------------------------------------------------------------------
# 測試案例 3：部分 null 金額（只加總非 null 部分）
# ---------------------------------------------------------------------------

def test_batch_partial_null_amounts() -> None:
    """3 張憑證，其中 1 張 total_amount=None，只加總有效部分，status=PENDING。"""
    ocr_results = [
        make_ocr_result(category="INVOICE", total_amount=1500.0),
        make_ocr_result(category="RECEIPT", total_amount=None),
        make_ocr_result(category="RECEIPT", total_amount=300.0),
    ]
    expense = _call_create_batch(ocr_results)

    assert expense.total_amount == Decimal("1800.00"), (
        f"預期 1800.00（忽略 null），實際 {expense.total_amount}"
    )
    assert expense.status == ExpenseStatus.PENDING


# ---------------------------------------------------------------------------
# 測試案例 4：全部 null → NEEDS_MANUAL_REVIEW
# ---------------------------------------------------------------------------

def test_batch_all_null_amounts() -> None:
    """所有憑證 total_amount=null → status=NEEDS_MANUAL_REVIEW。"""
    ocr_results = [
        make_ocr_result(category="INVOICE", total_amount=None),
        make_ocr_result(category="RECEIPT", total_amount=None),
    ]
    expense = _call_create_batch(ocr_results)

    assert expense.total_amount is None
    assert expense.status == ExpenseStatus.NEEDS_MANUAL_REVIEW


# ---------------------------------------------------------------------------
# 測試案例 5：voucher_categories 去重正確
# ---------------------------------------------------------------------------

def test_batch_voucher_categories_dedup() -> None:
    """多張 INVOICE + RECEIPT + 重複的 INVOICE → voucher_categories 不重複。"""
    ocr_results = [
        make_ocr_result(category="INVOICE", total_amount=1000.0),
        make_ocr_result(category="RECEIPT", total_amount=200.0),
        make_ocr_result(category="INVOICE", total_amount=800.0),  # 重複
    ]
    expense = _call_create_batch(ocr_results)

    assert expense.voucher_categories is not None
    categories = json.loads(expense.voucher_categories)
    assert sorted(categories) == sorted(["INVOICE", "RECEIPT"]), (
        f"預期 ['INVOICE', 'RECEIPT']（無重複），實際 {categories}"
    )
    assert len(categories) == 2


# ---------------------------------------------------------------------------
# 測試案例 6：image_count 等於 len(pending_images)
# ---------------------------------------------------------------------------

def test_batch_image_count_matches_pending() -> None:
    """image_count 欄位應等於 pending_images 的長度。"""
    pending_images = [
        "uploads/img_001.jpg",
        "uploads/img_002.jpg",
        "uploads/img_003.jpg",
        "uploads/img_004.jpg",
    ]
    ocr_results = [
        make_ocr_result(category="INVOICE", total_amount=500.0)
        for _ in pending_images
    ]
    expense = _call_create_batch(ocr_results, pending_images=pending_images)

    assert expense.image_count == len(pending_images), (
        f"預期 image_count={len(pending_images)}，實際 {expense.image_count}"
    )


# ---------------------------------------------------------------------------
# 測試案例 7：主憑證優先級（INVOICE > RECEIPT）
# ---------------------------------------------------------------------------

def test_batch_primary_voucher_priority() -> None:
    """有 RECEIPT 和 INVOICE 時，主憑證應選 INVOICE（優先級更高）。"""
    ocr_results = [
        make_ocr_result(
            category="RECEIPT",
            total_amount=200.0,
            extra_fields={"seller_name": "RECEIPT 商行", "item_description": "文具"},
        ),
        make_ocr_result(
            category="INVOICE",
            total_amount=1000.0,
            extra_fields={
                "invoice_number": "AB-99999999",
                "seller_name": "INVOICE 公司",
                "seller_tax_id": "87654321",
            },
        ),
    ]
    expense = _call_create_batch(ocr_results)

    # 主欄位應來自 INVOICE
    assert expense.invoice_number == "AB-99999999"
    assert expense.seller_name == "INVOICE 公司"
    assert expense.seller_tax_id == "87654321"
    # total_amount 為加總（200 + 1000）
    assert expense.total_amount == Decimal("1200.00")


# ---------------------------------------------------------------------------
# 測試案例 8：非憑證圖片不納入加總
# ---------------------------------------------------------------------------

def test_batch_non_voucher_excluded() -> None:
    """is_voucher=False 的圖片不應納入 total_amount 加總，也不出現在 voucher_categories。"""
    ocr_results = [
        make_ocr_result(category="INVOICE", total_amount=1000.0),
        make_ocr_result(is_voucher=False),  # 非憑證
    ]
    expense = _call_create_batch(ocr_results)

    assert expense.total_amount == Decimal("1000.00")
    assert expense.voucher_categories is not None
    categories = json.loads(expense.voucher_categories)
    assert "INVOICE" in categories
    assert len(categories) == 1  # 非憑證不應出現
