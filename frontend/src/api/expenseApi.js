import apiClient from '../utils/axios'

/**
 * GET /api/v1/expenses
 * @param {Object} params - { status, date_from, date_to, page, page_size }
 */
export const fetchExpenses = (params = {}) =>
  apiClient.get('/api/v1/expenses', { params })

/**
 * GET /api/v1/expenses/{id}
 * @param {string} id - Expense UUID
 */
export const getExpense = (id) =>
  apiClient.get(`/api/v1/expenses/${id}`)

/**
 * PATCH /api/v1/expenses/{id}
 * 部分更新 Expense 欄位（Dashboard 審核表單儲存用）
 * @param {string} id - Expense UUID
 * @param {Object} payload - ExpenseUpdate 欄位（全部可選）
 */
export const updateExpense = (id, payload) =>
  apiClient.patch(`/api/v1/expenses/${id}`, payload)

/**
 * POST /api/v1/expenses
 * Dashboard 手動新增費用
 */
export const createExpense = (payload) =>
  apiClient.post('/api/v1/expenses', payload)

/**
 * DELETE /api/v1/expenses/{id}
 * 刪除單筆費用
 */
export const deleteExpense = (id) =>
  apiClient.delete(`/api/v1/expenses/${id}`)

/**
 * GET /api/v1/expenses/export
 * 匯出 CSV（responseType blob 讓 Axios 以二進位接收）
 */
export const exportExpenses = (params = {}) =>
  apiClient.get('/api/v1/expenses/export', { params, responseType: 'blob' })

/**
 * POST /api/v1/expenses/{id}/images
 * 追加補件圖片至陣列末尾（multipart/form-data）
 * @param {string} id - Expense UUID
 * @param {File} file - 圖片檔案
 * @param {'expense'|'item'} imageType - 圖片類型
 */
export const uploadImage = (id, file, imageType) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('image_type', imageType)
  return apiClient.post(`/api/v1/expenses/${id}/images`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/**
 * PATCH /api/v1/expenses/reorder
 * 持久化拖曳排序：傳入完整排列後的 ID 陣列，後端依序寫入 display_order
 * @param {string[]} orderedIds - 排序後的 expense ID 陣列
 */
export const reorderExpenses = (orderedIds) =>
  apiClient.patch('/api/v1/expenses/reorder', { ordered_ids: orderedIds })

/**
 * PATCH /api/v1/expenses/{id}/reject
 * 退回單據：將狀態更新為 REPLACED_VOID（作廢），並觸發 LINE 純文字推播（依後端開關）
 * @param {string} id - Expense UUID
 */
export const rejectExpense = (id) =>
  apiClient.patch(`/api/v1/expenses/${id}/reject`, { reason: '' })

/**
 * GET /api/v1/expenses/{id}/images
 * 取得某筆 Expense 的所有子圖片清單
 * @param {string} expenseId - Expense UUID
 * @returns {{ status, data: { expense_id, images: Array }, message }}
 */
export const fetchExpenseImages = (expenseId) =>
  apiClient.get(`/api/v1/expenses/${expenseId}/images`)

/**
 * POST /api/v1/expenses/{id}/reocr
 * 重新對費用第一張影像執行 OCR，將辨識結果更新至 DB 並回傳更新後的 Expense
 * @param {string} id - Expense UUID
 * @note 覆寫 timeout 為 120s：Gemini OCR + 最多 3 次重試可能需要 30–90 秒，
 *       超過全域預設 15s 會導致請求被提前中斷（顯示「辨識失敗」）。
 */
export const reOcrExpense = (id) =>
  apiClient.post(`/api/v1/expenses/${id}/reocr`, undefined, { timeout: 120000 })

/**
 * POST /api/v1/admin/process-pending
 * 立即觸發所有 pending 圖片的批次 OCR 處理（不等待排程時間）
 * 端點立即回傳，實際處理在後端背景執行
 */
export const processPendingNow = () =>
  apiClient.post('/api/v1/admin/process-pending')

/**
 * GET /api/v1/admin/scheduler-config
 * 取得目前排程設定（enabled, times, timezone, scheduled_jobs）
 */
export const getSchedulerConfig = () =>
  apiClient.get('/api/v1/admin/scheduler-config')

/**
 * PATCH /api/v1/admin/scheduler-config
 * 更新排程設定，立即生效並持久化至 DB
 * @param {{ enabled: boolean, times: string[], timezone: string }} payload
 */
export const updateSchedulerConfig = (payload) =>
  apiClient.patch('/api/v1/admin/scheduler-config', payload)

/**
 * POST /api/v1/expenses/{id}/images/replace
 * 替換陣列中指定索引的圖片（multipart/form-data）
 * @param {string} id - Expense UUID
 * @param {File} file - 圖片檔案
 * @param {'expense'|'item'} imageType - 圖片類型
 * @param {number} index - 要替換的陣列索引（從 0 開始）
 */
export const replaceImage = (id, file, imageType, index) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('image_type', imageType)
  formData.append('index', index)
  return apiClient.post(`/api/v1/expenses/${id}/images/replace`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
