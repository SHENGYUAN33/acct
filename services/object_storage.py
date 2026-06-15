"""統一物件儲存層 — 依 STORAGE_BACKEND 切換本機磁碟或 Google Cloud Storage。

所有上傳圖片的「寫入 / 讀取 / 刪除」都應透過本模組，讓上層程式碼
（storage_service / line_service / ocr_service / files 路由 / liff_service）
不需感知底層是本機磁碟（開發）或 GCS（Cloud Run 正式環境）。

DB 內 image_url 一律維持相對鍵格式「uploads/{uuid}.ext」；本模組負責把該鍵
對應到本機路徑或 GCS object 名稱（兩者皆為 uploads/{uuid}.ext），確保舊資料相容。
"""

import logging
from pathlib import Path

from core.config import settings

logger = logging.getLogger(__name__)

# GCS bucket handle 延遲初始化（避免本機開發時載入 GCS SDK 或建立連線）
_gcs_bucket = None


def _is_gcs() -> bool:
    """目前是否使用 GCS 後端。"""
    return settings.storage_backend.lower() == "gcs"


def _normalize_key(rel_path: str) -> str:
    """正規化為 uploads/xxx 形式的 GCS 物件鍵（統一斜線、去除前導斜線）。"""
    return str(rel_path).replace("\\", "/").lstrip("/")


def _get_bucket():
    """取得（並快取）GCS bucket handle。"""
    global _gcs_bucket
    if _gcs_bucket is None:
        if not settings.gcs_bucket:
            raise RuntimeError("STORAGE_BACKEND=gcs 但未設定 GCS_BUCKET")
        from google.cloud import storage  # 僅在 gcs 模式才 import，避免本機需安裝 SDK

        _gcs_bucket = storage.Client().bucket(settings.gcs_bucket)
    return _gcs_bucket


def _canonical_local_path(rel_path: str) -> Path:
    """相對鍵 → 本機正規路徑（只取檔名，存於 storage_path 下）。"""
    return Path(settings.storage_path) / Path(rel_path).name


def put_bytes(rel_path: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    """將 bytes 寫入指定相對鍵。"""
    if _is_gcs():
        blob = _get_bucket().blob(_normalize_key(rel_path))
        blob.upload_from_string(data, content_type=content_type)
        return

    dest = _canonical_local_path(rel_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def get_bytes(rel_path: str) -> bytes | None:
    """讀取指定相對鍵的 bytes；不存在回傳 None。"""
    if _is_gcs():
        blob = _get_bucket().blob(_normalize_key(rel_path))
        return blob.download_as_bytes() if blob.exists() else None

    # 本機模式：先嘗試傳入的原始路徑（相容測試／既有絕對路徑），
    # 再回退到 storage_path 下的正規檔名位置。
    literal = Path(rel_path)
    if literal.is_file():
        return literal.read_bytes()
    canonical = _canonical_local_path(rel_path)
    return canonical.read_bytes() if canonical.is_file() else None


def exists(rel_path: str) -> bool:
    """檢查指定相對鍵是否存在。"""
    if _is_gcs():
        return _get_bucket().blob(_normalize_key(rel_path)).exists()
    return Path(rel_path).is_file() or _canonical_local_path(rel_path).is_file()


def delete(rel_path: str) -> None:
    """刪除指定相對鍵（不存在則靜默略過）。"""
    if _is_gcs():
        blob = _get_bucket().blob(_normalize_key(rel_path))
        if blob.exists():
            blob.delete()
        return

    # 本機模式：原始路徑與正規路徑都嘗試刪除
    Path(rel_path).unlink(missing_ok=True)
    _canonical_local_path(rel_path).unlink(missing_ok=True)
