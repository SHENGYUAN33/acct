# 費用彙整服務（create_batch_expense）

| 欄位 | 值 |
|------|-----|
| ID | T6 |
| 專案 | AcctAssist |
| Sprint | Sprint 2 |
| 指派給 | backend-dev |
| 優先級 | P0 |
| 狀態 | done |
| 依賴 | T3 |
| 預估 | 3h |
| 建立時間 | 2026-04-11T00:00:00.000Z |

---

## 任務描述

⚠️ **前置條件**：T3（DB Migration）完成

### `services/expense_service.py` — 新增方法

#### `create_batch_expense(db, user_id, pending_images, ocr_results, user_description, uploader_dept)`

**費用彙整規則**：

| 規則 | 說明 |
|------|------|
| 主憑證優先級 | INVOICE > RECEIPT > LABOR_SERVICE > TRANSPORTATION（取第一順位填入 expenses 主欄位） |
| `total_amount` | 加總所有 `is_voucher=True` 且 `total_amount` 非 null 的金額；CREDIT_NOTE 負數直接加總 |
| `voucher_categories` | 去重後的 is_voucher=True 類別清單，存為 JSON array |
| `image_count` | `len(pending_images)` |
| `status` | `PENDING` if `total_amount != null` else `NEEDS_MANUAL_REVIEW`（全部 OCR 失敗時） |

**DB 操作**：
- INSERT 1 筆 `Expense`（含彙整後欄位）
- INSERT N 筆 `ExpenseImage`（對應每張照片 + OCR 結果）
- 全程使用 async/await

#### `get_expense_images(db: AsyncSession, expense_id: UUID) -> list[ExpenseImage]`

- 查詢 `expense_images` 表，按 `sequence_order` 排序
- 全程使用 async/await

### `routers/expenses.py` — 新增端點

`GET /api/v1/expenses/{id}/images`

**回應格式**：
```json
{
  "status": "success",
  "data": {
    "expense_id": "uuid",
    "images": [
      {
        "id": "uuid",
        "image_url": "uploads/xxx.jpg",
        "is_voucher": true,
        "voucher_category": "INVOICE",
        "sequence_order": 1,
        "ocr_result": { "invoice_number": "AB12345678", "total_amount": 2400 },
        "created_at": "2026-04-11T10:00:00"
      }
    ]
  },
  "message": "成功"
}
```

### `schemas/expense_image.py` — 新增（新檔）

- `ExpenseImageRead` Pydantic schema（對應 ExpenseImage ORM）

## 驗收標準

- [ ] `create_batch_expense()` 正確建立 1 筆 Expense + N 筆 ExpenseImage
- [ ] `total_amount` 正確加總（含 CREDIT_NOTE 負數、含部分 null）
- [ ] `voucher_categories` 去重後存為 JSON array
- [ ] `image_count` 等於 `len(pending_images)`
- [ ] 全部批次 OCR 失敗時：`status = NEEDS_MANUAL_REVIEW`
- [ ] `GET /api/v1/expenses/{id}/images` 回傳正確格式
- [ ] 不存在的 expense_id → 回傳 404
- [ ] 所有 DB 操作使用 async/await

---

## 事件紀錄

### 2026-04-11T00:00:00.000Z — 建立任務（assigned）
由 L1（project-lead）透過 /task-delegation 建立
⚠️ 等待 T3 完成後解鎖

### 2026-04-10T18:36:39.000Z — 開始執行（in_progress）
T3 已完成，由 L1（project-lead）委派給 backend-dev 啟動

### 2026-04-10T18:36:39.000Z — 完成交付（in_review）
新增 schemas/expense_image.py（ExpenseImageRead）、services/expense_service.py 兩個方法（create_batch_expense、get_expense_images）、routers/expenses.py 新端點 GET /api/v1/expenses/{id}/images

### 2026-04-10T18:36:39.000Z — L1 審核通過（done）
審核者：project-lead。彙整規則正確、主憑證優先級實作清晰、JWT 認證由 Router 層統一保護、回應格式符合規範。全數通過。
