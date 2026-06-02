// Vitest 全域設定：模擬瀏覽器環境
import { vi } from 'vitest'

// 模擬 import.meta.env（Vite 環境變數在 jsdom 中不可用）
vi.stubGlobal('import', {
  meta: {
    env: {
      VITE_API_BASE_URL: 'http://localhost:8000',
      VITE_ENABLE_PROCESS_PENDING: 'false',
    },
  },
})

// 模擬 localStorage
const localStorageMock = (() => {
  let store = {}
  return {
    getItem: (key) => store[key] || null,
    setItem: (key, value) => { store[key] = String(value) },
    removeItem: (key) => { delete store[key] },
    clear: () => { store = {} },
  }
})()

Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock })
Object.defineProperty(globalThis, 'window', {
  value: {
    location: { pathname: '/', href: '' },
    localStorage: localStorageMock,
  },
  writable: true,
})
