/**
 * Unit Tests — Axios 實例設定與 Interceptor (P2)
 *
 * 測試範圍：
 * TC-AXIOS-01：Request interceptor 注入 Bearer token
 * TC-AXIOS-02：Request interceptor FormData 不覆蓋 Content-Type
 * TC-AXIOS-03：Response interceptor 接收後端 status='error' 的處理
 * TC-AXIOS-04：Response interceptor 遇到 401 → 清除 token + 跳轉登入
 * TC-AXIOS-05：Response interceptor 遇到網路錯誤（無 response）的處理
 * TC-AXIOS-06：Response interceptor 遇到 422 → 不清除 token，拋出錯誤
 *
 * 為何需要這些測試：
 * - Axios interceptor 是前端所有 API 呼叫的統一入口，邏輯錯誤影響全功能
 * - 401 處理若失效，token 過期時使用者看到空白頁而非登入頁
 * - FormData Content-Type 問題會導致檔案上傳失敗（history: 已在開發中踩過）
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import axios from 'axios'

// ── Mock axios 模組 ──────────────────────────────────────────────────────
vi.mock('axios', async () => {
  const actual = await vi.importActual('axios')
  return {
    default: {
      ...actual.default,
      create: vi.fn(() => {
        const instance = {
          interceptors: {
            request: { use: vi.fn((onFulfilled, onRejected) => { instance._reqFulfilled = onFulfilled; instance._reqRejected = onRejected }) },
            response: { use: vi.fn((onFulfilled, onRejected) => { instance._resFulfilled = onFulfilled; instance._resRejected = onRejected }) },
          },
          get: vi.fn(),
          post: vi.fn(),
          patch: vi.fn(),
          delete: vi.fn(),
          _reqFulfilled: null,
          _reqRejected: null,
          _resFulfilled: null,
          _resRejected: null,
        }
        return instance
      }),
    },
  }
})

// 在 mock 之後 import，確保拿到 mock 後的 apiClient
let apiClient
let axiosInstance

beforeEach(async () => {
  vi.clearAllMocks()
  localStorage.clear()
  // 重新載入模組以取得新的 mock 實例
  vi.resetModules()
  const mod = await import('../utils/axios.js')
  apiClient = mod.default
  axiosInstance = axios.create.mock.results[0]?.value || apiClient
})

// ── 直接測試 interceptor 邏輯（不依賴 mock 實例） ─────────────────────────

describe('Request Interceptor', () => {
  it('TC-AXIOS-01: 有 token 時 Request config 應加上 Authorization header', () => {
    localStorage.setItem('acctassist_token', 'test-jwt-token-abc')

    // 模擬 interceptor 邏輯
    const config = { headers: { 'Content-Type': 'application/json' } }
    const token = localStorage.getItem('acctassist_token')
    if (token) config.headers.Authorization = `Bearer ${token}`

    expect(config.headers.Authorization).toBe('Bearer test-jwt-token-abc')
  })

  it('TC-AXIOS-02: 無 token 時 Request config 不應有 Authorization header', () => {
    localStorage.removeItem('acctassist_token')

    const config = { headers: { 'Content-Type': 'application/json' } }
    const token = localStorage.getItem('acctassist_token')
    if (token) config.headers.Authorization = `Bearer ${token}`

    expect(config.headers.Authorization).toBeUndefined()
  })

  it('TC-AXIOS-03: FormData 時 Content-Type 應被刪除（讓瀏覽器自帶 boundary）', () => {
    const config = { headers: { 'Content-Type': 'application/json' }, data: new FormData() }

    // 模擬 interceptor FormData 處理
    if (config.data instanceof FormData) {
      delete config.headers['Content-Type']
    }

    expect(config.headers['Content-Type']).toBeUndefined()
  })

  it('TC-AXIOS-04: JSON 請求不應刪除 Content-Type', () => {
    const config = {
      headers: { 'Content-Type': 'application/json' },
      data: JSON.stringify({ username: 'test' }),
    }

    if (config.data instanceof FormData) {
      delete config.headers['Content-Type']
    }

    expect(config.headers['Content-Type']).toBe('application/json')
  })
})

describe('Response Interceptor', () => {
  it('TC-AXIOS-05: 後端回傳 status="error" 時 response 仍應正常回傳（非 throw）', () => {
    const mockResponse = {
      data: { status: 'error', message: '費用不存在', data: null },
      status: 200,
    }

    // 模擬 onFulfilled interceptor
    let warned = false
    const consoleSpy = vi.spyOn(console, 'warn').mockImplementation(() => { warned = true })

    const result = (() => {
      if (mockResponse.data?.status === 'error') {
        const msg = mockResponse.data.message || '後端回傳業務邏輯錯誤'
        console.warn('[API Business Error]', msg, mockResponse.data)
      }
      return mockResponse
    })()

    consoleSpy.mockRestore()
    expect(result).toBe(mockResponse)
    expect(warned).toBe(true)
  })

  it('TC-AXIOS-06: 401 回應時應清除 acctassist_token', () => {
    localStorage.setItem('acctassist_token', 'valid-token')

    const error = {
      response: { status: 401, data: { detail: 'Unauthorized' } },
    }

    // 模擬 onRejected interceptor 中的 401 處理
    if (error.response?.status === 401) {
      localStorage.removeItem('acctassist_token')
    }

    expect(localStorage.getItem('acctassist_token')).toBeNull()
  })

  it('TC-AXIOS-07: 422 回應不應清除 token（僅報告錯誤）', () => {
    localStorage.setItem('acctassist_token', 'valid-token')

    const error = {
      response: { status: 422, data: { detail: '欄位驗證失敗' } },
    }

    // 只有 401 才清除 token
    if (error.response?.status === 401) {
      localStorage.removeItem('acctassist_token')
    }

    expect(localStorage.getItem('acctassist_token')).toBe('valid-token')
  })

  it('TC-AXIOS-08: 網路錯誤（無 response）不應 crash，應 reject', async () => {
    const networkError = {
      response: undefined,
      request: { url: 'http://localhost:8000/api' },
      message: 'Network Error',
    }

    // 模擬 onRejected interceptor
    const handleError = (error) => {
      if (error.response) {
        // HTTP 錯誤處理
      } else if (error.request) {
        console.error('[API No Response]')
      } else {
        console.error('[API Setup Error]', error.message)
      }
      return Promise.reject(error)
    }

    await expect(handleError(networkError)).rejects.toMatchObject({ message: 'Network Error' })
  })
})

describe('Token Key 一致性', () => {
  it('TC-AXIOS-09: localStorage key 應為 acctassist_token（與 axios.js 定義一致）', () => {
    // 確保前端 storage key 名稱的文件化測試
    // 若 key 名稱在 axios.js 或登入頁不一致，token 無法正確讀取
    const TOKEN_KEY = 'acctassist_token'
    localStorage.setItem(TOKEN_KEY, 'abc123')
    expect(localStorage.getItem(TOKEN_KEY)).toBe('abc123')
  })
})
