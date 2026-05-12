"""
Unit tests for services.ocr_service.classify_and_extract()

所有測試皆 mock Gemini API，不依賴真實網路或 API Key。
Structured Output 模式：mock response.parsed 直接回傳 VoucherOCRResult 物件。
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from schemas.ocr import KEY_AUDIT_FIELDS, KEY_FIELD_THRESHOLD, VoucherOCRResult
from services.ocr_service import classify_and_extract


# ---------------------------------------------------------------------------
# Helper：建立假圖片 + mock Gemini response.parsed
# ---------------------------------------------------------------------------

def _make_mock_response(result: VoucherOCRResult) -> MagicMock:
    """建立模擬 Gemini generate_content 回應物件（Structured Output 模式）。"""
    mock_response = MagicMock()
    mock_response.parsed = result
    mock_response.text = result.model_dump_json()
    return mock_response


async def _call_classify(tmp_path: Path, result: VoucherOCRResult) -> VoucherOCRResult:
    """共用輔助函式：建立假圖片 + mock Gemini + 呼叫 classify_and_extract。"""
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake-image-bytes")

    mock_response = _make_mock_response(result)

    with patch("services.ocr_service._client") as mock_client:
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        with patch("services.ocr_service.Image") as mock_pil:
            mock_pil.open.return_value = MagicMock()
            return await classify_and_extract(str(img_path))


# ---------------------------------------------------------------------------
# 測試案例 1：INVOICE（統一發票）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_invoice(tmp_path: Path) -> None:
    """INVOICE → is_voucher=True，核心欄位正確，voucher_subtype=None。"""
    ocr = VoucherOCRResult(
        is_voucher=True,
        voucher_category="INVOICE",
        voucher_subtype=None,
        expense_category="GENERAL",
        scene_reasoning="統一發票字軌 AB-12345678，有賣方統編",
        invoice_number="AB-12345678",
        invoice_number_confidence=0.98,
        seller_name="測試商行有限公司",
        seller_name_confidence=0.95,
        seller_tax_id="12345678",
        seller_tax_id_confidence=0.97,
        total_amount=2400,
        total_amount_confidence=0.99,
        tax_amount=114,
        tax_amount_confidence=0.99,
        expense_date="2026-04-01",
        expense_date_confidence=0.99,
        overall_confidence=0.97,
        low_confidence_fields=[],
    )
    result = await _call_classify(tmp_path, ocr)

    assert result.success is True
    assert result.is_voucher is True
    assert result.voucher_category == "INVOICE"
    assert result.voucher_subtype is None
    assert result.invoice_number == "AB-12345678"
    assert result.seller_name == "測試商行有限公司"
    assert result.seller_tax_id == "12345678"
    assert result.total_amount == 2400
    assert result.error is None


# ---------------------------------------------------------------------------
# 測試案例 2：RECEIPT / GENERAL（一般收據）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_receipt_general(tmp_path: Path) -> None:
    """RECEIPT/GENERAL → is_voucher=True，expense_category=STATIONERY（文具）。"""
    ocr = VoucherOCRResult(
        is_voucher=True,
        voucher_category="RECEIPT",
        voucher_subtype="GENERAL",
        expense_category="STATIONERY",
        scene_reasoning="品項含 A4 紙、原子筆 → 文具用品",
        seller_name="7-ELEVEN",
        seller_name_confidence=0.95,
        total_amount=350,
        total_amount_confidence=0.98,
        expense_date="2026-04-02",
        expense_date_confidence=0.99,
        item_description="辦公室文具用品",
        has_exempt_stamp=False,
        overall_confidence=0.96,
        low_confidence_fields=[],
    )
    result = await _call_classify(tmp_path, ocr)

    assert result.success is True
    assert result.is_voucher is True
    assert result.voucher_category == "RECEIPT"
    assert result.voucher_subtype == "GENERAL"
    assert result.expense_category == "STATIONERY"
    assert result.seller_name == "7-ELEVEN"
    assert result.total_amount == 350
    assert result.item_description == "辦公室文具用品"


# ---------------------------------------------------------------------------
# 測試案例 3：RECEIPT / EXEMPT_INVOICE（免用統一發票）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_receipt_exempt_invoice(tmp_path: Path) -> None:
    """RECEIPT/EXEMPT_INVOICE → has_exempt_stamp=True，voucher_subtype='EXEMPT_INVOICE'。"""
    ocr = VoucherOCRResult(
        is_voucher=True,
        voucher_category="RECEIPT",
        voucher_subtype="EXEMPT_INVOICE",
        expense_category="MEAL",
        scene_reasoning="收據上有『免用統一發票』圓形橡皮章，品項為午餐便當",
        seller_name="員工餐廳",
        seller_name_confidence=0.90,
        total_amount=120,
        total_amount_confidence=0.95,
        expense_date="2026-04-03",
        expense_date_confidence=0.98,
        has_exempt_stamp=True,
        item_description="午餐便當",
        overall_confidence=0.91,
        low_confidence_fields=[],
    )
    result = await _call_classify(tmp_path, ocr)

    assert result.success is True
    assert result.voucher_category == "RECEIPT"
    assert result.voucher_subtype == "EXEMPT_INVOICE"
    assert result.has_exempt_stamp is True
    assert result.expense_category == "MEAL"


# ---------------------------------------------------------------------------
# 測試案例 4：RECEIPT + expense_category=MEAL（餐廳發票/收據）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_meal_expense(tmp_path: Path) -> None:
    """INVOICE 但 expense_category=MEAL → scene_reasoning 說明餐廳場景。"""
    ocr = VoucherOCRResult(
        is_voucher=True,
        voucher_category="INVOICE",
        voucher_subtype=None,
        expense_category="MEAL",
        scene_reasoning="品項含『套餐、飲料、主食』→ 餐廳消費 → MEAL",
        invoice_number="EF-11223344",
        invoice_number_confidence=0.95,
        seller_name="美食坊餐廳",
        seller_name_confidence=0.92,
        total_amount=580,
        total_amount_confidence=0.99,
        expense_date="2026-04-04",
        expense_date_confidence=0.99,
        overall_confidence=0.95,
        low_confidence_fields=[],
    )
    result = await _call_classify(tmp_path, ocr)

    assert result.success is True
    assert result.expense_category == "MEAL"
    assert "餐廳" in result.scene_reasoning or "套餐" in result.scene_reasoning


# ---------------------------------------------------------------------------
# 測試案例 5：LABOR_SERVICE（勞務報酬單）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_labor_service(tmp_path: Path) -> None:
    """LABOR_SERVICE → payee_name / id_number / net_amount 正確。"""
    ocr = VoucherOCRResult(
        is_voucher=True,
        voucher_category="LABOR_SERVICE",
        voucher_subtype=None,
        expense_category="LABOR",
        scene_reasoning="手寫金額 + 身分證字號 + 收款人簽章 → 勞務報酬單",
        payee_name="陳小華",
        id_number="A123456789",
        id_number_confidence=0.93,
        net_amount=15000,
        net_amount_confidence=0.97,
        tax_amount=450,
        tax_amount_confidence=0.97,
        total_amount=14550,
        total_amount_confidence=0.97,
        expense_date="2026-04-05",
        expense_date_confidence=0.99,
        labor_content="演講費",
        overall_confidence=0.95,
        low_confidence_fields=[],
    )
    result = await _call_classify(tmp_path, ocr)

    assert result.success is True
    assert result.is_voucher is True
    assert result.voucher_category == "LABOR_SERVICE"
    assert result.payee_name == "陳小華"
    assert result.id_number == "A123456789"
    assert result.net_amount == 15000


# ---------------------------------------------------------------------------
# 測試案例 6：TRANSPORTATION / HSR_TICKET（高鐵票根）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_transportation_hsr_ticket(tmp_path: Path) -> None:
    """TRANSPORTATION/HSR_TICKET → route_from/route_to/ticket_type 正確。"""
    ocr = VoucherOCRResult(
        is_voucher=True,
        voucher_category="TRANSPORTATION",
        voucher_subtype="HSR_TICKET",
        expense_category="TRANSPORTATION",
        scene_reasoning="高鐵票根格式，印有字軌號、座號、台北→左營",
        route_from="台北",
        route_to="高雄左營",
        transport_type="高鐵",
        ticket_type="實體票",
        total_amount=1490,
        total_amount_confidence=0.99,
        expense_date="2026-04-06",
        expense_date_confidence=0.99,
        overall_confidence=0.97,
        low_confidence_fields=[],
    )
    result = await _call_classify(tmp_path, ocr)

    assert result.success is True
    assert result.voucher_category == "TRANSPORTATION"
    assert result.voucher_subtype == "HSR_TICKET"
    assert result.route_from == "台北"
    assert result.route_to == "高雄左營"
    assert result.ticket_type == "實體票"
    assert result.expense_category == "TRANSPORTATION"


# ---------------------------------------------------------------------------
# 測試案例 7：TRANSPORTATION / TAXI（計程車）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_transportation_taxi(tmp_path: Path) -> None:
    """TRANSPORTATION/TAXI → receipt_type 欄位正確。"""
    ocr = VoucherOCRResult(
        is_voucher=True,
        voucher_category="TRANSPORTATION",
        voucher_subtype="TAXI",
        expense_category="TRANSPORTATION",
        scene_reasoning="收據印有車牌號碼與計程車字樣，為跳表收據",
        route_from="台北車站",
        route_to="松山機場",
        transport_type="計程車",
        receipt_type="跳表收據",
        total_amount=280,
        total_amount_confidence=0.98,
        expense_date="2026-04-07",
        expense_date_confidence=0.99,
        overall_confidence=0.96,
        low_confidence_fields=[],
    )
    result = await _call_classify(tmp_path, ocr)

    assert result.success is True
    assert result.voucher_subtype == "TAXI"
    assert result.receipt_type == "跳表收據"


# ---------------------------------------------------------------------------
# 測試案例 8：TRANSPORTATION / PARKING（停車費）— route_from/to 應為 null
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_transportation_parking(tmp_path: Path) -> None:
    """TRANSPORTATION/PARKING → route_from/route_to=None，parking_location 有值。"""
    ocr = VoucherOCRResult(
        is_voucher=True,
        voucher_category="TRANSPORTATION",
        voucher_subtype="PARKING",
        expense_category="TRANSPORTATION",
        scene_reasoning="停車場計時收據，印有停車場名稱與收費時段",
        route_from=None,
        route_to=None,
        transport_type="停車",
        parking_location="信義威秀停車場",
        total_amount=150,
        total_amount_confidence=0.98,
        expense_date="2026-04-08",
        expense_date_confidence=0.99,
        overall_confidence=0.95,
        low_confidence_fields=[],
    )
    result = await _call_classify(tmp_path, ocr)

    assert result.success is True
    assert result.voucher_subtype == "PARKING"
    assert result.route_from is None
    assert result.route_to is None
    assert result.parking_location == "信義威秀停車場"


# ---------------------------------------------------------------------------
# 測試案例 9：TRANSPORTATION / FUEL（油資）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_transportation_fuel(tmp_path: Path) -> None:
    """TRANSPORTATION/FUEL → fuel_type 欄位正確，scene_reasoning 含加油站。"""
    ocr = VoucherOCRResult(
        is_voucher=True,
        voucher_category="TRANSPORTATION",
        voucher_subtype="FUEL",
        expense_category="TRANSPORTATION",
        scene_reasoning="店名含『中油』，印有油品『95無鉛』與公升數 → 加油站 → FUEL",
        transport_type="油資",
        fuel_type="95無鉛",
        seller_name="台灣中油股份有限公司",
        seller_name_confidence=0.97,
        total_amount=1200,
        total_amount_confidence=0.98,
        expense_date="2026-04-09",
        expense_date_confidence=0.99,
        overall_confidence=0.96,
        low_confidence_fields=[],
    )
    result = await _call_classify(tmp_path, ocr)

    assert result.success is True
    assert result.voucher_subtype == "FUEL"
    assert result.fuel_type == "95無鉛"
    assert "中油" in result.scene_reasoning or "加油站" in result.scene_reasoning


# ---------------------------------------------------------------------------
# 測試案例 10：INSURANCE / ACCIDENT（意外險）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_insurance_accident(tmp_path: Path) -> None:
    """INSURANCE/ACCIDENT → insurer_name / insured_name / insurance_type 正確。"""
    ocr = VoucherOCRResult(
        is_voucher=True,
        voucher_category="INSURANCE",
        voucher_subtype="ACCIDENT",
        expense_category="INSURANCE",
        scene_reasoning="保費通知書，印有『意外險』與保單號碼",
        insurer_name="富邦人壽",
        insured_name="王大明",
        insurance_type="意外險",
        policy_number="POL-2026-001234",
        total_amount=3600,
        total_amount_confidence=0.97,
        expense_date="2026-04-10",
        expense_date_confidence=0.99,
        overall_confidence=0.95,
        low_confidence_fields=[],
    )
    result = await _call_classify(tmp_path, ocr)

    assert result.success is True
    assert result.voucher_category == "INSURANCE"
    assert result.voucher_subtype == "ACCIDENT"
    assert result.insurer_name == "富邦人壽"
    assert result.insured_name == "王大明"
    assert result.insurance_type == "意外險"


# ---------------------------------------------------------------------------
# 測試案例 11：UTILITY / ELECTRICITY（電費帳單）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_utility_electricity(tmp_path: Path) -> None:
    """UTILITY/ELECTRICITY → billing_period / account_number 正確。"""
    ocr = VoucherOCRResult(
        is_voucher=True,
        voucher_category="UTILITY",
        voucher_subtype="ELECTRICITY",
        expense_category="UTILITY",
        scene_reasoning="台電帳單格式，印有用電度數與帳單期間",
        seller_name="台灣電力公司",
        seller_name_confidence=0.98,
        billing_period="2026-03",
        account_number="123-456-789",
        total_amount=2800,
        total_amount_confidence=0.99,
        expense_date="2026-04-15",
        expense_date_confidence=0.99,
        overall_confidence=0.97,
        low_confidence_fields=[],
    )
    result = await _call_classify(tmp_path, ocr)

    assert result.success is True
    assert result.voucher_category == "UTILITY"
    assert result.voucher_subtype == "ELECTRICITY"
    assert result.billing_period == "2026-03"
    assert result.account_number == "123-456-789"


# ---------------------------------------------------------------------------
# 測試案例 12：RENTAL / VENUE（場地租金）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_rental_venue(tmp_path: Path) -> None:
    """RENTAL/VENUE → landlord_name / rental_period 正確，expense_category=VENUE_RENTAL。"""
    ocr = VoucherOCRResult(
        is_voucher=True,
        voucher_category="RENTAL",
        voucher_subtype="VENUE",
        expense_category="VENUE_RENTAL",
        scene_reasoning="租賃合約，標題含『場地租借合約』",
        landlord_name="台北市文化中心",
        rental_period="2026-04-20 至 2026-04-20",
        property_address="台北市信義區信義路五段",
        total_amount=15000,
        total_amount_confidence=0.97,
        expense_date="2026-04-01",
        expense_date_confidence=0.99,
        rental_subtype="場地租金",
        overall_confidence=0.95,
        low_confidence_fields=[],
    )
    result = await _call_classify(tmp_path, ocr)

    assert result.success is True
    assert result.voucher_category == "RENTAL"
    assert result.voucher_subtype == "VENUE"
    assert result.expense_category == "VENUE_RENTAL"
    assert result.rental_period == "2026-04-20 至 2026-04-20"


# ---------------------------------------------------------------------------
# 測試案例 13：ACCOMMODATION（住宿費）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_accommodation(tmp_path: Path) -> None:
    """ACCOMMODATION → hotel_name / check_in_date / check_out_date 正確。"""
    ocr = VoucherOCRResult(
        is_voucher=True,
        voucher_category="ACCOMMODATION",
        voucher_subtype=None,
        expense_category="ACCOMMODATION",
        scene_reasoning="飯店帳單格式，含 Check-in/Check-out 日期與房號",
        hotel_name="君悅大酒店",
        check_in_date="2026-04-10",
        check_out_date="2026-04-12",
        guest_name="李小明",
        total_amount=8800,
        total_amount_confidence=0.99,
        expense_date="2026-04-12",
        expense_date_confidence=0.99,
        overall_confidence=0.97,
        low_confidence_fields=[],
    )
    result = await _call_classify(tmp_path, ocr)

    assert result.success is True
    assert result.voucher_category == "ACCOMMODATION"
    assert result.voucher_subtype is None
    assert result.hotel_name == "君悅大酒店"
    assert result.check_in_date == "2026-04-10"
    assert result.check_out_date == "2026-04-12"


# ---------------------------------------------------------------------------
# 測試案例 14：POSTAGE（郵資）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_postage(tmp_path: Path) -> None:
    """POSTAGE → postage_type 正確。"""
    ocr = VoucherOCRResult(
        is_voucher=True,
        voucher_category="POSTAGE",
        voucher_subtype=None,
        expense_category="POSTAGE",
        scene_reasoning="郵局掛號收據，印有掛號字樣與郵件號碼",
        total_amount=35,
        total_amount_confidence=0.97,
        expense_date="2026-04-11",
        expense_date_confidence=0.99,
        recipient="王小明",
        postage_type="掛號",
        overall_confidence=0.93,
        low_confidence_fields=[],
    )
    result = await _call_classify(tmp_path, ocr)

    assert result.success is True
    assert result.voucher_category == "POSTAGE"
    assert result.postage_type == "掛號"
    assert result.recipient == "王小明"


# ---------------------------------------------------------------------------
# 測試案例 15：CREDIT_NOTE（退貨折讓單）— total_amount 必須為負數
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_credit_note_negative_amount(tmp_path: Path) -> None:
    """CREDIT_NOTE → total_amount 強制轉為負數（即使 Gemini 回傳正值）。"""
    # 情境 A：Gemini 回傳正數 → 系統自動轉負
    ocr_positive = VoucherOCRResult(
        is_voucher=True,
        voucher_category="CREDIT_NOTE",
        voucher_subtype=None,
        expense_category="GENERAL",
        original_invoice_number="CD-87654321",
        seller_name="退貨商行",
        total_amount=500,     # 正數，應被轉為 -500
        total_amount_confidence=0.97,
        expense_date="2026-04-07",
        expense_date_confidence=0.99,
        overall_confidence=0.93,
        low_confidence_fields=[],
    )
    result_a = await _call_classify(tmp_path, ocr_positive)

    assert result_a.success is True
    assert result_a.voucher_category == "CREDIT_NOTE"
    assert result_a.total_amount == -500, "CREDIT_NOTE 正數應自動轉為負數"

    # 情境 B：Gemini 回傳負數 → 保持原值
    ocr_negative = VoucherOCRResult(
        is_voucher=True,
        voucher_category="CREDIT_NOTE",
        voucher_subtype=None,
        expense_category="GENERAL",
        original_invoice_number="CD-87654321",
        seller_name="退貨商行",
        total_amount=-500,    # 已是負數，不應再次取負
        total_amount_confidence=0.97,
        expense_date="2026-04-07",
        expense_date_confidence=0.99,
        overall_confidence=0.93,
        low_confidence_fields=[],
    )
    result_b = await _call_classify(tmp_path, ocr_negative)

    assert result_b.total_amount == -500, "已是負數不應再次取負"


# ---------------------------------------------------------------------------
# 測試案例 16：非憑證圖片（自拍照、風景照等）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_non_voucher(tmp_path: Path) -> None:
    """非憑證圖片 → is_voucher=False，所有分類欄位為 None/預設值。"""
    ocr = VoucherOCRResult(
        is_voucher=False,
        voucher_category=None,
        voucher_subtype=None,
        expense_category=None,
        scene_reasoning="看起來是自拍照，無任何財務憑證特徵",
        overall_confidence=0.0,
        low_confidence_fields=[],
    )
    result = await _call_classify(tmp_path, ocr)

    assert result.success is True
    assert result.is_voucher is False
    assert result.voucher_category is None
    assert result.voucher_subtype is None
    assert result.total_amount is None


# ---------------------------------------------------------------------------
# 測試案例 17：低信心度欄位觸發 low_confidence_fields
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_low_confidence_audit_field(tmp_path: Path) -> None:
    """seller_tax_id 信心 < KEY_FIELD_THRESHOLD → low_confidence_fields 含 seller_tax_id。"""
    ocr = VoucherOCRResult(
        is_voucher=True,
        voucher_category="INVOICE",
        voucher_subtype=None,
        expense_category="GENERAL",
        scene_reasoning="統一發票，但統編模糊",
        invoice_number="AB-12345678",
        invoice_number_confidence=0.95,
        seller_name="模糊商行",
        seller_name_confidence=0.88,
        seller_tax_id="1234567X",   # 最後一碼不確定
        seller_tax_id_confidence=0.60,  # < 0.8 → 應在 low_confidence_fields
        total_amount=1000,
        total_amount_confidence=0.97,
        expense_date="2026-04-12",
        expense_date_confidence=0.99,
        overall_confidence=0.82,
        low_confidence_fields=["seller_tax_id"],
    )
    result = await _call_classify(tmp_path, ocr)

    assert result.success is True
    assert "seller_tax_id" in result.low_confidence_fields
    # 驗證後端可正確偵測到低信心關鍵欄位
    from services.expense_service import _has_low_confidence_audit_field
    assert _has_low_confidence_audit_field(result) is True


# ---------------------------------------------------------------------------
# 測試案例 18：推論欄位（total_amount 由 net + tax 反推）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_inferred_total_amount(tmp_path: Path) -> None:
    """total_amount 模糊但 net+tax 可見 → inferred_fields 含 total_amount，note 有說明。"""
    ocr = VoucherOCRResult(
        is_voucher=True,
        voucher_category="INVOICE",
        voucher_subtype=None,
        expense_category="GENERAL",
        scene_reasoning="統一發票，total_amount 模糊，由稅前+稅額推算",
        invoice_number="GH-99887766",
        invoice_number_confidence=0.94,
        seller_name="推論測試商行",
        seller_name_confidence=0.92,
        net_amount=1000,
        net_amount_confidence=0.95,
        tax_amount=50,
        tax_amount_confidence=0.95,
        total_amount=1050,
        total_amount_confidence=0.70,   # 推論值，信心較低
        total_amount_note="由稅前金額 1000 + 稅額 50 推算",
        expense_date="2026-04-13",
        expense_date_confidence=0.99,
        inferred_fields=["total_amount"],
        overall_confidence=0.88,
        low_confidence_fields=["total_amount"],
    )
    result = await _call_classify(tmp_path, ocr)

    assert result.success is True
    assert "total_amount" in result.inferred_fields
    assert result.total_amount_note is not None
    assert "推算" in result.total_amount_note
    assert "total_amount" in result.low_confidence_fields


# ---------------------------------------------------------------------------
# 測試案例 19：Gemini API 失敗（優雅降級）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_gemini_api_failure(tmp_path: Path) -> None:
    """Gemini API 拋出例外 → success=False，不向外拋出例外（優雅降級）。"""
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake-image-bytes")

    with patch("services.ocr_service._client") as mock_client:
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("Gemini API 503 Service Unavailable")
        )
        with patch("services.ocr_service.Image") as mock_pil:
            mock_pil.open.return_value = MagicMock()
            result = await classify_and_extract(str(img_path))

    assert result.success is False
    assert result.is_voucher is False
    assert result.voucher_category is None
    assert result.error is not None
    assert "503" in result.error or "Gemini" in result.error


# ---------------------------------------------------------------------------
# 測試案例 20：向下相容驗證 — 無子類型的類別 voucher_subtype=None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_subtype_categories_have_null_subtype(tmp_path: Path) -> None:
    """INVOICE / LABOR_SERVICE / CREDIT_NOTE / POSTAGE / ACCOMMODATION 的 voucher_subtype 應為 None。"""
    for category in ["INVOICE", "LABOR_SERVICE", "POSTAGE"]:
        ocr = VoucherOCRResult(
            is_voucher=True,
            voucher_category=category,
            voucher_subtype=None,  # 這些類別無子類型
            expense_category="GENERAL",
            total_amount=100,
            overall_confidence=0.9,
        )
        result = await _call_classify(tmp_path, ocr)
        assert result.voucher_subtype is None, f"{category} 應無子類型"
