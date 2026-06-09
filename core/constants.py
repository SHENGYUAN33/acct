"""業務常數集中管理。

將原本散落在 routers/expenses.py 頂層的對照表與欄位定義集中於此，
讓 Router 層只負責請求處理，不承擔業務常數的定義職責。

若其他模組（如 LINE 推播、報表產生、前端 API 等）需要這些對照，
統一從此模組 import，不要在各自檔案中重複定義。
"""

# ── 憑證類別 → 中文（與 config/expense_categories.json voucher_categories 同源）──
VOUCHER_CATEGORY_ZH: dict[str, str] = {
    "INVOICE":    "發票",
    "RECEIPT":    "收據",
    "LABOR_FORM": "勞保",
    "DEPOSIT":    "押金",
    "RETURN":     "退貨",
    "OTHER":      "其他",
    "CREDIT_NOTE": "退貨",  # 舊資料相容
}

# ── 費用狀態 → 中文 ────────────────────────────────────────────────
STATUS_ZH: dict[str, str] = {
    "PENDING": "未審核",
    "APPROVED": "已核准",
    "REJECTED": "已作廢",
    "NEEDS_MANUAL_REVIEW": "未審核（需特別注意）",
    "WAITING_RETURN": "待退貨",
    "REPLACED_VOID": "已作廢（沖銷）",
}

# ── 費用科目 key → 中文（從單一來源衍生，不得手動維護）──────────────────────
from core.expense_categories import KEY_TO_LABEL as EXPENSE_CATEGORY_ZH  # noqa: E402

# ── CSV 匯出欄位定義 ────────────────────────────────────────────────
CSV_HEADERS: list[str] = [
    "案件編號", "ID", "上傳者", "上傳者組別", "費用提報者", "費用提報者組別",
    "上傳日期", "費用日期", "發票號碼", "憑證類別", "細項", "含稅金額", "未稅金額", "營業稅額",
    "賣方統編", "賣方公司", "項目說明", "憑證狀態", "退件原因",
    "建立時間", "更新時間",
]

# ── 進項稅額明細表欄位定義 ──────────────────────────────────────────
TAX_REPORT_HEADERS: list[str] = [
    "案件編號", "費用日期", "發票號碼", "憑證類型", "憑證子類型", "稅務類別",
    "賣方統編", "賣方名稱", "稅前金額", "營業稅額", "含稅金額",
    "費用科目", "上傳者", "上傳者組別", "項目說明", "使用者備註",
    "憑證狀態", "備注",
]
