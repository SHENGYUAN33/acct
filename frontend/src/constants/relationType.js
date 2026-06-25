/**
 * 補件關聯類型單一來源（Single Source of Truth）
 *
 * badge 標籤、顏色、下拉選項皆從此衍生，禁止各元件各自定義複本。
 * 修改顏色或文字只需改此一處，所有元件自動跟上。
 */

export const RELATION_TYPE_CONFIG = {
  VOID_REPLACE: {
    label: '換新發票',
    badgeClass: 'bg-blue-100 text-blue-600 border-blue-200',
    optionClass: 'text-blue-600 hover:bg-blue-50',
  },
  CREDIT_NOTE: {
    label: '折讓單',
    badgeClass: 'bg-orange-100 text-orange-600 border-orange-200',
    optionClass: 'text-orange-600 hover:bg-orange-50',
  },
  RETURN_SUPPLEMENT: {
    label: '換貨收據',
    badgeClass: 'bg-teal-100 text-teal-600 border-teal-200',
    optionClass: 'text-teal-600 hover:bg-teal-50',
  },
  SUPPLEMENT: {
    // 舊版「差額補足」，現已統一視為換貨收據
    label: '換貨收據',
    badgeClass: 'bg-teal-100 text-teal-600 border-teal-200',
    optionClass: 'text-teal-600 hover:bg-teal-50',
  },
  VOID_ORIGINAL: {
    label: '被換單',
    badgeClass: 'bg-gray-100 text-gray-500 border-gray-200',
    optionClass: '',
  },
  VOID_REVERSAL: {
    label: '沖銷分錄',
    badgeClass: 'bg-red-100 text-red-600 border-red-200',
    optionClass: '',
  },
  RETURN_REVERSAL: {
    label: '沖銷分錄',
    badgeClass: 'bg-red-100 text-red-600 border-red-200',
    optionClass: '',
  },
  AMOUNT_CORRECTION: {
    label: '舊收據改金額',
    badgeClass: 'bg-purple-100 text-purple-600 border-purple-200',
    optionClass: 'text-purple-600 hover:bg-purple-50',
  },
}

/** 查詢設定；未知類型回傳 null */
export function getRelationTypeConfig(type) {
  return RELATION_TYPE_CONFIG[type] ?? null
}

/** 可由使用者在主頁面下拉修改的類型（含舊版 SUPPLEMENT） */
export const EDITABLE_RELATION_TYPES = ['VOID_REPLACE', 'CREDIT_NOTE', 'RETURN_SUPPLEMENT', 'SUPPLEMENT', 'AMOUNT_CORRECTION']

/** 待退貨管理補件類型（後端查詢用、前端 filter 用） */
export const SUPPLEMENT_RELATION_TYPES = ['VOID_REPLACE', 'CREDIT_NOTE', 'RETURN_SUPPLEMENT', 'AMOUNT_CORRECTION']

/** 下拉選項（四種正規類型，SUPPLEMENT 已收斂至 RETURN_SUPPLEMENT） */
export const RELATION_TYPE_OPTIONS = [
  { value: 'RETURN_SUPPLEMENT',  ...RELATION_TYPE_CONFIG.RETURN_SUPPLEMENT },
  { value: 'CREDIT_NOTE',        ...RELATION_TYPE_CONFIG.CREDIT_NOTE },
  { value: 'VOID_REPLACE',       ...RELATION_TYPE_CONFIG.VOID_REPLACE },
  { value: 'AMOUNT_CORRECTION',  ...RELATION_TYPE_CONFIG.AMOUNT_CORRECTION },
]
