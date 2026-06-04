import axios from 'axios'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

// ── Axios 實例設定 ────────────────────────────────────────────────
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: Number(import.meta.env.VITE_API_TIMEOUT_MS) || 15000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ── Request Interceptor：注入 JWT Token + 處理 FormData Content-Type ──
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('acctassist_token')
    if (token) config.headers.Authorization = `Bearer ${token}`
    // FormData 上傳時讓瀏覽器自動帶 boundary，不可手動設 Content-Type
    if (config.data instanceof FormData) {
      delete config.headers['Content-Type']
    }
    return config
  },
  (error) => {
    console.error('[Axios Request Error]', error)
    return Promise.reject(error)
  }
)

// ── Response Interceptor（統一錯誤攔截 + Console 除錯） ───────────
apiClient.interceptors.response.use(
  (response) => {
    // 後端統一回傳格式：{ status, data, message }
    // 若後端回傳 status === 'error'，視為業務邏輯錯誤
    if (response.data?.status === 'error') {
      const msg = response.data.message || '後端回傳業務邏輯錯誤'
      console.warn('[API Business Error]', msg, response.data)
    }
    return response
  },
  (error) => {
    if (error.response) {
      const { status, data } = error.response
      // 401 → 清除 token 並跳轉登入頁
      if (status === 401) {
        localStorage.removeItem('acctassist_token')
        if (window.location.pathname !== '/login') {
          window.location.href = '/login'
        }
        return Promise.reject(error)
      }
      console.error(`[API HTTP ${status}]`, data?.detail || data?.message || error.message)
    } else if (error.request) {
      // 請求送出但沒有收到回應（後端未啟動或 CORS 問題）
      console.error(`[API No Response] 後端可能未啟動，請確認 ${API_BASE_URL} 是否運行中`)
    } else {
      console.error('[API Setup Error]', error.message)
    }
    return Promise.reject(error)
  }
)

export default apiClient
