"""OCR 結構化輸出 Schema — 作為 Gemini response_schema 及後端資料傳遞型別。"""

from pydantic import BaseModel, Field

from core.config import settings

# ── 關鍵稽核欄位：任一欄位信心 < KEY_FIELD_THRESHOLD → NEEDS_MANUAL_REVIEW ──
KEY_AUDIT_FIELDS: frozenset[str] = frozenset(
    {"invoice_number", "seller_tax_id", "total_amount", "id_number"}
)
KEY_FIELD_THRESHOLD: float = settings.key_field_confidence_threshold


class VoucherOCRResult(BaseModel):
    """
    Gemini structured output schema + 後端 OCR 結果型別。

    設計原則：
    - 平坦結構（每個欄位搭配同層 _confidence float），對 Gemini response_schema 最相容
    - 所有類型特定欄位共存於同一模型，Gemini 對無關欄位填 null
    - success / error / raw_response 為後端控制欄位，不送進 Gemini prompt
    """

    # ── 分類 ────────────────────────────────────────────────────────────────
    is_voucher: bool = False
    # 憑證類型：INVOICE / RECEIPT / LABOR_FORM / DEPOSIT / OTHER（OCR 判定）
    # RETURN 僅由 LIFF 待退貨標記寫入，OCR 不再產生此值
    voucher_category: str | None = None
    # 子類型，例如 HSR_TICKET / FUEL / EXEMPT_INVOICE 等（OCR 內部用）
    voucher_subtype: str | None = None
    # 費用科目中文名稱（對應 config/expense_categories.json categories[].label）
    # 無法判斷時填「現場拍攝用品購買」
    expense_category: str | None = None

    # ── GenAI 推理說明 ───────────────────────────────────────────────────────
    # e.g. "店名含『中油』→ 加油站消費 → TRANSPORTATION/FUEL"
    scene_reasoning: str = ""
    # 由推論而非直接讀取得到的欄位名稱列表，e.g. ["total_amount"]
    inferred_fields: list[str] = Field(default_factory=list)

    # ── 通用欄位 + 信心分數 ──────────────────────────────────────────────────
    expense_date: str | None = None          # YYYY-MM-DD
    expense_date_confidence: float = 0.0

    total_amount: float | None = None        # 含稅總金額（CREDIT_NOTE 為負數）
    total_amount_confidence: float = 0.0
    total_amount_note: str | None = None     # 推論說明，e.g. "由稅前 1000 + 稅額 50 推算"

    seller_name: str | None = None
    seller_name_confidence: float = 0.0

    # ── 關鍵稽核欄位（< KEY_FIELD_THRESHOLD → 加入 low_confidence_fields）────
    invoice_number: str | None = None        # 格式：AB-12345678
    invoice_number_confidence: float = 0.0

    seller_tax_id: str | None = None         # 賣方統一編號（8 碼數字）
    seller_tax_id_confidence: float = 0.0

    buyer_tax_id: str | None = None          # 買方統一編號（B2B 才有）
    buyer_tax_id_confidence: float = 0.0

    net_amount: float | None = None          # 稅前金額
    net_amount_confidence: float = 0.0

    tax_amount: float | None = None          # 稅額
    tax_amount_confidence: float = 0.0

    # ── TRANSPORTATION 專屬欄位 ──────────────────────────────────────────────
    route_from: str | None = None            # 起點（停車費填 null）
    route_to: str | None = None              # 迄點（停車費填 null）
    transport_type: str | None = None        # 高鐵 / 台鐵 / 計程車 / 客運 / 停車 / 過路費 / Uber / 油資 / 罰單 / 遊覽車
    ticket_type: str | None = None           # HSR_TICKET：實體票 / 電子票 / 優惠票
    receipt_type: str | None = None          # TAXI：跳表收據 / 手寫收據 / 電子收據
    fuel_type: str | None = None             # FUEL：92無鉛 / 95無鉛 / 98無鉛 / 柴油
    bus_operator: str | None = None          # BUS：客運業者名稱
    train_class: str | None = None           # TAIWAN_RAILWAY：自強 / 莒光 / 區間 等
    parking_location: str | None = None      # PARKING：停車場名稱或地址
    highway_name: str | None = None          # TOLL_ETC：國道名稱
    operator_name: str | None = None         # CHARTER_BUS：遊覽車公司名稱
    fine_type: str | None = None             # FINE：違規事由

    # ── LABOR_SERVICE 專屬欄位 ──────────────────────────────────────────────
    payee_name: str | None = None            # 受款人姓名
    id_number: str | None = None             # 身分證字號（1 英文 + 9 數字）
    id_number_confidence: float = 0.0
    labor_content: str | None = None         # 勞務內容說明

    # ── INSURANCE 專屬欄位 ──────────────────────────────────────────────────
    insurer_name: str | None = None          # 保險公司名稱
    insured_name: str | None = None          # 被保險人姓名
    policy_number: str | None = None         # 保單號碼
    insurance_type: str | None = None        # 童工證保險 / 意外險 / 人身保險

    # ── UTILITY 專屬欄位 ────────────────────────────────────────────────────
    billing_period: str | None = None        # 帳單期間，e.g. "2026-03"
    account_number: str | None = None        # 帳號/用戶號碼
    phone_number: str | None = None          # TELECOM：電話號碼
    building_name: str | None = None         # MANAGEMENT_FEE：大樓名稱

    # ── RENTAL 專屬欄位 ──────────────────────────────────────────────────────
    landlord_name: str | None = None         # 出租方名稱
    rental_period: str | None = None         # 租期，e.g. "2026-04 至 2026-04"
    property_address: str | None = None      # 租賃物件地址
    rental_subtype: str | None = None        # 場地租金 / 辦公室租金 / 辦公室用品租金 / 車輛租金

    # ── ACCOMMODATION 專屬欄位 ──────────────────────────────────────────────
    hotel_name: str | None = None            # 飯店/民宿名稱
    check_in_date: str | None = None         # 入住日期（YYYY-MM-DD）
    check_out_date: str | None = None        # 退房日期（YYYY-MM-DD）
    guest_name: str | None = None            # 住客姓名

    # ── RECEIPT 專屬欄位 ────────────────────────────────────────────────────
    item_description: str | None = None      # 品項描述
    has_exempt_stamp: bool = False           # 是否有「免用統一發票」章

    # ── CREDIT_NOTE 專屬欄位 ────────────────────────────────────────────────
    original_invoice_number: str | None = None  # 原始發票字軌號碼

    # ── POSTAGE 專屬欄位 ────────────────────────────────────────────────────
    recipient: str | None = None             # 收件人
    postage_type: str | None = None          # 掛號 / 平信 / 包裹 / 快遞 / 其他

    # ── 覆核摘要（由 Gemini 填寫）────────────────────────────────────────────
    # Gemini 自行填入信心低於門檻的欄位名稱；後端依此判斷是否 NEEDS_MANUAL_REVIEW
    low_confidence_fields: list[str] = Field(default_factory=list)
    overall_confidence: float = 0.0

    # ── 後端控制欄位（不送進 Gemini prompt）─────────────────────────────────
    success: bool = True
    error: str | None = None
    raw_response: str = ""
