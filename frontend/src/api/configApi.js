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
