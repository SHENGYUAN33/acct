import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchExpenses as apiFetchExpenses,
  updateExpense as apiUpdateExpense,
  createExpense as apiCreateExpense,
  deleteExpense as apiDeleteExpense,
  exportExpenses as apiExportExpenses,
  uploadImage as apiUploadImage,
  replaceImage as apiReplaceImage,
  rejectExpense as apiRejectExpense,
  reOcrExpense as apiReOcrExpense,
  reorderExpenses as apiReorderExpenses,
} from '../api/expenseApi'

import { secureImgUrl } from '../utils/imageUrl'
import { getVoucherLabel } from '../constants/voucher.js'

/**
 * 將後端 Expense 物件 map 成前端所需的完整 shape
 * （補上後端尚未支援的前端欄位預設值）
 */
function mapExpense(item, index) {
  // 解析 voucher_categories（後端可能回傳 JSON 字串或陣列或 null）
  const voucherCategories = item.voucher_categories
    ? (typeof item.voucher_categories === 'string'
        ? JSON.parse(item.voucher_categories)
        : item.voucher_categories)
    : null

  return {
    ...item,
    // 顯示用流水號（以 created_at 排序後的順序，index 由父層傳入）
    serial: index + 1,
    // 拼接後端靜態檔案 URL（ARRAY → 每個元素加 baseURL，已含 http 則不重複拼接）
    image_url: (item.image_url || []).map(secureImgUrl),
    item_image_url: (item.item_image_url || []).map(secureImgUrl),
    // 後端尚未支援的前端欄位（預設值）
    is_asset: item.is_asset ?? false,
    return_original_data: item.return_original_data ?? '',
    // Sprint 2 新增欄位
    // voucher_categories：已 parse 的陣列，供表格直接顯示中文標籤
    voucher_categories: voucherCategories
      ? voucherCategories.map(cat => getVoucherLabel(cat))
      : null,
    // certificate_type：沿用舊欄位（取第一項中文，供 AuditModal 等處顯示）
    certificate_type: voucherCategories?.[0]
      ? getVoucherLabel(voucherCategories[0])
      : (item.certificate_type ?? null),
    user_description: item.user_description ?? null,
    image_count: item.image_count ?? 1,
    // Sprint 3 — 觸發來源（'manual_button' | 'auto_split' | null 表示舊資料）
    trigger_by: item.trigger_by ?? null,
  }
}

export const useExpenseStore = defineStore('expense', () => {
  // ── 狀態 ────────────────────────────────────────────────────
  const expenses = ref([])

  // API 載入狀態
  const isLoading = ref(false)
  const error = ref(null)

  // 後端分頁資訊
  const totalCount = ref(0)

  // 篩選條件
  const filters = ref({
    checkStatus: '',
    dept: '',
    category: '',   // 憑證類別中文標籤（client-side）
    status: '',     // 審核狀態（server-side）
    q: '',          // 搜尋關鍵字：案件編號/上傳者（server-side）
    dateFrom: '',
    dateTo: '',
    submitter: '',
  })

  // 分頁
  const currentPage = ref(1)
  const pageSize = ref(Number(import.meta.env.VITE_DEFAULT_PAGE_SIZE) || 100)

  // 勾選狀態（用 Set 儲存已勾選的 expense id）
  const checkedIds = ref(new Set())

  // 審核 Modal
  const selectedExpense = ref(null)
  const isAuditModalOpen = ref(false)

  // 重複憑證篩選
  const hasDuplicateFilter = ref(false)

  function toggleDuplicateFilter() {
    hasDuplicateFilter.value = !hasDuplicateFilter.value
    currentPage.value = 1
    fetchExpenses()
  }

  // ── Getters ──────────────────────────────────────────────────
  const filteredExpenses = computed(() => {
    return expenses.value.filter((e) => {
      // 勾選狀態篩選（client-side）
      if (filters.value.checkStatus === 'checked' && !checkedIds.value.has(e.id)) return false
      if (filters.value.checkStatus === 'unchecked' && checkedIds.value.has(e.id)) return false
      // 組別與憑證類別已改為 server-side 查詢，此處不再過濾
      // 費用提報者篩選（client-side fallback）
      if (
        filters.value.submitter &&
        !e.submitter_name?.includes(filters.value.submitter) &&
        !e.uploader_name?.includes(filters.value.submitter)
      ) return false
      return true
    })
  })

  const paginatedExpenses = computed(() => {
    const start = (currentPage.value - 1) * pageSize.value
    return filteredExpenses.value.slice(start, start + pageSize.value)
  })

  // 當前頁是否全勾選（需在 paginatedExpenses 後定義）
  const allChecked = computed(() => {
    return paginatedExpenses.value.length > 0 &&
      paginatedExpenses.value.every((e) => checkedIds.value.has(e.id))
  })

  const totalPages = computed(() =>
    Math.max(1, Math.ceil(filteredExpenses.value.length / pageSize.value))
  )

  // 統計卡片資料（從目前 expenses 計算）
  const stats = computed(() => {
    const pending = expenses.value.filter((e) => e.status === 'PENDING' || e.status === 'NEEDS_MANUAL_REVIEW')
    return {
      dateRange: `${filters.value.dateFrom || '-'} ~ ${filters.value.dateTo || '-'}`,
      hasPendingReview: pending.length > 0,
      totalUploaders: new Set(expenses.value.map((e) => e.uploader_name).filter(Boolean)).size,
      totalExpenses: expenses.value.length,
      totalImages: expenses.value.filter((e) => e.image_url && e.image_url.length > 0).length,
    }
  })

  // ── Actions ──────────────────────────────────────────────────

  function setFilter(key, value) {
    filters.value[key] = value
    currentPage.value = 1
  }

  // server-side 篩選條件變更時，重置頁碼並重新拉取資料
  async function setFilterAndFetch(key, value) {
    filters.value[key] = value
    currentPage.value = 1
    await fetchExpenses()
  }

  function resetFilters() {
    filters.value = {
      checkStatus: '',
      dept: '',
      category: '',
      status: '',
      q: '',
      dateFrom: '',
      dateTo: '',
      submitter: '',
    }
    currentPage.value = 1
    fetchExpenses()
  }

  // 切換單筆勾選（重新 assign 觸發 reactivity）
  function toggleCheck(id) {
    const next = new Set(checkedIds.value)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    checkedIds.value = next
  }

  // 全選 / 全取消（以當前分頁為範圍）
  function toggleAll() {
    if (allChecked.value) {
      checkedIds.value = new Set()
    } else {
      checkedIds.value = new Set(paginatedExpenses.value.map((e) => e.id))
    }
  }

  function setPage(page) {
    if (page >= 1 && page <= totalPages.value) {
      currentPage.value = page
    }
  }

  function setPageSize(size) {
    pageSize.value = size
    currentPage.value = 1
  }

  function openAudit(expense) {
    selectedExpense.value = { ...expense }
    isAuditModalOpen.value = true
  }

  /** Create Mode：開啟空白表單（無 id），供手動新增費用使用 */
  function openCreateModal() {
    selectedExpense.value = {}
    isAuditModalOpen.value = true
  }

  function closeAudit() {
    isAuditModalOpen.value = false
    selectedExpense.value = null
  }

  /**
   * 從後端拉取報帳清單，替換 expenses state
   * @param {Object} extraParams - 額外的查詢參數（如 status 過濾）
   */
  async function fetchExpenses(extraParams = {}) {
    isLoading.value = true
    error.value = null
    try {
      const params = {
        page: currentPage.value,
        page_size: pageSize.value,
        ...(hasDuplicateFilter.value ? { has_duplicate: true } : {}),
        ...(filters.value.status ? { status: filters.value.status } : {}),
        // 全部狀態或明確篩選已作廢時，都帶 include_inactive 讓 is_active=False 記錄可見
        ...(!filters.value.status || filters.value.status === 'REPLACED_VOID' ? { include_inactive: true } : {}),
        ...(filters.value.dateFrom ? { date_from: filters.value.dateFrom } : {}),
        ...(filters.value.dateTo
          ? { date_to: filters.value.dateTo }
          : filters.value.dateFrom
            ? { date_to: new Date().toISOString().split('T')[0] }
            : {}),
        ...(filters.value.q ? { q: filters.value.q } : {}),
        ...(filters.value.dept ? { uploader_dept_q: filters.value.dept } : {}),
        ...(filters.value.category ? { voucher_category_q: filters.value.category } : {}),
        ...extraParams,
      }
      const res = await apiFetchExpenses(params)
      const { items, total } = res.data.data
      expenses.value = items.map((item, index) => mapExpense(item, index))
      totalCount.value = total
    } catch (err) {
      error.value = '無法載入資料，請確認後端服務是否啟動'
      console.error('[Store] fetchExpenses 失敗：', err)
    } finally {
      isLoading.value = false
    }
  }

  /**
   * 儲存審核表單資料（PATCH），並可選擇性地核准（approve=true 時附帶 status=APPROVED）
   * @param {string} id - Expense UUID
   * @param {Object} formData - AuditModal 表單資料
   * @param {boolean} approve - 是否同時核准
   */
  async function saveExpense(id, formData, approve = false) {
    // 只送後端支援的欄位（排除前端專用欄位）
    const payload = {
      submitter_name: formData.submitter_name || null,
      submitter_dept: formData.submitter_dept || null,
      expense_date: formData.expense_date || null,
      invoice_number: formData.invoice_number || null,
      total_amount: formData.total_amount !== '' ? formData.total_amount : null,
      net_amount: formData.net_amount !== '' ? formData.net_amount : null,
      tax_amount: formData.tax_amount !== '' ? formData.tax_amount : null,
      seller_tax_id: formData.seller_tax_id || null,
      seller_name: formData.seller_name || null,
      item_description: formData.item_description || null,
    }

    // 核准時一併帶上 status
    if (approve) {
      payload.status = 'APPROVED'
    }

    // 移除值為 null 的欄位，減少 payload 大小
    Object.keys(payload).forEach((k) => {
      if (payload[k] === null) delete payload[k]
    })

    try {
      await apiUpdateExpense(id, payload)
      closeAudit()
      // 重新拉取列表，確保狀態與後端同步
      await fetchExpenses()
    } catch (err) {
      console.error('[Store] saveExpense 失敗：', err)
      throw err  // 往上拋，讓 AuditModal 顯示錯誤提示
    }
  }

  /**
   * 手動新增費用（Create Mode）
   * @param {Object} formData - AuditModal 表單資料（無 id）
   */
  async function createExpense(formData) {
    const payload = {
      uploader_name: formData.uploader_name || null,
      uploader_dept: formData.uploader_dept || null,
      submitter_name: formData.submitter_name || null,
      submitter_dept: formData.submitter_dept || null,
      expense_date: formData.expense_date || null,
      invoice_number: formData.invoice_number || null,
      total_amount: formData.total_amount !== '' ? formData.total_amount : null,
      net_amount: formData.net_amount !== '' ? formData.net_amount : null,
      tax_amount: formData.tax_amount !== '' ? formData.tax_amount : null,
      seller_tax_id: formData.seller_tax_id || null,
      seller_name: formData.seller_name || null,
      item_description: formData.item_description || null,
    }
    // 移除 null 值
    Object.keys(payload).forEach((k) => { if (payload[k] === null) delete payload[k] })

    const res = await apiCreateExpense(payload)
    // 回傳新建的 Expense 物件，讓 AuditModal 可以拿到 UUID 接續上傳圖片
    const created = res.data.data
    await fetchExpenses()
    return created
  }

  /**
   * 刪除費用
   * @param {string} id - Expense UUID
   */
  async function deleteExpense(id) {
    await apiDeleteExpense(id)
    await fetchExpenses()
  }

  /**
   * 匯出 CSV：觸發瀏覽器下載 expenses.csv
   */
  async function downloadExport() {
    const res = await apiExportExpenses()
    const url = URL.createObjectURL(new Blob([res.data], { type: 'text/csv;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url
    a.download = 'expenses.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  /**
   * 上傳補件圖片，成功後更新 store 中對應 expense 的圖片欄位
   * @param {string} id - Expense UUID
   * @param {File} file - 圖片檔案
   * @param {'expense'|'item'} imageType
   * @returns {Object} 更新後的 expense（含新 image URL）
   */
  async function uploadImage(id, file, imageType) {
    const res = await apiUploadImage(id, file, imageType)
    const updated = res.data.data
    const field = imageType === 'expense' ? 'image_url' : 'item_image_url'
    const newUrls = (updated[field] || []).map(secureImgUrl)
    const idx = expenses.value.findIndex((e) => e.id === id)
    if (idx !== -1) expenses.value[idx][field] = newUrls
    return newUrls
  }

  async function replaceImage(id, file, imageType, index) {
    const res = await apiReplaceImage(id, file, imageType, index)
    const updated = res.data.data
    const field = imageType === 'expense' ? 'image_url' : 'item_image_url'
    const newUrls = (updated[field] || []).map(secureImgUrl)
    const idx = expenses.value.findIndex((e) => e.id === id)
    if (idx !== -1) expenses.value[idx][field] = newUrls
    return newUrls
  }

  /**
   * 退回單據：呼叫 PATCH /reject，寫入原因並觸發 LINE 推播（依後端開關）
   * 成功後刷新清單並關閉 Modal
   * @param {string} id - Expense UUID
   * @param {string} reason - 退回原因
   */
  async function rejectExpense(id) {
    await apiRejectExpense(id)
    await fetchExpenses()
    isAuditModalOpen.value = false
  }

  /**
   * 重新辨識：呼叫後端 POST /reocr，對費用第一張影像重新執行 OCR 並更新 DB。
   * 不關閉 Modal — 由 AuditModal 接收回傳值後填入 form.value。
   * @param {string} id - Expense UUID
   * @returns {Object} 更新後的 Expense 物件（原始後端格式，含 image_url 相對路徑）
   */
  async function reOcrExpense(id) {
    const res = await apiReOcrExpense(id)
    const updated = res.data.data
    // 同步更新 expenses 清單中的對應筆資料
    const idx = expenses.value.findIndex((e) => e.id === id)
    if (idx !== -1) {
      expenses.value[idx] = mapExpense(updated, idx)
    }
    return updated
  }

  /**
   * 拖曳排序：將 fromId 那列移動到 toId 那列的位置（插入至前方），
   * 同步更新前端本地陣列並呼叫後端 API 持久化完整排序。
   * @param {string} fromId - 被拖曳列的 expense.id
   * @param {string} toId   - 放置目標列的 expense.id
   */
  async function reorderExpenses(fromId, toId) {
    if (fromId === toId) return
    const list = expenses.value
    const fromIdx = list.findIndex((e) => e.id === fromId)
    const toIdx = list.findIndex((e) => e.id === toId)
    if (fromIdx === -1 || toIdx === -1) return
    // 本地即時更新（讓 UI 立刻反映）
    const [moved] = list.splice(fromIdx, 1)
    list.splice(toIdx, 0, moved)
    // 持久化：傳送完整排序後的 ID 清單給後端
    const orderedIds = list.map((e) => e.id)
    try {
      await apiReorderExpenses(orderedIds)
    } catch (e) {
      // API 失敗時還原並通知（不影響其他操作）
      list.splice(toIdx, 1)
      list.splice(fromIdx, 0, moved)
      throw e
    }
  }

  function patchExpenseInList(id, fields) {
    const idx = expenses.value.findIndex(e => e.id === id)
    if (idx !== -1) expenses.value[idx] = { ...expenses.value[idx], ...fields }
  }

  return {
    expenses,
    isLoading,
    error,
    totalCount,
    filters,
    currentPage,
    pageSize,
    selectedExpense,
    isAuditModalOpen,
    filteredExpenses,
    paginatedExpenses,
    totalPages,
    stats,
    checkedIds,
    allChecked,
    hasDuplicateFilter,
    setFilter,
    setFilterAndFetch,
    resetFilters,
    setPage,
    setPageSize,
    toggleCheck,
    toggleAll,
    openAudit,
    closeAudit,
    fetchExpenses,
    saveExpense,
    createExpense,
    deleteExpense,
    downloadExport,
    uploadImage,
    replaceImage,
    openCreateModal,
    rejectExpense,
    reOcrExpense,
    reorderExpenses,
    toggleDuplicateFilter,
    patchExpenseInList,
  }
})
