import apiClient from '../utils/axios'

/**
 * GET /api/v1/config/departments
 * 取得系統組別清單（公開端點，不需 JWT）
 * @returns {Promise<string[]>} 組別名稱陣列
 */
export const fetchDepartments = () =>
  apiClient.get('/api/v1/config/departments')

/**
 * GET /api/v1/config/account-roles
 * 取得系統帳號角色清單（公開端點，不需 JWT）
 * @returns {Promise<string[]>} 角色名稱陣列
 */
export const fetchAccountRoles = () =>
  apiClient.get('/api/v1/config/account-roles')

/**
 * GET /api/v1/config/expense-categories
 * 取得費用科目平面清單（公開端點，不需 JWT）
 * @returns {Promise<{categories: Array}>} 科目陣列，每項含 key/label
 */
export const fetchExpenseCategories = () =>
  apiClient.get('/api/v1/config/expense-categories')

/**
 * GET /api/v1/config/voucher-categories
 * 取得憑證類別清單（公開端點，不需 JWT）
 * @returns {Promise<{voucher_categories: Array}>} 憑證類別陣列，每項含 key/label
 */
export const fetchVoucherCategories = () =>
  apiClient.get('/api/v1/config/voucher-categories')
