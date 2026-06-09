# 組別 C 修復紀錄：業務常數集中至 core/constants.py

**修改日期**：2026-06-08  
**涉及檔案**：`core/constants.py`（新增）、`routers/expenses.py`  
**關聯問題**：2.6（Translation Maps 定義在 Router 層）

---

## 為什麼要改

`routers/expenses.py` 頂層定義了四個業務常數：

```python
VOUCHER_CATEGORY_ZH = { "INVOICE": "發票", ... }  # 憑證類別中文
STATUS_ZH           = { "PENDING": "待審核", ... } # 費用狀態中文
EXPENSE_CATEGORY_ZH = { "MEAL": "餐費", ... }      # 費用科目中文
CSV_HEADERS         = ["案件編號", "ID", ...]       # CSV 欄位名
TAX_REPORT_HEADERS  = ["案件編號", "費用日期", ...]  # 進項稅表欄位名
```

這些是**業務常數**，不是路由邏輯，放在 Router 層有以下問題：

1. **跨模組重複**：若 LINE 推播訊息、排程報表或前端 API 也需要「PENDING → 待審核」
   的對照，就得在其他地方重複定義，或跨層 import Router 模組（嚴重違反職責分離）。

2. **測試困難**：常數和 FastAPI 路由混在一起，要 import 常數就必須觸發 FastAPI 初始化。

3. **易遺漏**：`expenseStore.js` 的 `CATEGORY_LABEL`、`WaitingReturnModal.vue` 的
   `VOUCHER_CATEGORY_LABEL` 各自重複定義了部分相同內容，就是因為沒有共用來源。

---

## 怎麼改

新增 `core/constants.py`，所有常數搬到此處。

`routers/expenses.py` 改為 import：
```python
from core.constants import (
    CSV_HEADERS, EXPENSE_CATEGORY_ZH,
    STATUS_ZH, TAX_REPORT_HEADERS, VOUCHER_CATEGORY_ZH,
)
```

Router 本體的程式碼完全不變，只是常數的來源從「本地定義」改為「import」。

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

### 測試 1：CSV 匯出的欄位標題是中文（確認常數正確載入）

```powershell
Invoke-WebRequest -Uri "http://localhost:8000/api/v1/expenses/export" `
  -Headers $headers -OutFile "test_export.csv"

# 讀取第一行（欄位名稱列）
$firstLine = Get-Content "test_export.csv" -First 1 -Encoding UTF8
Write-Host $firstLine
# 預期包含：案件編號,ID,上傳者,上傳者組別...
```

### 測試 2：費用列表中的狀態是中文（STATUS_ZH 正確）

```powershell
# 確認 API 回傳資料（狀態欄位是英文代碼，中文轉換在 CSV 和前端處理）
# 此測試確認後端能正常啟動且 import 沒有報錯
$resp = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/expenses?page_size=1" `
  -Headers $headers
$resp.StatusCode  # 預期：200
```

### 測試 3：進項稅額明細表欄位標題正確

```powershell
$today = Get-Date -Format "yyyy-MM-dd"
Invoke-WebRequest `
  -Uri "http://localhost:8000/api/v1/expenses/export/tax-report?date_from=2024-01-01&date_to=$today" `
  -Headers $headers -OutFile "test_tax.csv"

$firstLine = Get-Content "test_tax.csv" -First 1 -Encoding UTF8
Write-Host $firstLine
# 預期包含：案件編號,費用日期,發票號碼,憑證類型...
```

### 測試 4：確認 core/constants.py 可被獨立 import（不依賴 FastAPI）

```powershell
python -c "from core.constants import VOUCHER_CATEGORY_ZH, STATUS_ZH; print('OK', len(VOUCHER_CATEGORY_ZH))"
# 預期：OK 11（或對應的常數數量）
```

---

## 未來擴充注意事項

- **要新增一個憑證類別**：只改 `core/constants.py` 的 `VOUCHER_CATEGORY_ZH`，
  前端的 `CATEGORY_LABEL`（expenseStore.js）和 `VOUCHER_CATEGORY_LABEL`
  （WaitingReturnModal.vue）目前仍是各自維護，理想情況是透過 `/api/v1/config` 端點
  動態載入，但這是更大的重構，現階段先記錄此差異。

- **要在 LINE 推播訊息中顯示狀態中文**：直接 `from core.constants import STATUS_ZH`，
  不要在 `line_service.py` 另外定義對照表。

- **不要把路由邏輯（如 `_classify_tax_type()`）搬到 constants.py**：
  該函式依賴業務邏輯，應留在 `expenses.py` 或移至 `services/` 層，constants.py 只放純資料。
