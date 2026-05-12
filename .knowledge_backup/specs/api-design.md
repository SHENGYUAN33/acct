# API 設計規範

> 版本: v1.1 | Sprint 2 | 最後更新: 2026-04-11

## 概述

AcctAssist RESTful API，分為三個功能群組：
- **Webhook**：接收 LINE 平台事件
- **Expenses**：Dashboard 報帳 CRUD 與審核操作
- **System**：健康檢查

所有 API 統一回應格式（除 204、CSV Stream）：
```json
{ "status": "success" | "error", "data": { ... } | null, "message": "說明文字" }
```

---

## 端點清單

### Webhook

| Method | Path | 說明 |
|--------|------|------|
| `POST` | `/webhook` | 接收 LINE 事件（TextMessage / ImageMessage / PostbackEvent） |

**驗證**：`X-Line-Signature` Header 必須通過 HMAC-SHA256 驗證，否則回 400。
空 body（LINE 驗證用）直接回 200。

---

### Expenses

#### 查詢

| Method | Path | 說明 |
|--------|------|------|
| `GET` | `/api/v1/expenses` | 報帳清單（分頁 + 篩選） |
| `GET` | `/api/v1/expenses/{id}` | 單筆詳情 |
| `GET` | `/api/v1/expenses/export` | 匯出 CSV（含 UTF-8 BOM，最多 10,000 筆） |

**GET /api/v1/expenses Query Params：**

| 參數 | 型別 | 說明 |
|------|------|------|
| `status` | `PENDING\|APPROVED\|REJECTED\|NEEDS_MANUAL_REVIEW` | 狀態篩選（可選） |
| `date_from` | ISO 8601 datetime | 起始時間（可選） |
| `date_to` | ISO 8601 datetime | 結束時間（可選） |
| `page` | int ≥ 1，預設 1 | 頁碼 |
| `page_size` | int 1–200，預設 20 | 每頁筆數 |

**回應 ExpenseRead 欄位：**

| 欄位 | 型別 | 說明 |
|------|------|------|
| `id` | UUID | 系統主鍵 |
| `user_id` | UUID \| null | 關聯使用者 |
| `serial_number` | string | 案件流水號（EXP-YYYYMM-NNNN） |
| `image_url` | string[] | 憑證圖片路徑陣列 |
| `item_image_url` | string[] | 品項圖片路徑陣列 |
| `uploader_name` | string \| null | 上傳者姓名 |
| `uploader_dept` | string \| null | 上傳者組別 |
| `submitter_name` | string \| null | OCR 解析的申請人 |
| `submitter_dept` | string \| null | 申請人組別 |
| `upload_date` | datetime \| null | 上傳時間 |
| `expense_date` | date \| null | 消費日期 |
| `invoice_number` | string \| null | 發票號碼 |
| `total_amount` | Decimal \| null | 含稅金額 |
| `net_amount` | Decimal \| null | 未稅金額 |
| `tax_amount` | Decimal \| null | 營業稅額 |
| `seller_tax_id` | string \| null | 賣方統編 |
| `seller_name` | string \| null | 賣方名稱 |
| `item_description` | string \| null | 品項說明 |
| `status` | ExpenseStatus | 審核狀態 |
| `reject_reason` | string \| null | 退件原因 |
| `created_at` | datetime | 建立時間 |
| `updated_at` | datetime | 最後更新時間 |
| `user_description` | string \| null | 使用者附加備註（批次送出時填寫） |
| `image_count` | int | 本筆報帳包含的照片數量（預設 1） |
| `voucher_categories` | list\[str\] \| null | 憑證類別清單，JSON 陣列字串，去重後儲存（如 `["INVOICE","RECEIPT"]`） |

---

#### 寫入

| Method | Path | 說明 |
|--------|------|------|
| `POST` | `/api/v1/expenses` | Dashboard 手動新增 |
| `PATCH` | `/api/v1/expenses/{id}` | 部分更新欄位（審核表單儲存） |
| `DELETE` | `/api/v1/expenses/{id}` | 刪除（回 204 No Content） |

---

#### 審核操作

| Method | Path | 說明 |
|--------|------|------|
| `PATCH` | `/api/v1/expenses/{id}/reject` | 退件：設 REJECTED + 原因 + LINE 推播 |

**PATCH /reject Request Body：**
```json
{ "reason": "退件原因（必填）" }
```

**LINE 推播觸發條件：**
- `settings.enable_line_push_reject == True`（預設開啟）
- `expense.user_id` 存在
- `user.line_user_id` 存在

推播失敗不影響 API 回應（catch exception，僅記 log）。

> **核可操作（APPROVED）**：目前透過 `PATCH /api/v1/expenses/{id}` 設定 `status=APPROVED`，不觸發 LINE 推播（Phase 2 待補）。

---

#### 圖片管理

| Method | Path | 說明 |
|--------|------|------|
| `POST` | `/api/v1/expenses/{id}/images` | 追加圖片至陣列末尾 |
| `POST` | `/api/v1/expenses/{id}/images/replace` | 替換指定索引圖片 |
| `GET` | `/api/v1/expenses/{id}/images` | 查詢批次報帳的所有子圖（Sprint 2 新增） |

**Form Data 欄位（POST）：**
| 欄位 | 值 |
|------|-----|
| `file` | 圖片檔案（必須 content-type image/*） |
| `image_type` | `"expense"` 或 `"item"` |
| `index`（replace 專用） | int，從 0 開始 |

---

#### GET /api/v1/expenses/{id}/images（Sprint 2 新增）

查詢一筆批次報帳下的所有憑證子圖，依 `sequence_order` 升序排列。

**認證**：Bearer JWT（必須）

**Path 參數：**
| 參數 | 型別 | 說明 |
|------|------|------|
| `id` | UUID | Expense 主鍵 |

**成功回應（200）：**
```json
{
  "status": "success",
  "data": {
    "expense_id": "550e8400-e29b-41d4-a716-446655440000",
    "images": [
      {
        "id": "660e8400-e29b-41d4-a716-446655440001",
        "expense_id": "550e8400-e29b-41d4-a716-446655440000",
        "image_url": "uploads/invoice_001.jpg",
        "is_voucher": true,
        "voucher_category": "INVOICE",
        "sequence_order": 0,
        "ocr_result": "{\"invoice_number\":\"AB-12345678\",\"total_amount\":2400}",
        "created_at": "2026-04-11T10:00:00Z"
      },
      {
        "id": "660e8400-e29b-41d4-a716-446655440002",
        "expense_id": "550e8400-e29b-41d4-a716-446655440000",
        "image_url": "uploads/receipt_002.jpg",
        "is_voucher": true,
        "voucher_category": "RECEIPT",
        "sequence_order": 1,
        "ocr_result": "{\"seller_name\":\"7-ELEVEN\",\"total_amount\":350}",
        "created_at": "2026-04-11T10:00:01Z"
      }
    ]
  },
  "message": "成功"
}
```

**錯誤回應（404）：**
```json
{ "status": "error", "data": null, "message": "Expense not found" }
```

**ExpenseImage 回應欄位：**
| 欄位 | 型別 | 說明 |
|------|------|------|
| `id` | UUID | 子圖主鍵 |
| `expense_id` | UUID | 所屬 Expense |
| `image_url` | string | 圖片路徑（uploads/…） |
| `is_voucher` | bool | 是否為有效憑證 |
| `voucher_category` | string \| null | 憑證類別（INVOICE/RECEIPT/LABOR_SERVICE/TRANSPORTATION/CREDIT_NOTE） |
| `sequence_order` | int | 圖片順序（從 0 開始） |
| `ocr_result` | string \| null | OCR 結果（JSON 字串，含 fields dict） |
| `created_at` | datetime | 建立時間 |

---

### System

| Method | Path | 說明 |
|--------|------|------|
| `GET` | `/health` | 健康檢查，回 `{ "status": "ok" }` |

---

## 狀態碼規範

| Code | 使用情境 |
|------|---------|
| 200 | 成功（含 GET/PUT/PATCH） |
| 201 | 建立成功（POST /expenses） |
| 204 | 刪除成功 |
| 400 | 請求格式錯誤 / 簽章驗證失敗 |
| 404 | 資源不存在 |
| 422 | Pydantic 驗證失敗（FastAPI 自動） |
| 500 | 伺服器錯誤 |

---

## 功能開關（影響 API 行為）

| 開關 | 預設值 | 影響端點 |
|------|--------|---------|
| `enable_line_push_reject` | `True` | `PATCH /reject` |
| `enable_user_binding` | `True` | `POST /webhook` |
