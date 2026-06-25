"""
四情境補件關聯類型規則 — 單一來源（Single Source of Truth）

新增情境或修改報表邏輯時，只需改此一處。
各 service / router 統一從這裡 import，禁止在其他模組直接寫死類型清單。

情境對照：
  VOID_REPLACE      — 換新發票：新發票登錄，原發票產生 VOID_REVERSAL 沖銷
  CREDIT_NOTE       — 折讓單：獨立負數，原發票不動，不產生沖銷
  RETURN_SUPPLEMENT — 換貨收據：新收據登錄，原收據產生 RETURN_REVERSAL 沖銷
  AMOUNT_CORRECTION — 舊收據改金額：與換貨收據結構相同，但語意不同

  VOID_ORIGINAL  — 被換新發票取代的舊發票（系統自動標記，非使用者上傳）
  VOID_REVERSAL  — 換新發票的沖銷分錄（負數，系統自動建立）
  RETURN_REVERSAL— 換貨收據/改金額的沖銷分錄（負數，系統自動建立）
"""

from models.expense import ExpenseStatus

# ── 補件類型 ────────────────────────────────────────────────────────────────

# 出現在待退貨管理右側（孤立補件池）的所有補件 relation_type
SUPPLEMENT_TYPES: frozenset[str] = frozenset({
    "VOID_REPLACE",
    "CREDIT_NOTE",
    "RETURN_SUPPLEMENT",
    "AMOUNT_CORRECTION",
})

# 系統自動建立、只出現在子列的沖銷分錄類型
REVERSAL_TYPES: frozenset[str] = frozenset({
    "VOID_REVERSAL",
    "RETURN_REVERSAL",
})

# 補件上傳後需自動建立 RETURN_REVERSAL 沖銷分錄的類型
# 折讓單（CREDIT_NOTE）本身即為負數，不需要額外沖銷
# 換新發票（VOID_REPLACE）的沖銷由 VOID_REVERSAL 負責
REVERSAL_REQUIRED_TYPES: frozenset[str] = frozenset({
    "RETURN_SUPPLEMENT",
    "AMOUNT_CORRECTION",
})

# CSV 強制納入（不受日期篩選遮蔽）的關聯類型
CSV_FORCE_INCLUDE_TYPES: frozenset[str] = frozenset({
    "VOID_REVERSAL",
    "RETURN_REVERSAL",
    "CREDIT_NOTE",
    "VOID_ORIGINAL",
    "AMOUNT_CORRECTION",
})

# ── return_record 語意說明（文件用，不參與程式邏輯）────────────────────────

RETURN_RECORD_DESCRIPTION: dict[str, str] = {
    "VOID_REPLACE":      "原始發票號碼（如 AB-12345678）",
    "CREDIT_NOTE":       "原始發票號碼（如 AB-12345678）",
    "RETURN_SUPPLEMENT": "原始收據的發票號碼；無發票號碼則為案件編號",
    "AMOUNT_CORRECTION": "原始收據的發票號碼；無發票號碼則為案件編號",
}

# ── CSV 報表輸出規則 ────────────────────────────────────────────────────────

def csv_remark(
    relation_type: str | None,
    status: ExpenseStatus,
    reject_reason: str | None,
    void_reason: str | None,
) -> str:
    """
    決定 CSV 備注欄文字。

    - 沖銷分錄 → "沖銷分錄"
    - 換單作廢 → void_reason / reject_reason / "換單作廢"
    - 其餘      → reject_reason（或空白）
    """
    if relation_type in REVERSAL_TYPES:
        return "沖銷分錄"
    if status == ExpenseStatus.REPLACED_VOID:
        return void_reason or reject_reason or "換單作廢"
    return reject_reason or ""
