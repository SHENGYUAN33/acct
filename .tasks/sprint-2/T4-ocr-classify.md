# OCR 擴充（classify_and_extract）

| 欄位 | 值 |
|------|-----|
| ID | T4 |
| 專案 | AcctAssist |
| Sprint | Sprint 2 |
| 指派給 | backend-dev |
| 優先級 | P0 |
| 狀態 | done |
| 依賴 | — |
| 預估 | 3h |
| 建立時間 | 2026-04-11T00:00:00.000Z |

---

## 任務描述

在 `services/ocr_service.py` 新增批次 OCR 支援。

⚠️ **禁止修改** 現有的 `extract_invoice_data()` 方法（向下相容）。

### 新增 `ImageOCRResult` dataclass

```python
@dataclass
class ImageOCRResult:
    is_voucher: bool
    voucher_category: str | None   # INVOICE / RECEIPT / LABOR_SERVICE / TRANSPORTATION / CREDIT_NOTE
    fields: dict | None            # 各類別專屬欄位
    raw_response: str
    success: bool
    error: str | None
```

### 新增 `classify_and_extract(image_path: str) -> ImageOCRResult`

- **單次 Gemini 呼叫**：判斷是否為憑證（is_voucher）+ 分類 + 萃取欄位
- 使用 `MULTI_TASK_PROMPT`（含 5 種類別完整欄位格式）
- **序列執行**（非並行）：避免 Gemini 免費版 RPM 限制（429）
- Gemini 呼叫失敗時：`success=False`，`error` 填入錯誤訊息，優雅降級

### 各類別欄位規範

| 類別 | 欄位 |
|------|------|
| INVOICE | `invoice_number`, `seller_name`, `seller_tax_id`, `buyer_tax_id`, `total_amount`, `tax_amount`, `expense_date` |
| RECEIPT | `seller_name`, `total_amount`, `expense_date`, `item_description` |
| LABOR_SERVICE | `payee_name`, `id_number`, `net_amount`, `tax_amount`, `total_amount`, `expense_date` |
| TRANSPORTATION | `from_location`, `to_location`, `total_amount`, `expense_date`, `transport_type` |
| CREDIT_NOTE | `seller_name`, `invoice_number`, `total_amount`（必須為**負數**）, `expense_date` |

## 驗收標準

- [ ] `classify_and_extract()` 可獨立呼叫，回傳 `ImageOCRResult`
- [ ] 5 種類別（INVOICE/RECEIPT/LABOR_SERVICE/TRANSPORTATION/CREDIT_NOTE）各自回傳正確的 `fields` 結構
- [ ] 非憑證圖片（如自拍照）：`is_voucher=False`，`fields=None`
- [ ] CREDIT_NOTE 的 `total_amount` 確保為**負數**
- [ ] Gemini API 失敗時：`success=False`，不拋出例外
- [ ] `extract_invoice_data()` 原有功能仍正常執行（無迴歸）
- [ ] 所有 Gemini 呼叫使用 `async/await`

---

## 事件紀錄

### 2026-04-11T00:00:00.000Z — 建立任務（assigned）
由 L1（project-lead）透過 /task-delegation 建立
✅ 可立即開始（無前置依賴）

### 2026-04-10T18:36:39.000Z — 開始執行（in_progress）
由 L1（project-lead）委派給 backend-dev，第一波並行啟動

### 2026-04-10T18:36:39.000Z — 完成交付（in_review）
新增 ImageOCRResult、MULTI_TASK_PROMPT、classify_and_extract()

### 2026-04-10T18:36:39.000Z — L1 審核通過（done）
審核者：project-lead。classify_and_extract 實作完整、CREDIT_NOTE 負數強制轉換正確、雙層 except 優雅降級、extract_invoice_data 原封不動。全數通過。
新增 `ImageOCRResult` dataclass、`MULTI_TASK_PROMPT` 常數、`classify_and_extract()` async 方法至 `services/ocr_service.py`。`extract_invoice_data()` 原有邏輯未動。
