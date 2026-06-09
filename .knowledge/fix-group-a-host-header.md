# 組別 A 修復紀錄：Host Header 安全強化與重複邏輯消除

**修改日期**：2026-06-08  
**涉及檔案**：`main.py`  
**關聯問題**：2.3（程式碼重複）、3.5（Host Header Injection / XSS）

---

## 為什麼要改

### 問題 2.3：邏輯重複

`serve_liff_root` 與 `serve_liff_single` 各自複製了相同的兩行：

```python
host  = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost:8000")
proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
```

這違反 DRY 原則。未來若要加第三個 LIFF 頁面，或修改邏輯（如改 fallback 值），
必須同步修改多處，容易遺漏。

### 問題 3.5：Host Header Injection 導致 XSS

`x-forwarded-host` 是一個**用戶可以完全控制**的 HTTP header，
在沒有反向代理（nginx / GCP Load Balancer）過濾的環境下，任何人都能偽造它。

偽造前的請求：
```
GET /liff-app HTTP/1.1
X-Forwarded-Host: evil.com'; document.location='https://phishing.com'//
```

未修改前的 `_inject_liff_vars()` 直接把 host 注入 HTML：
```python
content.replace("'{{LIFF_API_BASE}}'", f"'{api_base}'")
```

輸出 HTML 裡的 JavaScript 就會變成：
```javascript
const API_BASE = 'http://evil.com'; document.location='https://phishing.com'//';
```

使用者一開啟 LIFF 頁面就會被導向釣魚網站。這屬於 **Reflected XSS / Open Redirect**。

---

## 怎麼改

在 `main.py` 新增私有函式 `_get_base_url(request)`：

```python
_SAFE_HOST_RE = _re.compile(r"^[a-zA-Z0-9.\-]+(:[0-9]{1,5})?$")

def _get_base_url(request: Request) -> str:
    raw_forwarded = request.headers.get("x-forwarded-host", "")
    host = (
        raw_forwarded
        if raw_forwarded and _SAFE_HOST_RE.match(raw_forwarded)
        else request.headers.get("host", "localhost:8000")
    )
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    if proto not in ("http", "https"):
        proto = "http"
    return f"{proto}://{host}"
```

**設計決策說明：**

1. **為什麼只驗證 `x-forwarded-host`，不驗證 `host`？**  
   `Host` header 由 TCP 連線層決定，在反向代理之後的值是代理設定的，
   不是用戶端直接控制的。`X-Forwarded-Host` 才是用戶端可以任意填寫的值。

2. **為什麼 fallback 用 `request.headers.get("host")` 而不是 `request.url.host`？**  
   `request.url` 在某些 ASGI 實作（如 uvicorn 搭配 nginx）裡可能已解析為
   內部 IP，不含外部域名。`Host` header 更接近使用者實際請求的域名。

3. **Regex 允許哪些格式？**  
   `^[a-zA-Z0-9.\-]+(:[0-9]{1,5})?$`
   允許：`localhost:8000`、`myapp.example.com`、`192.168.1.1:8080`  
   拒絕：`evil.com'; alert(1)`、`../etc`、任何含特殊字元的字串

兩個路由函式改為直接呼叫 `_get_base_url(request)`，不再重複讀取 header。

---

## 如何驗證修改有效

啟動後端：
```powershell
uvicorn main:app --reload --port 8000
```

### 測試 1：正常請求（應回傳 HTML，不報錯）
```powershell
$resp = Invoke-WebRequest -Uri "http://localhost:8000/liff-app" -UseBasicParsing
$resp.StatusCode          # 預期：200
$resp.Content.Length -gt 0  # 預期：True
```

### 測試 2：合法的 X-Forwarded-Host（應被採用）
```powershell
$resp = Invoke-WebRequest -Uri "http://localhost:8000/liff-app" `
  -Headers @{ "X-Forwarded-Host" = "myapp.example.com" } -UseBasicParsing
$resp.Content | Select-String "myapp.example.com"
# 預期：找到（合法 host 通過驗證，被注入 HTML）
```

### 測試 3：惡意 X-Forwarded-Host（應被擋掉，使用 fallback）
```powershell
$resp = Invoke-WebRequest -Uri "http://localhost:8000/liff-app" `
  -Headers @{ "X-Forwarded-Host" = "evil.com'; alert(1)//" } -UseBasicParsing

# 惡意字串不應出現在 HTML 中
$resp.Content | Select-String "evil"      # 預期：無輸出
$resp.Content | Select-String "alert"     # 預期：無輸出
# fallback 的 host 應出現（127.0.0.1:8000 或 localhost:8000）
$resp.Content | Select-String "localhost" # 預期：找到
```

### 測試 4：非法 proto（應被強制改為 http）
```powershell
$resp = Invoke-WebRequest -Uri "http://localhost:8000/liff-app" `
  -Headers @{ "X-Forwarded-Proto" = "javascript" } -UseBasicParsing
$resp.Content | Select-String "javascript://"   # 預期：無輸出
$resp.Content | Select-String "http://"         # 預期：找到
```

### 測試 5：`/liff-single` 路由行為一致（重複邏輯已消除）
```powershell
$r1 = Invoke-WebRequest -Uri "http://localhost:8000/liff-app" `
  -Headers @{ "X-Forwarded-Host" = "evil.com'<script>" } -UseBasicParsing
$r2 = Invoke-WebRequest -Uri "http://localhost:8000/liff-single" `
  -Headers @{ "X-Forwarded-Host" = "evil.com'<script>" } -UseBasicParsing

($r1.Content | Select-String "evil") -eq $null   # 預期：True
($r2.Content | Select-String "evil") -eq $null   # 預期：True
```

---

## 未來擴充注意事項

- 若新增第三個 LIFF 路由，直接呼叫 `_get_base_url(request)` 即可，不要重新讀 header。
- 若有 nginx / GCP Load Balancer，需確認反向代理設定了
  `proxy_set_header X-Forwarded-Host $host;` 和 `proxy_set_header X-Forwarded-Proto $scheme;`，
  否則 `_get_base_url` 的 `x-forwarded-host` 分支永遠不會被用到（直接走 fallback 的 Host header）。
- `_SAFE_HOST_RE` 允許 IP 格式（如 `34.123.45.67:8000`），若未來要限制只能用域名，
  可把 regex 改為 `r"^[a-zA-Z0-9.\-]+(:[0-9]{1,5})?$"` 並排除純數字加點的格式。
