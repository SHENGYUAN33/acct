/**
 * 審核狀態單一來源（Single Source of Truth）
 *
 * 所有元件的狀態標籤、顏色、篩選選項皆從此衍生，不得各自定義複本。
 * label 需與後端 core/constants.py STATUS_ZH 保持一致。
 */

export const STATUS_CONFIG = {
  PENDING:             { label: '未審核',               dot: 'bg-yellow-400', textColor: 'text-yellow-600' },
  APPROVED:            { label: '已核准',               dot: 'bg-green-500',  textColor: 'text-green-600'  },
  REJECTED:            { label: '已作廢',               dot: 'bg-gray-400',   textColor: 'text-gray-500'   },
  NEEDS_MANUAL_REVIEW: { label: '未審核（需特別注意）', dot: 'bg-orange-400', textColor: 'text-orange-500' },
  WAITING_RETURN:      { label: '待退貨',               dot: 'bg-purple-500', textColor: 'text-purple-600' },
  REPLACED_VOID:       { label: '已作廢（沖銷）', dot: 'bg-gray-400',   textColor: 'text-gray-500'   },
}

/** 查詢單一狀態設定；未知狀態回傳灰色 fallback，不拋例外 */
export function getStatusConfig(status) {
  return STATUS_CONFIG[status] ?? { label: status ?? '—', dot: 'bg-gray-300', textColor: 'text-gray-400' }
}

/** FilterPanel 篩選下拉用（只顯示可篩選的狀態子集） */
export const FILTER_STATUS_OPTIONS = [
  { value: '',                   label: '全部狀態' },
  { value: 'PENDING',            label: STATUS_CONFIG.PENDING.label },
  { value: 'NEEDS_MANUAL_REVIEW',label: STATUS_CONFIG.NEEDS_MANUAL_REVIEW.label },
  { value: 'APPROVED',           label: STATUS_CONFIG.APPROVED.label },
  { value: 'WAITING_RETURN',     label: STATUS_CONFIG.WAITING_RETURN.label },
]
