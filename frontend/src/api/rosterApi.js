import apiClient from '../utils/axios'

/**
 * GET /api/v1/roster
 * 查詢員工名冊清單（支援分頁與綁定狀態篩選）
 * @param {Object} params - { page, size, is_bound }
 */
export const getRosterList = (params = {}) =>
  apiClient.get('/api/v1/roster', { params })

/**
 * POST /api/v1/roster
 * 新增單筆員工至名冊
 * @param {{ name: string, department: string, employee_id?: string }} data
 */
export const createRosterEntry = (data) =>
  apiClient.post('/api/v1/roster', data)

/**
 * PATCH /api/v1/roster/{id}
 * 修改員工資料（部分更新）
 * @param {string} id - Roster 員工 UUID
 * @param {{ name?: string, department?: string, employee_id?: string }} data
 */
export const updateRosterEntry = (id, data) =>
  apiClient.patch(`/api/v1/roster/${id}`, data)

/**
 * DELETE /api/v1/roster/{id}
 * 刪除員工（已綁定者後端會回傳 400）
 * @param {string} id - Roster 員工 UUID
 */
export const deleteRosterEntry = (id) =>
  apiClient.delete(`/api/v1/roster/${id}`)

/**
 * POST /api/v1/roster/import
 * CSV 批次匯入員工名冊（multipart/form-data）
 * 不手動設定 Content-Type，讓瀏覽器自動帶入 boundary
 * @param {File} file - .csv 檔案
 */
export const importRosterCSV = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return apiClient.post('/api/v1/roster/import', formData)
}

/**
 * POST /api/v1/roster/{id}/unbind
 * 解除員工的 LINE 帳號綁定
 * @param {string} id - Roster 員工 UUID
 */
export const unbindRosterEntry = (id) =>
  apiClient.post(`/api/v1/roster/${id}/unbind`)

/**
 * GET /api/v1/roster/export
 * 匯出現有員工名冊為 CSV 並觸發下載
 */
export const exportRosterCSV = async () => {
  const res = await apiClient.get('/api/v1/roster/export', { responseType: 'blob' })
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url
  a.download = 'roster_export.csv'
  a.click()
  URL.revokeObjectURL(url)
}

/**
 * 下載 CSV 樣板（前端本地產生，不需後端）
 * 產生含範例資料的 CSV 並觸發瀏覽器下載
 */
export const downloadRosterTemplate = () => {
  const content = [
    'name,department,line_id,account_role,line_name,email,is_petty_cash_target,bank_account',
    '王小明,製片組,,一般員工,王小明LINE,wangxm@example.com,false,',
    '李小華,攝影組,,管理員,,lixh@example.com,true,123456789',
  ].join('\n')

  // 加 BOM 確保 Excel 正確顯示中文
  const bom = '﻿'
  const blob = new Blob([bom + content], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'roster_template.csv'
  a.click()
  URL.revokeObjectURL(url)
}
