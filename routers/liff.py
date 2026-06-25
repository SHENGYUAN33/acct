"""LIFF 批次上傳 API 路由。

端點清單：
  POST   /liff/sessions                              — 建立上傳 Session
  POST   /liff/sessions/{session_id}/images          — 上傳單張圖片（multipart）
  PATCH  /liff/sessions/{session_id}/images/{img_id} — 手動切換憑證/物品照類型
  GET    /liff/sessions/{session_id}/preview         — 確認頁群組預覽
  POST   /liff/sessions/{session_id}/submit          — 確認送出，建立 Expense

認證方式：X-Line-User-Id header（由 LIFF 前端帶入 liff.getProfile().userId）
"""

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from core.database import get_db
from schemas.liff import (
    CreateSessionRequest,
    ImageResponse,
    ImageUploadResponse,
    PatchImageRequest,
    SessionPreviewResponse,
    SessionResponse,
    SubmitSessionRequest,
    SubmitSessionResponse,
)
from services import liff_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/liff",
    tags=["liff"],
)


# ---------------------------------------------------------------------------
# 共用 dependency：從 Header 取得 LINE User ID
# ---------------------------------------------------------------------------

def get_line_user_id(
    x_line_user_id: str | None = Header(default=None, alias="X-Line-User-Id"),
    uid: str | None = Query(default=None, description="LINE user id（apiGet fallback，與 X-Line-User-Id 擇一）"),
) -> str:
    """
    從請求 Header 或 query param 取得 LINE 使用者 ID。

    優先讀 X-Line-User-Id header；若 header 被 LINE WebKit 限制，
    前端 apiGet 會改用 ?uid= query param 作為備援。
    """
    user_id = x_line_user_id or uid
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 X-Line-User-Id header，請透過 LIFF 頁面呼叫此 API",
        )
    return user_id


# ---------------------------------------------------------------------------
# POST /liff/sessions — 建立 Session
# ---------------------------------------------------------------------------

@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="建立 LIFF 上傳 Session",
)
def create_session(
    body: CreateSessionRequest,
    db: Session = Depends(get_db),
) -> SessionResponse:
    """
    建立一個新的上傳 Session（TTL 30 分鐘）。

    前端在使用者進入 LIFF 頁面後立即呼叫，取得 session_id 供後續圖片上傳使用。
    """
    session = liff_service.create_session(db, body.line_user_id)
    return SessionResponse(
        session_id=session.id,
        expires_at=session.expires_at,
        status=session.status,
    )


# ---------------------------------------------------------------------------
# POST /liff/sessions/{session_id}/images — 上傳單張圖片
# ---------------------------------------------------------------------------

@router.post(
    "/sessions/{session_id}/images",
    response_model=ImageUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="上傳單張圖片至 Session",
)
async def upload_image(
    session_id: uuid.UUID,
    file: UploadFile = File(..., description="圖片檔案"),
    sequence_order: int = Form(..., description="前端凍結的排列順序（0-based）"),
    line_user_id: str = Depends(get_line_user_id),
    db: Session = Depends(get_db),
) -> ImageUploadResponse:
    """
    上傳單張圖片至指定 Session，儲存檔案並建立 SessionImage 記錄。
    OCR 不在此同步執行，由 submit 後的背景任務統一處理。

    **重要**：sequence_order 由前端在使用者按下「送出」瞬間 Object.freeze() 凍結，
    後端永遠以此欄位排序，與圖片到達時間無關。
    """
    _ct = (file.content_type or "").lower()
    if _ct and not _ct.startswith("image/") and _ct != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"不支援的檔案類型：{file.content_type}。允許：圖片或 PDF",
        )

    img_record, ocr_completed, is_voucher = await liff_service.add_image(
        db=db,
        session_id=session_id,
        upload_file=file,
        sequence_order=sequence_order,
    )

    return ImageUploadResponse(
        image=ImageResponse(
            image_id=img_record.id,
            sequence_order=img_record.sequence_order,
            image_path=img_record.image_path,
            is_voucher=img_record.is_voucher,
            manually_set=img_record.manually_set,
        ),
        ocr_completed=ocr_completed,
        is_voucher=is_voucher,
    )


# ---------------------------------------------------------------------------
# PATCH /liff/sessions/{session_id}/images/{image_id} — 手動切換類型
# ---------------------------------------------------------------------------

@router.patch(
    "/sessions/{session_id}/images/{image_id}",
    response_model=ImageResponse,
    summary="手動切換圖片類型（憑證 / 物品照）",
)
def patch_image(
    session_id: uuid.UUID,
    image_id: uuid.UUID,
    body: PatchImageRequest,
    line_user_id: str = Depends(get_line_user_id),
    db: Session = Depends(get_db),
) -> ImageResponse:
    """
    使用者在確認頁手動切換 is_voucher 類型。

    manually_set=True 後，此圖片的分組判斷優先於 OCR 結果。
    """
    img = liff_service.patch_image_type(
        db=db,
        session_id=session_id,
        image_id=image_id,
        is_voucher=body.is_voucher,
    )
    return ImageResponse(
        image_id=img.id,
        sequence_order=img.sequence_order,
        image_path=img.image_path,
        is_voucher=img.is_voucher,
        manually_set=img.manually_set,
    )


# ---------------------------------------------------------------------------
# GET /liff/sessions/{session_id}/preview — 確認頁預覽
# ---------------------------------------------------------------------------

@router.get(
    "/sessions/{session_id}/preview",
    response_model=SessionPreviewResponse,
    summary="取得 Session 費用群組預覽",
)
def get_preview(
    session_id: uuid.UUID,
    line_user_id: str = Depends(get_line_user_id),
    db: Session = Depends(get_db),
) -> SessionPreviewResponse:
    """
    依 sequence_order ASC 重建費用群組預覽，供確認頁渲染。

    群組切割規則：
    - is_voucher=True 的圖片作為每個費用群組的起點
    - 第一張 voucher 之前的物品圖歸入 orphan_images（將關聯至最近的報帳）
    """
    return liff_service.get_session_preview(db=db, session_id=session_id)


# ---------------------------------------------------------------------------
# POST /liff/sessions/{session_id}/submit — 確認送出
# ---------------------------------------------------------------------------

@router.post(
    "/sessions/{session_id}/submit",
    response_model=SubmitSessionResponse,
    summary="確認送出，觸發背景 OCR 與費用建立",
)
def submit_session(
    session_id: uuid.UUID,
    body: SubmitSessionRequest,
    background_tasks: BackgroundTasks,
    line_user_id: str = Depends(get_line_user_id),
    db: Session = Depends(get_db),
) -> SubmitSessionResponse:
    """
    鎖定 Session（status → submitted）並立即回傳，背景任務執行 OCR + 建帳。

    流程：
    1. 標記 session.status = "submitted"（防止重複送出）、processing_status = "pending"
    2. 立即回傳 200，使用者不再等待 OCR
    3. 背景任務 process_session_background：OCR → multi_split_logic_v2 → create_batch_expense × N
    """
    desc_map: dict[int, str] = {
        g.group_index: g.description
        for g in body.group_descriptions
    }

    response = liff_service.submit_session(
        db=db,
        session_id=session_id,
        group_descriptions=desc_map,
        waiting_return_ref=body.waiting_return_ref,
    )

    background_tasks.add_task(
        liff_service.process_session_background,
        session_id=session_id,
        group_descriptions=desc_map,
        waiting_return_ref=body.waiting_return_ref,
        is_waiting_return=body.is_waiting_return,
        is_return_supplement=body.is_return_supplement,
        wr_original_invoice=body.wr_original_invoice,
        wr_original_date=body.wr_original_date,
        wr_original_amount=body.wr_original_amount,
        wr_is_amount_correction=body.wr_is_amount_correction,
    )

    return response
