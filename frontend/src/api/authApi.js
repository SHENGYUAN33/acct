import apiClient from '../utils/axios'

/**
 * POST /api/v1/auth/login
 * 帳號密碼登入，回傳 { access_token, token_type }
 * 使用 URLSearchParams 符合 OAuth2PasswordRequestForm 格式（application/x-www-form-urlencoded）
 */
export const login = (username, password) => {
  const form = new URLSearchParams()
  form.append('username', username)
  form.append('password', password)
  return apiClient.post('/api/v1/auth/login', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
}

/**
 * GET /api/v1/auth/project-info
 * 取得系統設定（如統一編號），需 JWT
 */
export const getProjectInfo = () =>
  apiClient.get('/api/v1/auth/project-info')

/**
 * POST /api/v1/auth/register
 * 建立新管理員帳號，回傳 { username, display_name, employee_id }
 */
export const register = (username, password, displayName, employeeId) =>
  apiClient.post('/api/v1/auth/register', {
    username,
    password,
    display_name: displayName || null,
    employee_id:  employeeId  || null,
  })
