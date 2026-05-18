# 回滾說明

這個資料夾是 **LIFF 批次上傳功能** 開發前的備份，時間：2026-05-18。

## 一鍵回滾指令

在專案根目錄執行：

```bash
cp _rollback/main.py main.py
cp _rollback/requirements.txt requirements.txt
cp -r _rollback/routers/* routers/
cp -r _rollback/services/* services/
cp -r _rollback/models/* models/
cp -r _rollback/schemas/* schemas/
```

## 新增的檔案（直接刪除即可）

開發過程中只會新增以下檔案，不會修改現有邏輯：

| 新增位置 | 說明 |
|---|---|
| `routers/liff.py` | LIFF 專用 API 路由 |
| `services/liff_service.py` | LIFF session 管理邏輯 |
| `models/liff_session.py` | UploadSession ORM |
| `schemas/liff.py` | LIFF 請求/回應 schema |
| `liff/` | LIFF 前端靜態檔案目錄 |
| `alembic/versions/liff_session_*` | 資料庫 migration |

刪除以上新增檔案後，再執行上方 cp 指令，系統即完全恢復。

## 備份內容清單

- `main.py` — FastAPI 入口（掛載 LIFF 路由處會修改）
- `requirements.txt` — 可能新增 python-multipart 等依賴
- `routers/` — 所有路由備份
- `services/` — 所有服務備份
- `models/` — 所有 ORM 備份
- `schemas/` — 所有 schema 備份
