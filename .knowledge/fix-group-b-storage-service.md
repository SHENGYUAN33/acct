# 組別 B 修復紀錄：統一圖片儲存入口

**修改日期**：2026-06-08  
**涉及檔案**：`services/storage_service.py`（新增）、`routers/expenses.py`、`services/liff_service.py`、`routers/liff.py`  
**關聯問題**：1.4（上傳路徑不一致）、2.1（儲存邏輯重複）

---

## 為什麼要改

### 問題 1.4：三個地方各自決定圖片存放路徑，行為不一致

| 位置 | 路徑基底 | 儲存後回傳的相對路徑 |
|------|---------|------------------|
| `routers/expenses.py:upload_expense_image` | `Path("uploads")` 硬編碼 | `uploads/{filename}` |
| `routers/expenses.py:replace_expense_image` | `Path("uploads")` 硬編碼 | `uploads/{filename}` |
| `services/liff_service.save_uploaded_file` | `settings.storage_path` | `{storage_path}/{filename}`（含完整路徑！） |

`liff_service` 回傳的是 `str(dest)`，若 `STORAGE_PATH=./uploads`，
實際回傳 `"uploads/uuid.jpg"`，但若 `STORAGE_PATH=/data/uploads`，
就會回傳 `/data/uploads/uuid.jpg`，存進 DB 後前端拼不出正確 URL。

`expenses.py` 硬編碼 `"uploads/"` 則不管 `STORAGE_PATH` 設什麼都不理會。

### 問題 2.1：20 行相同的儲存邏輯在 expenses.py 複製了兩次

`upload_expense_image` 和 `replace_expense_image` 各有：
1. MIME 類型檢查
2. 副檔名提取
3. UUID 檔名生成
4. 大小檢查
5. 磁碟寫入
6. 例外處理

邏輯完全相同，但 `liff_service.save_uploaded_file` 只有 4 行，
**沒有大小檢查**（缺少步驟 4），使用者可以透過 LIFF 上傳任意大小的圖片。

---

## 怎麼改

### 新增 `services/storage_service.py`

集中實作 `async def save_image(file: UploadFile) -> str`：

```
輸入：FastAPI UploadFile
輸出：「uploads/{uuid}.ext」相對路徑（統一格式，永遠以 uploads/ 開頭）
驗證：MIME 類型 → 大小上限 → 副檔名白名單 → 磁碟寫入
```

**為什麼回傳 `"uploads/{filename}"` 而不是完整絕對路徑？**  
DB 存的是相對路徑，讓前端透過 `secureImgUrl()` 組成 URL，
後端的 `routers/files.py` 再從 `settings.storage_path` 讀取實際檔案。
這樣 `STORAGE_PATH` 換成任何路徑（甚至未來換 GCS），只需改 `storage_service.py` 一處。

**副檔名白名單**：`{.jpg, .jpeg, .png, .gif, .webp}`  
不在白名單內的副檔名強制轉為 `.jpg`，防止上傳 `.php`、`.js` 等可執行格式。

### 修改 `routers/expenses.py`

兩個端點各 20 行縮減為 1 行：
```python
relative_path = await save_image(file)
```

同時移除了頂層的 `UPLOADS_DIR = Path("uploads")` 常數（已無用）。

### 修改 `services/liff_service.py`

`save_uploaded_file` 改為呼叫 `save_image`（補上原本缺少的大小檢查）：
```python
async def save_uploaded_file(upload_file: UploadFile) -> str:
    return await _save_image(upload_file)
```

因為 `save_image` 是 async，所以：
- `save_uploaded_file` → 改為 `async def`
- `add_image` → 改為 `async def`（因為內部 await save_uploaded_file）
- `routers/liff.py:upload_image` → 改為 `async def`（因為 await add_image）

---

## 如何驗證修改有效

啟動後端：
```powershell
uvicorn main:app --reload --port 8000
```

先取得 JWT：
```powershell
$resp = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/auth/login" `
  -Method POST -ContentType "application/x-www-form-urlencoded" `
  -Body "username=你的帳號&password=你的密碼"
$token = ($resp.Content | ConvertFrom-Json).data.access_token
$headers = @{ Authorization = "Bearer $token" }
```

### 測試 1：正常上傳（應 201，回傳 image_url 以 "uploads/" 開頭）

```powershell
# 準備一張小圖片（< 10MB）
$form = @{
  file       = Get-Item "test.jpg"
  image_type = "expense"
}
$resp = Invoke-WebRequest `
  -Uri "http://localhost:8000/api/v1/expenses/{真實的 expense UUID}/images" `
  -Method POST -Headers $headers -Form $form
$data = ($resp.Content | ConvertFrom-Json).data
$data.image_url  # 預期：["uploads/xxxxxxxx-xxxx.jpg"]（以 uploads/ 開頭，不含絕對路徑）
```

### 測試 2：上傳超過 10MB 的檔案（應 400）

```powershell
# 建立 11MB 的假檔案
$bytes = New-Object byte[] (11 * 1024 * 1024)
[System.IO.File]::WriteAllBytes("big.jpg", $bytes)

try {
  Invoke-WebRequest `
    -Uri "http://localhost:8000/api/v1/expenses/{UUID}/images" `
    -Method POST -Headers $headers `
    -Form @{ file = Get-Item "big.jpg"; image_type = "expense" }
} catch {
  $_.Exception.Response.StatusCode  # 預期：400
}
```

### 測試 3：replace 端點也受大小限制（舊版已有，確認沒有退步）

```powershell
try {
  Invoke-WebRequest `
    -Uri "http://localhost:8000/api/v1/expenses/{UUID}/images/replace" `
    -Method POST -Headers $headers `
    -Form @{ file = Get-Item "big.jpg"; image_type = "expense"; index = 0 }
} catch {
  $_.Exception.Response.StatusCode  # 預期：400
}
```

### 測試 4：LIFF 上傳也受大小限制（此為修復前的漏洞，修復後應 400）

LIFF 上傳走的是 `POST /liff/sessions/{session_id}/images`，  
傳大於 10MB 的圖片應該也要收到 400。

### 測試 5：DB 裡的 image_url 格式一致

```powershell
# 分別透過 Dashboard 補件（expenses router）和 LIFF 上傳各一張圖後
$resp = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/expenses?page_size=5" `
  -Headers $headers
($resp.Content | ConvertFrom-Json).data.items |
  Select-Object serial_number, image_url |
  ForEach-Object {
    $_.image_url | ForEach-Object {
      if ($_ -notmatch "^uploads/") { Write-Host "❌ 路徑格式錯誤: $_" }
      else { Write-Host "✅ $_" }
    }
  }
# 預期：全部 ✅，沒有 ❌
```

---

## 未來擴充注意事項

- **要換 GCS / S3**：只改 `services/storage_service.py` 的 `save_image()` 函式本體，
  把 `dest.write_bytes(content)` 換成雲端 SDK 的上傳呼叫，回傳值格式不變。
- **要改大小上限**：只改 `.env` 的 `MAX_UPLOAD_BYTES`，不需要改程式碼。
- **要增加允許的副檔名**：修改 `storage_service.py` 的 `_ALLOWED_EXTENSIONS` 集合。
- **任何新增的上傳端點**：呼叫 `from services.storage_service import save_image`，
  不要自己實作儲存邏輯。
