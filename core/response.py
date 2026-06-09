"""統一 API 回應格式工具。

所有 Router 端點的回傳值必須透過此模組的 ok() 產生，
確保格式一致：{"status": "success"|"error", "data": ..., "message": "..."}

曾有 50+ 個端點各自手動拼裝 dict，導致：
  1. 格式容易打錯（如 "succcess"）
  2. 新增欄位需要全站搜尋修改
  3. 無法統一在一處加入 logging 或 tracing header
"""

from typing import Any


def ok(data: Any = None, message: str = "ok") -> dict:
    """回傳成功回應。"""
    return {"status": "success", "data": data, "message": message}
