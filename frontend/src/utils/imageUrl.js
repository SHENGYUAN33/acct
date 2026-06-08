import { API_BASE_URL } from './axios'

/**
 * 將後端圖片路徑轉換為帶 JWT 的完整認證 URL。
 *
 * 接受兩種輸入：
 *   - 相對路徑：「uploads/uuid.jpg」（直接來自 API 回應）
 *   - 完整 URL：「https://backend/uploads/uuid.jpg」（已被其他地方組過一次的舊格式）
 *
 * 輸出：「https://backend/api/v1/uploads/uuid.jpg?token=<jwt>」
 *
 * <img :src="secureImgUrl(url)"> 可直接使用，token 放在 query param
 * 因為瀏覽器的 <img> 標籤不支援帶 Authorization header。
 */
export function secureImgUrl(url) {
  if (!url) return ''

  let filename = ''

  if (url.startsWith('http')) {
    // 已是完整 URL：只處理本站舊格式 /uploads/...，外部 URL 原樣回傳
    const oldPrefix = `${API_BASE_URL}/uploads/`
    if (!url.startsWith(oldPrefix)) return url
    filename = url.slice(oldPrefix.length)
  } else {
    // 相對路徑：「uploads/uuid.jpg」或「./uploads/uuid.jpg」
    filename = url.replace(/^\.?\/?(uploads\/)/, '')
  }

  const base = `${API_BASE_URL}/api/v1/uploads/${filename}`
  const token = localStorage.getItem('acctassist_token')
  return token ? `${base}?token=${encodeURIComponent(token)}` : base
}
