import { API_BASE_URL } from './axios'

/**
 * 將後端檔案路徑轉換為帶 JWT 的完整認證 URL。
 *
 * 只取路徑最後一個片段（檔名），相容所有格式：
 *   - 「uploads/uuid.jpg」         → uuid.jpg
 *   - 「./uploads/uuid.pdf」       → uuid.pdf
 *   - 「https://host/uploads/uuid.png」 → uuid.png
 *
 * 輸出：「https://backend/api/v1/uploads/uuid.ext?token=<jwt>」
 */
export function secureImgUrl(url) {
  if (!url) return ''
  const filename = url.replace(/\\/g, '/').split('/').pop()
  if (!filename) return ''
  const base = `${API_BASE_URL}/api/v1/uploads/${filename}`
  const token = localStorage.getItem('acctassist_token')
  return token ? `${base}?token=${encodeURIComponent(token)}` : base
}

// 瀏覽器原生可在 <img> 標籤顯示的格式
const _IMG_EXTS = new Set(['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'])

/**
 * 判斷此 URL 是否可直接用 <img> 標籤顯示。
 * PDF、TIFF 等格式回傳 false，前端應改用連結或 iframe。
 */
export function isViewableImage(url) {
  if (!url) return false
  const ext = url.toLowerCase().split('?')[0].split('.').pop()
  return _IMG_EXTS.has(ext)
}

/**
 * 取得檔案的顯示類型，供前端決定渲染方式。
 * @returns {'image' | 'pdf' | 'file'}
 */
export function getFileType(url) {
  if (!url) return 'file'
  const ext = url.toLowerCase().split('?')[0].split('.').pop()
  if (_IMG_EXTS.has(ext)) return 'image'
  if (ext === 'pdf') return 'pdf'
  return 'file'
}
