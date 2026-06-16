"""OCR Service — 使用 Google Gemini API 進行憑證辨識、場景推論與欄位信心評分。"""

import asyncio
import logging
from io import BytesIO
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image

from core.config import settings
from core.expense_categories import build_ocr_prompt_list
from schemas.ocr import VoucherOCRResult
from services import object_storage

logger = logging.getLogger(__name__)

# Initialise Gemini client once at import time
_client = genai.Client(api_key=settings.gemini_api_key)

# Semaphore 限制 OCR 並行數量。預設為 None（函式內建立）。
# 測試可 patch 此變數注入當前 event loop 的 Semaphore，避免跨 event loop 錯誤。
_OCR_SEMAPHORE: asyncio.Semaphore | None = None


# ── Prompt ────────────────────────────────────────────────────────────────────

_PROMPT_TEMPLATE = """你是一個具備台灣會計知識的財務審計助理。請分析這張圖片，依序執行以下三個步驟，最後嚴格依照 JSON Schema 回傳結果。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【步驟一：場景推理（scene_reasoning）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
觀察圖片上的所有視覺線索：店名、品項、格式、印章、色彩、LOGO、版面配置、印刷字體。
根據這些線索推斷「這筆費用最可能發生在什麼場景」，在 scene_reasoning 欄位用一句話說明你的推理過程。

━━ 步驟 1A：憑證類型（voucher_category）━━
  INVOICE    → 印有「統一發票」字樣，有字軌號碼（如 AB-12345678）
              ※ 統一發票右上或表頭區通常印有賣方統一編號（8 碼數字），務必萃取至 seller_tax_id；
                電子發票載具條碼區段旁亦常有賣方統編，同樣萃取
  RECEIPT    → 視覺上為傳統收據格式：POS 收銀機列印或手寫收據（賣方名稱＋品項＋金額）；無統一發票字軌
              範例：超商收據、餐廳收據、加油站 POS 收據、停車場 POS 收據、文具店收據
              **不包含**：票根、票券、對帳單、帳單、政府公文、截圖、保險文件、銀行文件、醫療收據、證明文件
  LABOR_FORM → 勞務報酬單；含手寫金額＋身分證字號＋收款人簽章
  DEPOSIT    → 押金收據、訂金收據
  OTHER      → 無法歸入以上任何類型（含折讓單、退貨折讓證明、換貨收據、換新發票補件等退換貨相關文件一律歸此類）

子類型（voucher_subtype，僅 RECEIPT 適用）：
  RECEIPT   → EXEMPT_INVOICE（有「免用統一發票」圓形橡皮章）/ GENERAL（無）
              ※ EXEMPT_INVOICE：橡皮章內通常印有賣方統一編號（8 碼數字），務必萃取至 seller_tax_id
  交通相關 RECEIPT 子類型（視覺為 POS 列印收據者）：
    PARKING        停車場 POS 列印收據
    FUEL           加油站 POS 列印收據
  OTHER 的 voucher_subtype 一律填 null
  其餘類型 voucher_subtype 填 null

━━ 步驟 1B：費用科目（expense_category）━━
從以下清單選一，填入**完整中文名稱**：

  {CATEGORY_LIST}

  **重要：若無法判斷，expense_category 填「勞-現場拍攝用品購買」**

場景推理範例：
  - 「店名含『中油、台塑石化、全國加油』+ POS 列印格式 → 加油站收據 → voucher_category=RECEIPT, voucher_subtype=FUEL, expense_category=勞-交通費-油資」
  - 「品項含飯、便當、套餐 → 餐廳收據 → voucher_category=RECEIPT, expense_category=勞-餐飲費」
  - 「版面含 Check-in/Check-out 日期與房號 → 飯店帳單，帳單格式非收據 → voucher_category=OTHER, expense_category=勞-住宿費」
  - 「有買方統一編號已填入 → B2B 公司採購發票 → voucher_category=INVOICE」
  - 「手寫金額＋身分證字號＋收款人簽章 → 勞報單 → voucher_category=LABOR_FORM, expense_category=勞-勞務費」
  - 「台電/中華電信格式帳單，含帳單期間與用量明細 → 帳單格式非收據 → voucher_category=OTHER, expense_category=勞-水電瓦斯費 或 勞-電信/網路費」
  - 「台灣高鐵票根，含車次/座位/起訖站 → 票券非收據 → voucher_category=OTHER, expense_category=勞-交通費-高鐵、台鐵、客運、遊覽車」
  - 「遠通電收/ETC 通行費明細紀錄，含多筆通行時間與路段 → 對帳單格式非收據 → voucher_category=OTHER, expense_category=勞-交通費-過路費」
  - 「計程車運價證明（政府制式表格，手寫車資/車號/駕駛人）→ 證明文件格式非收據 → voucher_category=OTHER, expense_category=勞-交通費-計程車資」
  - 「文具四件、A4 影印紙 → expense_category=勞-文具用品」
  - 「五金行收據、商品名稱不明 → 無法確定部門 → expense_category=勞-現場拍攝用品購買」

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【步驟二：欄位萃取與合理性推論】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
萃取所有可見欄位。若關鍵欄位不清晰，依會計常識進行合理推論：

(A) 金額推論
  - total_amount 模糊，但可見 net_amount 和 tax_amount
    → total_amount = net_amount + tax_amount
    → 將 "total_amount" 加入 inferred_fields
    → total_amount_note 填「由稅前金額 {net} + 稅額 {tax} 推算」

(B) 日期推論與民國曆轉換（最重要）
  - 台灣憑證幾乎全部使用民國年份，必須轉換為西元再填入 expense_date
    轉換公式：民國年 + 1911 = 西元年
    範例：
      115/03/12  → 2026-03-12
      115-03-12  → 2026-03-12
      115年3月12日 → 2026-03-12
      114.12.25  → 2025-12-25
      113/1/5    → 2024-01-05
  - expense_date 輸出格式必須嚴格遵守 YYYY-MM-DD（西元四位數年份），禁止輸出民國格式
  - 數字 1 與 7 在印刷體中極易混淆，辨識時必須用以下規則自我檢核：
    * 月份必須介於 01–12；若辨識結果 > 12（如 17 月），代表 7 被誤讀為 1 或反之，需修正
    * 日期必須介於 01–31；若辨識結果 > 31（如 37 日），同理需修正
    * 統一發票上方印有「期別」（如「115年03-04月」），可作為日期月份的交叉驗證依據
    * 其他易混淆數字對：0 與 6、3 與 8、5 與 6，遇模糊時同樣以合理範圍優先判斷
  - expense_date 只有月日無年份
    → 依票據格式（民國/西元）及常理推估最可能的年份
    → 將 "expense_date" 加入 inferred_fields
  - 統一發票：字軌號碼旁通常印有期別（如「115年01-02月」）
    → 以帳單月份中間日推估（如 01-02月 → 2026-01-15）

(C) 統一編號驗算
  - 台灣統一編號使用加權驗證法（weights: 1,2,1,2,1,2,4,1）
  - 若驗算結果吻合 → 信心維持高分
  - 若有一字元不確定 → seller_tax_id_confidence 設為 0.6

(D) 發票字軌推論
  - invoice_number 若有一字元辨識不確定
    → 給出最可能的值，invoice_number_confidence 設為 0.6

(E) 折讓金額（RETURN + original_invoice_number）
  - total_amount 必須為負數（折讓）

各類型萃取欄位清單：
  INVOICE       → invoice_number, seller_name, seller_tax_id, buyer_tax_id,
                   total_amount, net_amount, tax_amount, expense_date
                   ※ seller_tax_id 為 8 碼數字，通常印於發票右上角或表頭賣方欄；
                     電子發票亦同，務必萃取，不得遺漏
  RECEIPT       → seller_name, seller_tax_id, total_amount, expense_date,
                   has_exempt_stamp（EXEMPT_INVOICE 子類型為 true）
                   ※ 收據上若印有「統一編號」欄位，務必萃取至 seller_tax_id（8 碼數字）
  LABOR_SERVICE → payee_name, id_number, net_amount, tax_amount, total_amount,
                   expense_date, labor_content
  TRANSPORTATION→ expense_date, route_from, route_to, total_amount, transport_type
                   + 子類型額外欄位（ticket_type/receipt_type/fuel_type/
                     bus_operator/train_class/parking_location/highway_name/
                     operator_name/fine_type）
  RETURN（折讓）→ seller_name, original_invoice_number, total_amount（負數）, expense_date
  INSURANCE     → expense_date, insurer_name, insured_name, total_amount,
                   policy_number, insurance_type
  UTILITY       → expense_date, seller_name, total_amount, billing_period,
                   account_number; TELECOM 加 phone_number; MANAGEMENT_FEE 加 building_name
  RENTAL        → expense_date, landlord_name, total_amount, rental_period,
                   property_address, rental_subtype
  ACCOMMODATION → expense_date, hotel_name, total_amount, check_in_date,
                   check_out_date, guest_name
  POSTAGE       → expense_date, total_amount, recipient, postage_type

PARKING 的 route_from / route_to 填 null，parking_location 填停車場地點。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【步驟三：信心評分與覆核標記】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
對每個有資料的欄位給出 0.0–1.0 的信心分數：
  1.0  = 清晰可見，無任何疑義
  0.9  = 可見但有輕微列印模糊
  0.8  = 可見但字跡偏小或稍微模糊
  0.5–0.79 = 部分可見或需合理推論
  0.0–0.49 = 高度不確定或完全推論

low_confidence_fields 填入規則：
  關鍵稽核欄位（invoice_number / seller_tax_id / buyer_tax_id / total_amount / id_number）
    信心 < 0.8 → 加入 low_confidence_fields
  其餘欄位
    信心 < 0.6 → 加入 low_confidence_fields
  inferred_fields 中的欄位若信心 < 0.8 亦加入

overall_confidence = 所有已填欄位信心分數的加權平均（以 total_amount 權重最高）

若圖片不是財務憑證（如自拍照、風景照），回傳 is_voucher: false，其餘欄位填預設值。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【補充判斷規則】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

(F) 折讓單強化識別：
  核心判斷依據：以下任一特徵 → voucher_category = RETURN，並填入 original_invoice_number
    * 標題含「折讓」、「退貨折讓」、「銷貨退回折讓單」、「折讓證明單」
    * 金額欄位含括號金額（台灣會計負數慣例：如 (1,200) 表示負 1,200 元）
    * 含「原發票字軌號碼」、「原發票號碼：」、「退貨發票號碼」標示欄
    * 文件整體呈現「退款」而非「收款」的交易方向
  original_invoice_number：
    → 優先讀取「原發票字軌」欄位，格式：2 大寫英文字母 + 連字號 + 8 位數字（如 AB-12345678）
    → 若欄位模糊，在文件全文中尋找此格式的字串
  total_amount 必須填負數（退款金額）

(G) 憑證圖 vs. 商品圖的視覺判斷準則：

  【憑證圖特徵（is_voucher: true）】
    ✓ 大量印刷文字、表格、欄位標籤（如：品名、數量、金額）
    ✓ 印章（統一發票章、免用統一發票章、收訖章）
    ✓ 條碼、QR Code、發票序號
    ✓ 金額、日期、統一編號等財務資訊清晰可見
    ✓ 店家名稱、賣方資訊

  【商品圖特徵（is_voucher: false，voucher_category: null）】
    ✗ 主體為具體物品（衣服、腳架、道具、設備）
    ✗ 無金額、無賣方統編、無發票編號
    ✗ 照片風格（非文件掃描）
    ✗ 損壞照片（用於損害舉證）
    ✗ 包裝標籤（僅有品名，無金融交易資訊）

  → 商品圖 scene_reasoning 應標明：「商品照片，非財務憑證，歸屬為物品附件」

(H) 差額補足憑證（SUPPLEMENT）：
  - 若同一圖片中可見兩份單據（原收據 + 差額補單，常見於拍照並排）：
    * 分別萃取各自的 invoice_number / total_amount
    * 以金額較大者作為本次主憑證
    * 於 scene_reasoning 說明「含差額補足，已取主憑證金額 {X}，次憑證金額 {Y}」
"""


def _build_prompt() -> str:
    """在 runtime 將 {CATEGORY_LIST} 替換為最新科目清單（由 expense_categories 單一來源產生）。"""
    return _PROMPT_TEMPLATE.replace("{CATEGORY_LIST}", build_ocr_prompt_list())


def _extract_image_path(image_path: str | Path | dict | list) -> str | Path:
    """
    智慧路徑提取：防禦 Sprint 3 新格式（含 metadata 的 dict/list）。
    PIL.Image.open() 只接受 str 或 Path，此函式確保回傳值符合要求。

    支援格式：
    - str / Path  → 直接回傳
    - dict        → 取 'path' 鍵值（e.g. {"path": "...", "timestamp": ..., "message_id": ...}）
    - list        → 遞迴取第一項的路徑
    """
    if isinstance(image_path, dict):
        return image_path.get("path", "")
    if isinstance(image_path, list):
        if not image_path:
            return ""
        return _extract_image_path(image_path[0])
    return image_path  # str 或 Path，直接回傳


async def classify_and_extract(image_path: str | Path | dict | list) -> VoucherOCRResult:
    """
    送出圖片至 Gemini，以三步驟推理鏈進行場景分類、欄位萃取與信心評分。

    使用 response_schema=VoucherOCRResult 的 Structured Output 模式，
    response.parsed 直接回傳 Pydantic 物件，不需手動解析 JSON。

    Args:
        image_path: 圖片檔案的本地路徑。支援純字串、Path 物件，
                    或 Sprint 3 新格式的含 metadata dict/list。

    Returns:
        VoucherOCRResult（success=True 表示正常完成；
        success=False 時 error 欄位有錯誤說明，不拋出例外）。
    """
    resolved_path = _extract_image_path(image_path)
    try:
        data = object_storage.get_bytes(str(resolved_path))
        if data is None:
            raise FileNotFoundError(f"找不到圖片：{resolved_path}")
        with Image.open(BytesIO(data)) as img:
            response = await _client.aio.models.generate_content(
                model=settings.gemini_model,
                contents=[_build_prompt(), img],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=VoucherOCRResult,
                ),
            )

        result: VoucherOCRResult = response.parsed

        # 折讓（RETURN + original_invoice_number）：total_amount 必須為負數
        is_credit = (
            result.is_voucher
            and result.voucher_category in ("RETURN", "CREDIT_NOTE")
        )
        if is_credit and result.total_amount is not None and result.total_amount > 0:
            result.total_amount = -result.total_amount

        result.raw_response = response.text or ""
        result.success = True
        return result

    except Exception as exc:
        logger.error("classify_and_extract failed for %s: %s", resolved_path, exc, exc_info=True)
        return VoucherOCRResult(
            is_voucher=False,
            success=False,
            error=str(exc),
            raw_response="",
        )


async def classify_and_extract_with_retry(
    image_path: str | Path,
    max_retries: int = 3,
) -> VoucherOCRResult:
    """
    帶指數退避 retry 的 OCR 入口，同時受 _OCR_SEMAPHORE 限制並行數量。

    Retry 策略：
      第 1 次失敗 → 等 1 秒後重試
      第 2 次失敗 → 等 2 秒後重試
      第 3 次失敗 → 直接回傳最後一次失敗結果（success=False）

    Args:
        image_path: 圖片檔案的本地路徑。
        max_retries: 最大嘗試次數（包含第一次，預設 3）。

    Returns:
        VoucherOCRResult
    """
    max_retries = int(max_retries)
    semaphore = _OCR_SEMAPHORE if _OCR_SEMAPHORE is not None else asyncio.Semaphore(int(settings.ocr_max_concurrent))
    result = VoucherOCRResult(is_voucher=False, success=False, error="未執行")
    for attempt in range(max_retries):
        async with semaphore:
            result = await classify_and_extract(image_path)
        if result.success:
            return result
        if attempt < max_retries - 1:
            wait_secs = 2 ** attempt  # 1, 2 秒
            logger.warning(
                "OCR retry %d/%d for %s, waiting %ds (error: %s)",
                attempt + 1,
                max_retries,
                image_path,
                wait_secs,
                result.error,
            )
            await asyncio.sleep(wait_secs)
    return result
