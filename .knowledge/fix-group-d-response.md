# 組別 D 修復紀錄：統一 API 回應格式

**修改日期**：2026-06-08  
**涉及檔案**：`core/response.py`（新增）、`routers/admin.py`、`routers/auth.py`、`routers/config.py`、`routers/expenses.py`、`routers/roster.py`  
**關聯問題**：2.2（API 回應格式重複散落）

---

## 為什麼要改

全專案 35 個端點各自手動拼裝回應 dict：

```python
return {
    "status": "success",
    "data": ExpenseRead.model_validate(expense).model_dump(),
    "message": "Expense updated",
}
```

這造成三個問題：

1. **格式容易打錯且無法被靜態分析檢查**  
   `"status": "succcess"`、`"mesage"` 之類的 typo 只有在實際呼叫時才會發現。

2. **未來全站改格式需要搜尋 35 處**  
   例如想在所有回應加上 `"request_id"` 追蹤欄位，
   或把 `"status"` 改成 HTTP 狀態碼，就需要逐一修改。

3. **無法在統一入口加 logging / tracing**  
   若要記錄所有 API 回應的 payload 大小或加入 trace ID，
   現在沒有集中的地方可以掛 hook。

---

## 怎麼改

新增 `core/response.py`，只有一個函式：

```python
def ok(data=None, message="ok") -> dict:
    return {"status": "success", "data": data, "message": message}
```

所有端點改為：

```python
from core.response import ok

# 之前
return {"status": "success", "data": result.model_dump(), "message": "ok"}

# 之後
return ok(data=result.model_dump())
```

**為什麼不做 Pydantic 模型？**  
`response_model=dict` 已經夠用，現階段引入 Generic Pydantic model 會需要改所有
`response_model=dict` 為 `response_model=ApiResponse[ExpenseRead]`，改動量更大。
`ok()` 是最小侵入性的第一步，確認沒有問題後再升級也不遲。

**沒有 `fail()` 函式？**  
錯誤路徑統一用 FastAPI 的 `HTTPException`，會自動產生 `{"detail": "..."}` 格式。
刻意不提供 `fail()`，避免混用兩種錯誤回應格式。

---

## 如何驗證修改有效

### 測試 1：各端點回傳格式仍然正確

```powershell
$resp = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/auth/login" `
  -Method POST -ContentType "application/x-www-form-urlencoded" `
  -Body "username=你的帳號&password=你的密碼"
$body = $resp.Content | ConvertFrom-Json
$body.status   # 預期："success"
$body.data     # 預期：含 access_token 的物件
$body.message  # 預期："登入成功"
```

### 測試 2：取得費用列表格式正確

```powershell
$token = ($resp.Content | ConvertFrom-Json).data.access_token
$r = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/expenses?page_size=1" `
  -Headers @{ Authorization = "Bearer $token" }
$b = $r.Content | ConvertFrom-Json
$b.status        # 預期："success"
$b.data.total    # 預期：數字
$b.data.items    # 預期：陣列
$b.message       # 預期："ok"
```

### 測試 3：設定端點格式正確

```powershell
$r = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/config/departments"
($r.Content | ConvertFrom-Json).status   # 預期："success"
($r.Content | ConvertFrom-Json).data.departments  # 預期：陣列
```

### 測試 4：確認程式碼中沒有殘留的手動拼裝

```powershell
# 應回傳 0
Select-String -Path "routers\*.py" -Pattern '"status": "success"' | Measure-Object | Select-Object -ExpandProperty Count
# 預期：0
```

---

## 未來擴充注意事項

- **要加 request_id**：只改 `core/response.py` 的 `ok()` 一處：
  ```python
  import uuid
  def ok(data=None, message="ok") -> dict:
      return {"status": "success", "data": data, "message": message,
              "request_id": str(uuid.uuid4())}
  ```

- **要做 logging**：在 `ok()` 裡加 `logger.debug(...)` 即可全站生效。

- **StreamingResponse（CSV 匯出）不適用 ok()**：這些端點直接回傳串流，
  不走 JSON 包裝格式，不需要改，也不應該改。

- **`/health` 端點刻意沒改**：它在 `main.py` 不在 router 目錄，
  且格式與業務 API 略有不同（含 `db` 欄位），若要統一可自行決定。
