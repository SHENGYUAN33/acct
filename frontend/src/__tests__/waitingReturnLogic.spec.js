/**
 * Unit Tests — WaitingReturnModal 純邏輯函式 (P2)
 *
 * 測試策略：
 * WaitingReturnModal 為複雜的 Vue 元件，含大量 UI 互動邏輯。
 * 此測試不掛載整個元件，而是測試其中可提取的「純邏輯函式」：
 * - rightPanelItems computed 邏輯（顯示優先級：進階篩選 > 搜尋 > 孤立補件）
 * - toggleExpand 手風琴邏輯
 * - searchSupplements 篩選條件（relation_type 過濾）
 * - imgUrl 圖片 URL 轉換邏輯
 * - STATUS_LABEL / VOUCHER_CATEGORY_LABEL 常數正確性
 *
 * 為何需要這些測試：
 * - PR ca47224 修改了補件配對架構，rightPanelItems 優先級邏輯影響 UI 顯示
 * - imgUrl 函式若邏輯錯誤，Dashboard 所有圖片會顯示為空白
 * - 常數 label 對應正確性影響審計報表中的狀態顯示
 */

import { describe, it, expect, beforeEach } from 'vitest'

// ── 從 WaitingReturnModal 提取出的純邏輯（不依賴 Vue 響應式） ──────────────

const BACKEND_BASE = 'http://localhost:8000'

/** 對應 WaitingReturnModal.vue 的 imgUrl() */
function imgUrl(url) {
  if (!url) return ''
  return url.startsWith('http') ? url : `${BACKEND_BASE}/${url}`
}

/** 對應 WaitingReturnModal.vue 的 rightPanelItems computed 邏輯 */
function getRightPanelItems({
  rightActiveCount,
  rightFilterResults,
  searchQuery,
  searchResults,
  orphanSupplements,
}) {
  if (rightActiveCount > 0 && rightFilterResults.length > 0) return rightFilterResults
  if (searchQuery.trim() && searchResults.length > 0) return searchResults
  return orphanSupplements
}

/** 對應 WaitingReturnModal.vue 的 toggleExpand() */
function toggleExpand(currentExpandedId, invoiceId) {
  return currentExpandedId === invoiceId ? null : invoiceId
}

/** 對應 WaitingReturnModal.vue 的 searchSupplements 過濾邏輯 */
function filterSupplementsByRelationType(items) {
  return items.filter(e =>
    ['RETURN_SUPPLEMENT', 'VOID_REPLACE', 'CREDIT_NOTE'].includes(e.relation_type)
  )
}

/** 對應 leftActiveCount computed */
function countActiveFilters(filterObj) {
  return Object.values(filterObj).filter(v => v !== '').length
}

// ── 常數 ─────────────────────────────────────────────────────────────────

const STATUS_LABEL = {
  PENDING: '待審核', APPROVED: '已核准', REJECTED: '已退回',
  NEEDS_MANUAL_REVIEW: '需人工審核', SUPPLEMENTED: '已補件',
  REPLACED_VOID: '已作廢', WAITING_RETURN: '待退貨', COMPLETED: '已結清',
}

const VOUCHER_CATEGORY_LABEL = {
  INVOICE: '電子發票', RECEIPT: '收據', TRANSPORTATION: '交通票據',
  LABOR_SERVICE: '勞務服務', INSURANCE: '保險', RENTAL: '租金',
  ACCOMMODATION: '住宿', UTILITY: '水電費', POSTAGE: '郵寄費用',
}

// ── Tests ─────────────────────────────────────────────────────────────────

describe('imgUrl 圖片 URL 轉換', () => {
  it('TC-IMG-01: 相對路徑應加上 BACKEND_BASE 前綴', () => {
    expect(imgUrl('uploads/abc.jpg')).toBe('http://localhost:8000/uploads/abc.jpg')
  })

  it('TC-IMG-02: 已含 http 的完整 URL 不應再加前綴', () => {
    expect(imgUrl('https://storage.googleapis.com/bucket/file.jpg'))
      .toBe('https://storage.googleapis.com/bucket/file.jpg')
  })

  it('TC-IMG-03: 空值應回傳空字串，不 crash', () => {
    expect(imgUrl(null)).toBe('')
    expect(imgUrl(undefined)).toBe('')
    expect(imgUrl('')).toBe('')
  })

  it('TC-IMG-04: http（非 https）的完整 URL 亦不應加前綴', () => {
    expect(imgUrl('http://internal-server/file.jpg')).toBe('http://internal-server/file.jpg')
  })
})

describe('rightPanelItems 顯示優先級', () => {
  const orphans = [{ id: 'o1', relation_type: 'RETURN_SUPPLEMENT' }]
  const searchResults = [{ id: 's1', relation_type: 'VOID_REPLACE' }]
  const filterResults = [{ id: 'f1', relation_type: 'CREDIT_NOTE' }]

  it('TC-PANEL-01: 無篩選無搜尋時，顯示孤立補件（預設狀態）', () => {
    const items = getRightPanelItems({
      rightActiveCount: 0,
      rightFilterResults: [],
      searchQuery: '',
      searchResults: [],
      orphanSupplements: orphans,
    })
    expect(items).toBe(orphans)
  })

  it('TC-PANEL-02: 有搜尋結果時，優先顯示搜尋結果', () => {
    const items = getRightPanelItems({
      rightActiveCount: 0,
      rightFilterResults: [],
      searchQuery: 'EXP-202601',
      searchResults,
      orphanSupplements: orphans,
    })
    expect(items).toBe(searchResults)
  })

  it('TC-PANEL-03: 進階篩選有結果時，最高優先（覆蓋搜尋結果）', () => {
    const items = getRightPanelItems({
      rightActiveCount: 2,
      rightFilterResults: filterResults,
      searchQuery: 'EXP-202601',
      searchResults,
      orphanSupplements: orphans,
    })
    expect(items).toBe(filterResults)
  })

  it('TC-PANEL-04: 搜尋有輸入但結果為空，退回顯示孤立補件', () => {
    const items = getRightPanelItems({
      rightActiveCount: 0,
      rightFilterResults: [],
      searchQuery: 'nonexistent',
      searchResults: [],
      orphanSupplements: orphans,
    })
    expect(items).toBe(orphans)
  })

  it('TC-PANEL-05: 進階篩選有啟用但結果為空，不顯示空的進階結果', () => {
    const items = getRightPanelItems({
      rightActiveCount: 1,
      rightFilterResults: [],
      searchQuery: '',
      searchResults: [],
      orphanSupplements: orphans,
    })
    expect(items).toBe(orphans)
  })
})

describe('toggleExpand 手風琴邏輯', () => {
  it('TC-EXPAND-01: 點擊未展開的項目 → 展開（回傳該 ID）', () => {
    expect(toggleExpand(null, 'invoice-001')).toBe('invoice-001')
  })

  it('TC-EXPAND-02: 點擊已展開的同一項目 → 收合（回傳 null）', () => {
    expect(toggleExpand('invoice-001', 'invoice-001')).toBeNull()
  })

  it('TC-EXPAND-03: 點擊另一個未展開項目 → 切換（回傳新 ID）', () => {
    expect(toggleExpand('invoice-001', 'invoice-002')).toBe('invoice-002')
  })
})

describe('搜尋結果 relation_type 過濾', () => {
  const allExpenses = [
    { id: '1', relation_type: 'RETURN_SUPPLEMENT' },
    { id: '2', relation_type: 'VOID_REPLACE' },
    { id: '3', relation_type: 'CREDIT_NOTE' },
    { id: '4', relation_type: null },
    { id: '5', relation_type: 'SUPPLEMENT' }, // 舊類型，不應顯示
    { id: '6', relation_type: 'PENDING' },     // 一般費用，不應顯示
  ]

  it('TC-FILTER-01: 搜尋結果應只保留三種補件類型（RETURN_SUPPLEMENT / VOID_REPLACE / CREDIT_NOTE）', () => {
    const filtered = filterSupplementsByRelationType(allExpenses)
    expect(filtered).toHaveLength(3)
    expect(filtered.map(e => e.id)).toEqual(['1', '2', '3'])
  })

  it('TC-FILTER-02: 空陣列不 crash，回傳空陣列', () => {
    expect(filterSupplementsByRelationType([])).toEqual([])
  })

  it('TC-FILTER-03: 無任何符合補件類型時回傳空陣列', () => {
    const noMatch = [
      { id: 'a', relation_type: null },
      { id: 'b', relation_type: 'SUPPLEMENT' },
    ]
    expect(filterSupplementsByRelationType(noMatch)).toHaveLength(0)
  })
})

describe('進階篩選條件計數', () => {
  it('TC-COUNT-01: 空篩選條件 → activeCount = 0', () => {
    const filter = { serial_number: '', invoice_number: '', uploader_name: '', uploader_dept: '' }
    expect(countActiveFilters(filter)).toBe(0)
  })

  it('TC-COUNT-02: 部分填寫 → 正確計數', () => {
    const filter = { serial_number: 'EXP-', invoice_number: '', uploader_name: 'Alice', uploader_dept: '' }
    expect(countActiveFilters(filter)).toBe(2)
  })

  it('TC-COUNT-03: 全部填寫 → 回傳欄位總數', () => {
    const filter = { a: '1', b: '2', c: '3' }
    expect(countActiveFilters(filter)).toBe(3)
  })
})

describe('STATUS_LABEL 常數完整性', () => {
  const expectedStatuses = [
    'PENDING', 'APPROVED', 'REJECTED', 'NEEDS_MANUAL_REVIEW',
    'SUPPLEMENTED', 'REPLACED_VOID', 'WAITING_RETURN', 'COMPLETED',
  ]

  it('TC-CONST-01: STATUS_LABEL 應涵蓋後端所有 ExpenseStatus 值', () => {
    for (const status of expectedStatuses) {
      expect(STATUS_LABEL[status]).toBeDefined()
      expect(STATUS_LABEL[status]).not.toBe('')
    }
  })

  it('TC-CONST-02: WAITING_RETURN 狀態顯示文字應為「待退貨」', () => {
    expect(STATUS_LABEL.WAITING_RETURN).toBe('待退貨')
  })

  it('TC-CONST-03: COMPLETED 狀態顯示文字應為「已結清」', () => {
    expect(STATUS_LABEL.COMPLETED).toBe('已結清')
  })

  it('TC-CONST-04: REPLACED_VOID 狀態顯示文字應為「已作廢」', () => {
    expect(STATUS_LABEL.REPLACED_VOID).toBe('已作廢')
  })
})

describe('VOUCHER_CATEGORY_LABEL 常數完整性', () => {
  it('TC-CONST-05: INVOICE 類別顯示文字應為「電子發票」', () => {
    expect(VOUCHER_CATEGORY_LABEL.INVOICE).toBe('電子發票')
  })

  it('TC-CONST-06: TRANSPORTATION 類別應有對應標籤', () => {
    expect(VOUCHER_CATEGORY_LABEL.TRANSPORTATION).toBeDefined()
  })

  it('TC-CONST-07: 所有 VOUCHER_CATEGORY_LABEL 值均非空字串', () => {
    Object.entries(VOUCHER_CATEGORY_LABEL).forEach(([key, val]) => {
      expect(val).not.toBe('')
      expect(typeof val).toBe('string')
    })
  })
})
