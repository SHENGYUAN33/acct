"""Storage Service — 統一檔案儲存入口。

所有上傳檔案必須透過此模組的 save_image()，確保：
  1. MIME 類型驗證（允許 image/* 及 application/pdf）
  2. 副檔名白名單（防止上傳 .php / .js 等可執行檔案）
  3. 大小上限檢查（settings.max_upload_bytes，預設 10MB）
  4. 儲存路徑統一使用 settings.storage_path（不硬編碼 "uploads/"）
  5. 回傳格式統一為 「uploads/{uuid}.ext」相對路徑

支援格式：JPEG、PNG、GIF、WebP、BMP、TIFF、PDF
"""

import logging
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from core.config import settings
from services import object_storage

logger = logging.getLogger(__name__)

# 允許的 MIME 類型（image/* 系列 + PDF）
_ALLOWED_MIME_PREFIXES = ("image/",)
_ALLOWED_MIME_EXACT = {"application/pdf"}

# 允許的副檔名（小寫），決定存檔時保留的副檔名
_ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg",   # JPEG
    ".png",            # PNG
    ".gif",            # GIF
    ".webp",           # WebP
    ".bmp",            # BMP
    ".tiff", ".tif",   # TIFF
    ".pdf",            # PDF
}


def _is_allowed_mime(content_type: str) -> bool:
    """檢查 MIME 類型是否在允許清單內。"""
    if any(content_type.startswith(p) for p in _ALLOWED_MIME_PREFIXES):
        return True
    return content_type in _ALLOWED_MIME_EXACT


async def save_image(file: UploadFile) -> str:
    """
    驗證並儲存上傳的檔案。

    Args:
        file: FastAPI UploadFile 物件。

    Returns:
        相對路徑字串，格式為 「uploads/{uuid}.ext」，
        可直接寫入 DB 的 image_url 欄位。

    Raises:
        HTTPException 415: 不支援的 MIME 類型。
        HTTPException 400: 超過大小上限。
        HTTPException 500: 寫入磁碟失敗。
    """
    content_type = (file.content_type or "").lower()
    if not _is_allowed_mime(content_type):
        raise HTTPException(
            status_code=415,
            detail=f"不支援的檔案類型（{content_type}）。允許：圖片或 PDF",
        )

    content = await file.read()

    if len(content) > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"檔案超過大小限制（上限 {limit_mb} MB）")

    raw_ext = Path(file.filename or "").suffix.lower()
    ext = raw_ext if raw_ext in _ALLOWED_EXTENSIONS else ".jpg"

    filename = f"{uuid.uuid4()}{ext}"
    rel_path = f"uploads/{filename}"

    try:
        object_storage.put_bytes(rel_path, content, content_type=content_type)
    except Exception as e:
        logger.error("檔案儲存失敗 path=%s: %s", rel_path, e, exc_info=True)
        raise HTTPException(status_code=500, detail="檔案儲存失敗，請稍後再試")

    return rel_path
