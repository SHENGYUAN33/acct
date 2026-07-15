"""
Unit Tests — 四種補件情境的報表呈現邏輯 (P0)

測試範圍：
1. csv_remark：CSV 備注欄決策矩陣（沖銷分錄 / 換單作廢 / 一般退件）
2. VOID_REPLACE（換新發票）：auto_link_records 自動比對 + create_reversal_expense 沖銷分錄
3. CREDIT_NOTE（折讓單）：auto_link_records 自動轉負、不建立沖銷分錄
4. RETURN_SUPPLEMENT / AMOUNT_CORRECTION（換貨收據 / 改金額）：pair_expenses 建立 RETURN_REVERSAL
5. 定期報表期間呈現：get_expenses_for_export 以 upload_date 篩選，驗證「舊單只在自己上傳期出現、
   沖銷分錄落在綁定當下那一期」是否符合業務預期（狀況一 / 狀況二）

為何需要這些測試：
- 四種情境的沖銷分錄建立時機不同（有些在上傳當下自動建立，有些要等人工在 Dashboard 配對），
  這直接決定了同一筆交易的正負數會出現在報表的哪一期，錯了會導致金額重複認列或漏記
- 先前人工審查發現 LIFF 待退貨情境A（VOID_REPLACE）永遠不會產生沖銷分錄，此檔案將其固定為
  迴歸測試（regression test），避免日後被誤判為「已修好」
- 直接呼叫真正的 service 函式（create_reversal_expense / auto_link_records / pair_expenses /
  get_expenses_for_export / csv_remark），而非重寫邏輯，才能在邏輯被改動時真正被測試抓到
"""

import json
import sys
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

# ── 最早期 patch：注入假 psycopg2，避免 import 時觸發真實 DB 連線 ──────
_fake_psycopg2 = MagicMock()
_fake_psycopg2.__version__ = "2.9.9"
_fake_psycopg2.Error = Exception
sys.modules.setdefault("psycopg2", _fake_psycopg2)
sys.modules.setdefault("psycopg2.extensions", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.types import TEXT, TypeDecorator

from core.relation_rules import csv_remark
from models.expense import Expense, ExpenseStatus
from schemas.ocr import VoucherOCRResult
from services.expense_service import create_reversal_expense, get_expenses_for_export, pair_expenses
from services.relation_service import auto_link_records


# ---------------------------------------------------------------------------
# ARRAY(String) 欄位在 SQLite 無法直接綁定 Python list，
# 於測試 process 內把 image_url / item_image_url 的欄位型別換成 JSON TEXT。
# 只影響本檔案的 in-memory 測試連線，不影響正式環境的 PostgreSQL ARRAY 型別。
# ---------------------------------------------------------------------------

class _JsonArray(TypeDecorator):
    impl = TEXT
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return json.dumps(value if value is not None else [])

    def process_result_value(self, value, dialect):
        return json.loads(value) if value else []


Expense.__table__.c.image_url.type = _JsonArray()
Expense.__table__.c.item_image_url.type = _JsonArray()


# ── SQLite in-memory 引擎 ──────────────────────────────────────────────────

SQLITE_URL = "sqlite:///file:report_scenarios_test?mode=memory&cache=shared&uri=true"


def _build_engine():
    engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS expenses (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                serial_number TEXT UNIQUE NOT NULL,
                image_url TEXT NOT NULL DEFAULT '[]',
                item_image_url TEXT NOT NULL DEFAULT '[]',
                uploader_name TEXT,
                uploader_dept TEXT,
                submitter_dept TEXT,
                upload_date TIMESTAMP,
                submitter_name TEXT,
                item_description TEXT,
                expense_date DATE,
                invoice_number TEXT,
                total_amount NUMERIC(12,2),
                net_amount NUMERIC(12,2),
                tax_amount NUMERIC(12,2),
                seller_tax_id TEXT,
                seller_name TEXT,
                amount NUMERIC(12,2),
                status TEXT NOT NULL DEFAULT 'PENDING',
                reject_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_description TEXT,
                image_count INTEGER NOT NULL DEFAULT 1,
                voucher_categories TEXT,
                voucher_subtypes TEXT,
                expense_categories TEXT,
                trigger_by TEXT,
                group_id TEXT,
                parent_id TEXT,
                possible_duplicate_of TEXT,
                relation_type TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                void_reason TEXT,
                referenced_invoice_number TEXT,
                return_record TEXT,
                display_order INTEGER,
                dismissed_from_waiting_return INTEGER NOT NULL DEFAULT 0,
                voided_at TIMESTAMP
            )
        """))
        conn.commit()
    return engine


_engine = _build_engine()


@pytest.fixture()
def db() -> Session:
    """每個測試取得獨立 session，結束後回滾確保隔離。"""
    connection = _engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, autocommit=False, autoflush=False)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


# ── 測試輔助函式 ──────────────────────────────────────────────────────────

def _make_expense(db: Session, serial: str, **kwargs) -> Expense:
    """建立一筆 Expense 並 commit，回傳 ORM 物件（供後續讀取自動產生欄位）。"""
    defaults = dict(
        id=uuid.uuid4(),
        serial_number=serial,
        image_url=[],
        item_image_url=[],
        status=ExpenseStatus.PENDING,
        is_active=True,
    )
    defaults.update(kwargs)
    expense = Expense(**defaults)
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


def _ocr_credit_note(original_invoice_number: str, total_amount: float = 2000.0) -> VoucherOCRResult:
    """建立一筆 Gemini 判定為折讓單的 OCR 結果（成功、is_voucher、帶原發票號）。"""
    return VoucherOCRResult(
        is_voucher=True,
        success=True,
        voucher_category="CREDIT_NOTE",
        original_invoice_number=original_invoice_number,
        total_amount=total_amount,
    )


def _reversals(db: Session, relation_type: str) -> list[Expense]:
    return list(db.query(Expense).filter(Expense.relation_type == relation_type).all())


# ---------------------------------------------------------------------------
# 1. csv_remark 決策矩陣
# ---------------------------------------------------------------------------

class TestCsvRemark:
    """TC-REMARK-*：core/relation_rules.py::csv_remark 純函式矩陣測試。"""

    @pytest.mark.parametrize("relation_type", ["VOID_REVERSAL", "RETURN_REVERSAL"])
    def test_reversal_types_always_show_fixed_label(self, relation_type: str) -> None:
        """TC-REMARK-01：沖銷分錄類型固定顯示「沖銷分錄」，不受其他欄位影響。"""
        result = csv_remark(relation_type, ExpenseStatus.APPROVED, "某退件原因", "某作廢原因")
        assert result == "沖銷分錄"

    def test_replaced_void_prefers_void_reason(self) -> None:
        """TC-REMARK-02：REPLACED_VOID 狀態優先顯示 void_reason。"""
        result = csv_remark(None, ExpenseStatus.REPLACED_VOID, "退件原因", "換貨換單")
        assert result == "換貨換單"

    def test_replaced_void_falls_back_to_reject_reason(self) -> None:
        """TC-REMARK-03：REPLACED_VOID 但 void_reason 為空時，退回 reject_reason。"""
        result = csv_remark(None, ExpenseStatus.REPLACED_VOID, "統編填錯", None)
        assert result == "統編填錯"

    def test_replaced_void_default_label_when_both_empty(self) -> None:
        """TC-REMARK-04：REPLACED_VOID 兩者皆空時，顯示預設「換單作廢」。"""
        result = csv_remark(None, ExpenseStatus.REPLACED_VOID, None, None)
        assert result == "換單作廢"

    def test_normal_status_shows_reject_reason_only(self) -> None:
        """TC-REMARK-05：非沖銷、非 REPLACED_VOID 時，只顯示 reject_reason。"""
        result = csv_remark(None, ExpenseStatus.PENDING, "測試退件", "不應顯示")
        assert result == "測試退件"

    def test_normal_status_blank_when_no_reject_reason(self) -> None:
        """TC-REMARK-06：一般狀態且無退件原因時，備注應為空字串。"""
        result = csv_remark(None, ExpenseStatus.APPROVED, None, None)
        assert result == ""

    def test_credit_note_relation_type_not_treated_as_reversal(self) -> None:
        """TC-REMARK-07：CREDIT_NOTE 不在 REVERSAL_TYPES 內，備注不應顯示「沖銷分錄」。"""
        result = csv_remark("CREDIT_NOTE", ExpenseStatus.PENDING, None, None)
        assert result == ""


# ---------------------------------------------------------------------------
# 2. 換新發票（VOID_REPLACE）
# ---------------------------------------------------------------------------

class TestVoidReplace:
    """TC-VOID-*：換新發票情境 —— 舊發票負數、新發票正數。"""

    def test_auto_link_marks_original_and_creates_reversal(self, db: Session) -> None:
        """TC-VOID-01：說明文字含 [發票號] 時，auto_link_records 應自動：
        1) 標記原始發票 relation_type=VOID_ORIGINAL 並記錄 void_reason/voided_at
        2) 新發票 relation_type=VOID_REPLACE 且 parent_id 指向原始發票
        3) 自動建立一筆 VOID_REVERSAL 沖銷分錄，金額為原發票的負值

        為何測試：這是換新發票情境的核心自動化路徑，若此處故障，
        舊發票將不會被沖銷，報表金額會重複認列。
        """
        original = _make_expense(
            db, "EXP-202607-0001", invoice_number="AB-11112222",
            total_amount=Decimal("10000"), net_amount=Decimal("9524"), tax_amount=Decimal("476"),
            status=ExpenseStatus.APPROVED,
        )
        new_expense = _make_expense(
            db, "EXP-202607-0002",
            total_amount=Decimal("8000"), status=ExpenseStatus.PENDING,
        )

        result = auto_link_records(
            db, new_expense, ocr_results=[], user_description="換貨換單 [AB-11112222]",
        )

        db.refresh(original)
        assert original.relation_type == "VOID_ORIGINAL", "原始發票應被標記為 VOID_ORIGINAL"
        assert original.void_reason == "換貨換單"
        assert original.voided_at is not None
        # status 不會被 auto_link_records 自動改成 REPLACED_VOID（需人工在 Dashboard 操作）
        assert original.status == ExpenseStatus.APPROVED, \
            "auto_link_records 不應自動改變原始發票的 status"

        assert result.relation_type == "VOID_REPLACE"
        assert result.parent_id == original.id
        assert result.referenced_invoice_number == "AB-11112222"
        assert result.total_amount == Decimal("8000"), "新發票金額應維持正數"

        reversals = _reversals(db, "VOID_REVERSAL")
        assert len(reversals) == 1, "應自動建立恰好一筆 VOID_REVERSAL 沖銷分錄"
        reversal = reversals[0]
        assert reversal.total_amount == Decimal("-10000"), "沖銷分錄金額應為原發票的負值"
        assert reversal.net_amount == Decimal("-9524")
        assert reversal.tax_amount == Decimal("-476")
        assert reversal.parent_id == original.id
        assert reversal.status == ExpenseStatus.PENDING

    def test_reversal_upload_date_is_creation_time_not_original_time(self, db: Session) -> None:
        """TC-VOID-02：沖銷分錄的 upload_date 應為「新發票上傳當下」，
        而非沿用原始發票的上傳時間 —— 這是報表期間歸屬正確與否的關鍵。

        為何測試：對應業務規則「狀況一」：舊發票在第1週的報表只出現1筆，
        沖銷分錄要等第2週換新發票時才出現在第2週報表，
        若沖銷分錄誤用原始發票的 upload_date，會導致它出現在錯誤的期別。
        """
        period1 = datetime(2026, 6, 1, tzinfo=timezone.utc)
        original = _make_expense(
            db, "EXP-202606-0001", invoice_number="AB-22223333",
            total_amount=Decimal("10000"), upload_date=period1, status=ExpenseStatus.PENDING,
        )
        new_expense = _make_expense(
            db, "EXP-202607-0003",
            total_amount=Decimal("8000"), status=ExpenseStatus.PENDING,
        )

        before_call = datetime.now(timezone.utc)
        auto_link_records(db, new_expense, ocr_results=[], user_description="[AB-22223333]")
        after_call = datetime.now(timezone.utc)

        reversal = _reversals(db, "VOID_REVERSAL")[0]
        assert reversal.upload_date is not None
        reversal_upload_date = reversal.upload_date
        if reversal_upload_date.tzinfo is None:
            reversal_upload_date = reversal_upload_date.replace(tzinfo=timezone.utc)
        assert before_call <= reversal_upload_date <= after_call, \
            "沖銷分錄 upload_date 應等於建立當下時間，而非原始發票的 upload_date"
        assert reversal.upload_date != original.upload_date

    def test_liff_scenario_a_void_replace_gets_reversal_on_pairing(self, db: Session) -> None:
        """TC-VOID-03（迴歸測試）：LIFF 待退貨情境A —— 使用者手填「原發票號碼」建立的
        VOID_REPLACE 補件，在 Dashboard 手動配對成功後，應自動建立 VOID_REVERSAL 沖銷分錄，
        並將原始發票標記為 VOID_ORIGINAL。

        背景：先前 pair_expenses 只認 REVERSAL_REQUIRED_TYPES（RETURN_SUPPLEMENT /
        AMOUNT_CORRECTION），VOID_REPLACE 不在其中，導致手動配對後金額未沖銷、原始
        發票與新發票金額重複計算。此測試改為釘住「已修正」的行為。
        """
        original = _make_expense(
            db, "EXP-202607-0004", invoice_number="AB-33334444",
            total_amount=Decimal("10000"), status=ExpenseStatus.WAITING_RETURN,
        )
        supplement = _make_expense(
            db, "EXP-202607-0005", relation_type="VOID_REPLACE",
            referenced_invoice_number="AB-33334444", total_amount=Decimal("8000"),
        )

        pair_expenses(db, supplement.id, original.id)

        reversals = _reversals(db, "VOID_REVERSAL")
        assert len(reversals) == 1, "VOID_REPLACE 透過 pair_expenses 配對後應自動建立一筆 VOID_REVERSAL 沖銷分錄"
        reversal = reversals[0]
        assert reversal.parent_id == original.id
        assert reversal.total_amount == Decimal("-10000"), "沖銷金額應為原始發票金額的負值"

        db.refresh(original)
        assert original.relation_type == "VOID_ORIGINAL", "配對後原始發票應標記為 VOID_ORIGINAL"
        assert original.voided_at is not None

    def test_pair_expenses_void_replace_reversal_not_duplicated(self, db: Session) -> None:
        """TC-VOID-04：重複呼叫 pair_expenses（例如使用者誤按兩次配對按鈕）不應重複建立
        VOID_REVERSAL 沖銷分錄。"""
        original = _make_expense(
            db, "EXP-202607-0008", invoice_number="AB-55556666",
            total_amount=Decimal("5000"), status=ExpenseStatus.PENDING,
        )
        supplement = _make_expense(
            db, "EXP-202607-0009", relation_type="VOID_REPLACE",
            referenced_invoice_number="AB-55556666", total_amount=Decimal("4500"),
        )

        pair_expenses(db, supplement.id, original.id)
        pair_expenses(db, supplement.id, original.id)

        assert len(_reversals(db, "VOID_REVERSAL")) == 1, "重複配對不應重複建立沖銷分錄"


# ---------------------------------------------------------------------------
# 3. 折讓單（CREDIT_NOTE）
# ---------------------------------------------------------------------------

class TestCreditNote:
    """TC-CREDIT-*：折讓單情境 —— 原發票不動，折讓單本身即為負數。"""

    def test_credit_note_forces_negative_and_original_untouched(self, db: Session) -> None:
        """TC-CREDIT-01：折讓單 OCR 判定成功且比對到原發票時：
        1) 折讓單金額被強制轉負（即使 OCR 給正數）
        2) 原發票完全不受影響（不新增 relation_type、不設 voided_at）
        3) 不會多產生任何第三筆沖銷分錄

        為何測試：折讓單是三種需要「負數抵銷」情境中，唯一不需要額外沖銷分錄的，
        若誤觸發沖銷分錄邏輯會導致金額被扣兩次。
        """
        original = _make_expense(
            db, "EXP-202607-0006", invoice_number="AB-44445555",
            total_amount=Decimal("10000"), status=ExpenseStatus.APPROVED,
        )
        credit_note = _make_expense(
            db, "EXP-202607-0007",
            total_amount=Decimal("2000"),  # OCR 給正數，程式應強制轉負
            net_amount=Decimal("1905"), tax_amount=Decimal("95"),
        )

        ocr_results = [_ocr_credit_note("AB-44445555", total_amount=2000.0)]
        result = auto_link_records(db, credit_note, ocr_results=ocr_results, user_description=None)

        assert result.relation_type == "CREDIT_NOTE"
        assert result.total_amount == Decimal("-2000"), "折讓單金額應被強制轉負"
        assert result.net_amount == Decimal("-1905")
        assert result.tax_amount == Decimal("-95")
        assert result.parent_id == original.id

        db.refresh(original)
        assert original.relation_type is None, "原發票不應被標記任何 relation_type"
        assert original.voided_at is None, "原發票不應被設定 voided_at"
        assert original.is_active is True
        assert original.status == ExpenseStatus.APPROVED, "原發票狀態不應被改變"

        # 不應有任何 XXX_REVERSAL 被建立
        assert len(_reversals(db, "VOID_REVERSAL")) == 0
        assert len(_reversals(db, "RETURN_REVERSAL")) == 0

    def test_credit_note_without_match_stays_unlinked(self, db: Session) -> None:
        """TC-CREDIT-02：找不到原發票（也找不到同賣家 7 天內記錄）時，
        折讓單應維持一般憑證狀態，relation_type 不被設定，金額也不被強制轉負。

        為何測試：避免把找不到比對對象的折讓單誤標記，導致 Dashboard
        待退貨清單出現找不到原始憑證的孤兒資料。
        """
        credit_note = _make_expense(
            db, "EXP-202607-0008",
            total_amount=Decimal("2000"), seller_name=None,
        )

        ocr_results = [_ocr_credit_note("ZZ-99999999", total_amount=2000.0)]
        result = auto_link_records(db, credit_note, ocr_results=ocr_results, user_description=None)

        assert result.relation_type is None, "查無比對對象時不應標記為 CREDIT_NOTE"
        assert result.total_amount == Decimal("2000"), "查無比對對象時金額不應被強制轉負"
        assert result.parent_id is None


# ---------------------------------------------------------------------------
# 4. 換貨收據（RETURN_SUPPLEMENT）／舊收據改金額（AMOUNT_CORRECTION）
# ---------------------------------------------------------------------------

class TestReturnSupplementAndAmountCorrection:
    """TC-RETURN-*：透過 pair_expenses 建立沖銷分錄的兩種情境。"""

    @pytest.mark.parametrize("relation_type", ["RETURN_SUPPLEMENT", "AMOUNT_CORRECTION"])
    def test_pair_creates_return_reversal(self, db: Session, relation_type: str) -> None:
        """TC-RETURN-01：待退貨原收據與補件配對後，應自動建立 RETURN_REVERSAL
        沖銷分錄，金額為原收據的負值；RETURN_SUPPLEMENT 與 AMOUNT_CORRECTION
        共用同一套沖銷邏輯，行為應完全一致。

        為何測試：這兩種情境代表「換貨收據」與「舊收據改金額」，
        都需要負數抵銷舊收據金額，是報表正確性的核心。
        """
        original = _make_expense(
            db, f"EXP-202607-00{10 if relation_type == 'RETURN_SUPPLEMENT' else 11}",
            invoice_number=f"AB-5555{relation_type[:4]}", total_amount=Decimal("10000"),
            status=ExpenseStatus.WAITING_RETURN,
        )
        supplement = _make_expense(
            db, f"EXP-202607-00{12 if relation_type == 'RETURN_SUPPLEMENT' else 13}",
            relation_type=relation_type, total_amount=Decimal("8000"),
        )

        result = pair_expenses(db, supplement.id, original.id)

        assert result.parent_id == original.id
        assert result.return_record == original.invoice_number

        db.refresh(original)
        assert original.voided_at is not None, "原收據應被標記沖銷確認時間"

        reversals = _reversals(db, "RETURN_REVERSAL")
        assert len(reversals) == 1
        reversal = reversals[0]
        assert reversal.total_amount == Decimal("-10000")
        assert reversal.parent_id == original.id
        assert reversal.status == ExpenseStatus.PENDING

    def test_pair_credit_note_supplement_does_not_create_reversal(self, db: Session) -> None:
        """TC-RETURN-02：CREDIT_NOTE 類型的補件透過 pair_expenses 配對，
        不應觸發沖銷分錄建立（本身已是負數，REVERSAL_REQUIRED_TYPES 不含 CREDIT_NOTE）。

        為何測試：確保 pair_expenses 的沖銷建立邏輯只鎖定
        RETURN_SUPPLEMENT / AMOUNT_CORRECTION，不誤觸發於折讓單。
        """
        original = _make_expense(
            db, "EXP-202607-0014", invoice_number="AB-66667777",
            total_amount=Decimal("10000"), status=ExpenseStatus.WAITING_RETURN,
        )
        supplement = _make_expense(
            db, "EXP-202607-0015", relation_type="CREDIT_NOTE", total_amount=Decimal("-2000"),
        )

        pair_expenses(db, supplement.id, original.id)

        assert len(_reversals(db, "RETURN_REVERSAL")) == 0

    def test_pair_is_idempotent_no_duplicate_reversal(self, db: Session) -> None:
        """TC-RETURN-03：重複呼叫 pair_expenses（模擬使用者重複點擊配對按鈕）
        不應重複建立第二筆 RETURN_REVERSAL。

        為何測試：pair_expenses docstring 註明 idempotent，需要測試保護此承諾。
        """
        original = _make_expense(
            db, "EXP-202607-0016", invoice_number="AB-77778888",
            total_amount=Decimal("10000"), status=ExpenseStatus.WAITING_RETURN,
        )
        supplement = _make_expense(
            db, "EXP-202607-0017", relation_type="RETURN_SUPPLEMENT", total_amount=Decimal("8000"),
        )

        pair_expenses(db, supplement.id, original.id)
        pair_expenses(db, supplement.id, original.id)

        assert len(_reversals(db, "RETURN_REVERSAL")) == 1, "重複配對不應重複建立沖銷分錄"

    def test_orphan_supplement_without_match_has_no_reversal_yet(self, db: Session) -> None:
        """TC-RETURN-04：補件尚未配對（孤兒狀態）時，新收據的正數金額
        單獨存在，沒有任何抵銷負數 —— 這是「配對延遲」風險空窗期的直接體現。

        為何測試：驗證系統目前的行為 —— 沖銷分錄只在人工配對那一刻才產生，
        配對之前，正數會在自己上傳的期間單獨出現在報表上。
        """
        original = _make_expense(
            db, "EXP-202607-0018", invoice_number="AB-88889999",
            total_amount=Decimal("10000"), status=ExpenseStatus.WAITING_RETURN,
        )
        supplement = _make_expense(
            db, "EXP-202607-0019", relation_type="RETURN_SUPPLEMENT", total_amount=Decimal("8000"),
        )

        assert supplement.parent_id is None
        assert len(_reversals(db, "RETURN_REVERSAL")) == 0
        assert original.voided_at is None


# ---------------------------------------------------------------------------
# 5. 定期報表期間呈現（get_expenses_for_export）
# ---------------------------------------------------------------------------

class TestReportPeriodVisibility:
    """TC-PERIOD-*：驗證「舊單只在自己上傳期出現、沖銷分錄落在綁定當下那一期」。"""

    def test_scenario_one_reversal_appears_only_in_binding_period(self, db: Session) -> None:
        """TC-PERIOD-01（狀況一）：舊發票於第1週上傳，第1週報表應只有1筆+10000；
        第2週才換新發票並自動綁定，第2週報表應有2筆：-10000（沖銷）與+8000（新發票），
        舊發票不應在第2週報表重複出現。
        """
        period1 = date(2026, 6, 1)
        period2 = date(2026, 6, 8)

        original = _make_expense(
            db, "EXP-202606-0100", invoice_number="AB-10001000",
            total_amount=Decimal("10000"),
            upload_date=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
        )

        # 第1週報表：只應看到舊發票 1 筆
        week1_items = get_expenses_for_export(
            db, date_from=period1, date_to=date(2026, 6, 7), include_inactive=True, limit=1000,
        )
        assert [e.id for e in week1_items] == [original.id]
        assert week1_items[0].total_amount == Decimal("10000")

        # 第2週：上傳新發票並自動綁定（沖銷分錄建立時間 = 現在，落在第2週）
        new_expense = _make_expense(
            db, "EXP-202606-0101", total_amount=Decimal("8000"),
            upload_date=datetime(2026, 6, 8, 10, 0, tzinfo=timezone.utc),
        )
        auto_link_records(db, new_expense, ocr_results=[], user_description="[AB-10001000]")
        reversal = _reversals(db, "VOID_REVERSAL")[0]
        # 沖銷分錄的 upload_date 是「現在」（測試執行當下），手動改成落在第2週以模擬情境
        reversal.upload_date = datetime(2026, 6, 8, 11, 0, tzinfo=timezone.utc)
        db.commit()

        week2_items = get_expenses_for_export(
            db, date_from=period2, date_to=date(2026, 6, 14), include_inactive=True, limit=1000,
        )
        week2_ids = {e.id for e in week2_items}
        assert week2_ids == {new_expense.id, reversal.id}, \
            "第2週報表應只有新發票與沖銷分錄，舊發票不應重複出現"
        totals = sorted(e.total_amount for e in week2_items)
        assert totals == [Decimal("-10000"), Decimal("8000")]

    def test_scenario_two_same_period_shows_three_rows(self, db: Session) -> None:
        """TC-PERIOD-02（狀況二）：舊發票（週一）與新發票（週三）都在同一週上傳並綁定，
        該週報表應有 3 筆：+10000（舊發票）、-10000（沖銷）、+8000（新發票）。
        """
        monday = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
        wednesday = datetime(2026, 6, 3, 9, 0, tzinfo=timezone.utc)

        original = _make_expense(
            db, "EXP-202606-0102", invoice_number="AB-20002000",
            total_amount=Decimal("10000"), upload_date=monday,
        )
        new_expense = _make_expense(
            db, "EXP-202606-0103", total_amount=Decimal("8000"), upload_date=wednesday,
        )
        auto_link_records(db, new_expense, ocr_results=[], user_description="[AB-20002000]")
        reversal = _reversals(db, "VOID_REVERSAL")[0]
        reversal.upload_date = wednesday
        db.commit()

        items = get_expenses_for_export(
            db, date_from=date(2026, 6, 1), date_to=date(2026, 6, 7), include_inactive=True, limit=1000,
        )
        assert len(items) == 3
        totals = sorted(e.total_amount for e in items)
        assert totals == [Decimal("-10000"), Decimal("8000"), Decimal("10000")]

    def test_force_include_types_still_respect_date_filter(self, db: Session) -> None:
        """TC-PERIOD-03：CSV_FORCE_INCLUDE_TYPES（如 VOID_REVERSAL）只影響「status 篩選」，
        不會讓記錄跳脫日期區間篩選 —— 沖銷分錄若落在區間外，仍不應出現。
        """
        original = _make_expense(
            db, "EXP-202606-0104", invoice_number="AB-30003000",
            total_amount=Decimal("10000"),
            upload_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        reversal = create_reversal_expense(db, original, "VOID_REVERSAL")
        reversal.upload_date = datetime(2026, 6, 1, tzinfo=timezone.utc)  # 落在區間外的日期
        db.commit()

        # 篩選一個完全不含 6/1 的區間，即使帶 status 條件，沖銷分錄也不應出現
        items = get_expenses_for_export(
            db, status=ExpenseStatus.APPROVED,
            date_from=date(2026, 7, 1), date_to=date(2026, 7, 31),
            include_inactive=True, limit=1000,
        )
        assert reversal.id not in {e.id for e in items}, \
            "強制納入類型不應繞過日期篩選"

    def test_rejected_excluded_even_with_include_inactive(self, db: Session) -> None:
        """TC-PERIOD-04：REJECTED 記錄永遠不應出現在匯出結果，即使帶 include_inactive=True。"""
        rejected = _make_expense(
            db, "EXP-202607-0020", status=ExpenseStatus.REJECTED,
            total_amount=Decimal("5000"),
            upload_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        items = get_expenses_for_export(
            db, date_from=date(2026, 7, 1), date_to=date(2026, 7, 31), include_inactive=True, limit=1000,
        )
        assert rejected.id not in {e.id for e in items}
