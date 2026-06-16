/**
 * 憑證類別單一來源（Single Source of Truth）
 *
 * 官方清單與後端 config/expense_categories.json voucher_categories 一致。
 * 舊代碼 fallback 僅供歷史資料相容，新資料不應出現舊代碼。
 */

/** 官方清單（與 GET /api/v1/config/voucher-categories 同步，供下拉選單初始值） */
export const OFFICIAL_VOUCHER_CATEGORIES = [
  { value: 'INVOICE',    label: '發票' },
  { value: 'RECEIPT',    label: '收據' },
  { value: 'LABOR_FORM', label: '勞保' },
  { value: 'DEPOSIT',    label: '押金' },
  { value: 'RETURN',     label: '退貨' },
  { value: 'OTHER',      label: '其他' },
]

/** key → label 映射（現行官方代碼 + 舊代碼 fallback） */
export const VOUCHER_LABEL_MAP = {
  INVOICE:        '發票',
  RECEIPT:        '收據',
  LABOR_FORM:     '勞保',
  DEPOSIT:        '押金',
  RETURN:         '退貨',
  CREDIT_NOTE:    '退貨',        // 舊資料相容：OCR 舊版存 CREDIT_NOTE，顯示同 RETURN
  TRANSPORTATION: '交通費',      // 舊資料相容：OCR 舊版存 TRANSPORTATION
  OTHER:          '其他',
}

/** key → label；未知 key 原樣回傳 */
export function getVoucherLabel(key) {
  return VOUCHER_LABEL_MAP[key] ?? key ?? '—'
}
