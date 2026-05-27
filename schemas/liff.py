"""LIFF 批次上傳 API 的 Pydantic Request / Response Schema。

端點對應：
  POST /liff/sessions                — CreateSessionRequest → SessionResponse
  POST /liff/sessions/{id}/images    — (multipart, 無 schema) → ImageUploadResponse
  POST /liff/sessions/{id}/submit    — SubmitSessionRequest → SubmitSessionResponse
  GET  /liff/sessions/{id}/preview   — → SessionPreviewResponse
  PATCH /liff/sessions/{id}/images/{image_id} — PatchImageRequest → ImageResponse
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# POST /liff/sessions — 建立上傳 Session
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    line_user_id: str = Field(..., max_length=64, description="LINE 使用者 ID（由 liff.getProfile() 取得）")
    id_token: str = Field(..., description="liff.getIDToken() 回傳的 JWT，用於後端驗證身分")


class SessionResponse(BaseModel):
    session_id: uuid.UUID
    expires_at: datetime
    status: str  # uploading | submitted | expired

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# POST /liff/sessions/{session_id}/images — 上傳單張圖片
# ---------------------------------------------------------------------------
# Request 為 multipart/form-data，含：
#   file           : UploadFile（圖片）
#   sequence_order : int（前端凍結的順序）
# 無需獨立 Pydantic schema。

class ImageResponse(BaseModel):
    image_id: uuid.UUID
    sequence_order: int
    image_path: str
    is_voucher: bool | None = None   # OCR 完成前為 None
    manually_set: bool = False

    model_config = {"from_attributes": True}


class ImageUploadResponse(BaseModel):
    image: ImageResponse
    ocr_completed: bool = False       # 本次呼叫是否同步完成 OCR
    is_voucher: bool | None = None    # OCR 判斷結果（ocr_completed=True 時才有值）


# ---------------------------------------------------------------------------
# PATCH /liff/sessions/{session_id}/images/{image_id} — 手動切換類型
# ---------------------------------------------------------------------------

class PatchImageRequest(BaseModel):
    is_voucher: bool = Field(..., description="True=憑證  False=物品照")


# ---------------------------------------------------------------------------
# GET /liff/sessions/{session_id}/preview — 確認頁預覽
# ---------------------------------------------------------------------------

class PreviewImageItem(BaseModel):
    image_id: uuid.UUID
    sequence_order: int
    image_path: str
    is_voucher: bool | None
    manually_set: bool

    model_config = {"from_attributes": True}


class ExpenseGroupPreview(BaseModel):
    """對應一筆即將建立的 Expense（以 is_voucher=True 的圖片為群組起點）。"""
    group_index: int           # 0-based
    voucher_image: PreviewImageItem | None  # 群組起始的憑證圖
    item_images: list[PreviewImageItem]     # 附屬的物品圖
    description: str = ""     # 使用者備註（submit 時填入）


class SessionPreviewResponse(BaseModel):
    session_id: uuid.UUID
    status: str
    groups: list[ExpenseGroupPreview]
    orphan_images: list[PreviewImageItem]   # 第一張憑證之前的物品圖（孤立）
    total_images: int


# ---------------------------------------------------------------------------
# POST /liff/sessions/{session_id}/submit — 確認送出
# ---------------------------------------------------------------------------

class GroupDescription(BaseModel):
    """每個費用群組的備註（以 group_index 對應）。"""
    group_index: int
    description: str = ""


class SubmitSessionRequest(BaseModel):
    group_descriptions: list[GroupDescription] = Field(
        default_factory=list,
        description="各費用群組的文字備註，可空清單表示無備註",
    )
    waiting_return_ref: str | None = Field(
        default=None,
        description="[舊版] 待退貨原始憑證號碼（向後相容保留，新版請用 is_return_supplement）",
    )
    is_return_supplement: bool = Field(
        default=False,
        description="此次上傳為退貨補件（勾選後系統依 OCR 結果與填寫欄位自動判斷情境）",
    )
    wr_original_invoice: str | None = Field(
        default=None,
        description="情境A：被替換的原始發票號碼",
    )
    wr_original_date: str | None = Field(
        default=None,
        description="情境C：原始收據日期（YYYY-MM-DD）",
    )
    wr_original_amount: float | None = Field(
        default=None,
        description="情境C：原始收據金額（用於模糊比對）",
    )


class CreatedExpenseItem(BaseModel):
    group_index: int
    expense_id: uuid.UUID
    serial_number: str


class SubmitSessionResponse(BaseModel):
    session_id: uuid.UUID
    created_expenses: list[CreatedExpenseItem]
    orphan_attached: bool = False   # 孤立物品圖是否已附加至近期報帳
    message: str = "上傳成功"
