"""Files Router — 受 JWT 保護的靜態圖片代理。

移除 main.py 的公開 StaticFiles 掛載後，所有圖片請求改走此端點。
支援兩種認證方式，因為 <img> 標籤無法帶 Authorization header：
  1. Authorization: Bearer <token>  （Axios / fetch 呼叫）
  2. ?token=<token>                 （<img :src="url?token=xxx"> 直接嵌入）
"""

import logging
import re
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import FileResponse

from core.config import settings
from core.security import decode_access_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["files"])

# 只允許 UUID 格式 + 白名單副檔名，防止路徑穿越
_SAFE_FILENAME_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"\.(jpg|jpeg|png|gif|webp)$",
    re.IGNORECASE,
)


def _resolve_token(authorization: str | None, token: str | None) -> str:
    """從 Header 或 query param 取出原始 JWT 字串。"""
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    if token:
        return token
    return ""


@router.get("/api/v1/uploads/{filename}", include_in_schema=False)
def serve_upload(
    filename: str,
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> FileResponse:
    """
    JWT 保護的圖片代理端點。
    認證通過後從 STORAGE_PATH 讀取檔案並串流回傳。
    """
    raw_token = _resolve_token(authorization, token)
    if not raw_token or not decode_access_token(raw_token):
        raise HTTPException(status_code=401, detail="未授權，請重新登入")

    if not _SAFE_FILENAME_RE.match(filename):
        raise HTTPException(status_code=404, detail="檔案不存在")

    path = Path(settings.storage_path) / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="檔案不存在")

    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=300"},
    )
