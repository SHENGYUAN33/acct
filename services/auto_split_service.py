"""
憑證切割邏輯（Sprint 3）

提供 LIFF 批次送出共用的純切割工具：
  - multi_split_logic / multi_split_logic_v2：以 is_voucher=True 的圖片作為斷點切割群組
  - distribute_description*：將備註文字分配到各群組
  - _ImageEntry / _parse_buffer：pending buffer 結構與解析

註：原「60 秒自動切割 Timer」與「每日排程批次」功能已移除（不相容 Cloud Run 無狀態架構），
    本模組僅保留 LIFF 流程實際使用的純函式。
"""

import json
import logging
from dataclasses import dataclass

from schemas.ocr import VoucherOCRResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Buffer 結構：新格式含 timestamp / message_id，舊格式純字串向後相容
# ---------------------------------------------------------------------------

@dataclass
class _ImageEntry:
    path: str
    timestamp: int      # LINE event.timestamp（毫秒 Unix），用於排序
    message_id: str     # LINE message ID，保留供 debug trace


def _parse_buffer(pending_images_json: str) -> list[_ImageEntry]:
    """
    解析 pending_images JSON 字串，回傳依 timestamp ASC 排序的 _ImageEntry 清單。

    - 新格式：[{"path": "...", "timestamp": 1714..., "message_id": "..."}, ...]
    - 舊格式（Sprint 2）：["path1.jpg", "path2.jpg", ...]
      → timestamp=0 兜底，不 raise error（backward compat）
    """
    raw: list = json.loads(pending_images_json or "[]")
    entries: list[_ImageEntry] = []
    for item in raw:
        if isinstance(item, dict):
            entries.append(
                _ImageEntry(
                    path=item.get("path", ""),
                    timestamp=item.get("timestamp", 0),
                    message_id=item.get("message_id", ""),
                )
            )
        elif isinstance(item, str):
            # 舊格式相容：純路徑字串
            entries.append(_ImageEntry(path=item, timestamp=0, message_id=""))
    return sorted(entries, key=lambda e: e.timestamp)


# ---------------------------------------------------------------------------
# 核心切割函式（純函式，無副作用，易單元測試）
# ---------------------------------------------------------------------------

def multi_split_logic(
    entries: list[_ImageEntry],
    ocr_results: list[VoucherOCRResult],
) -> list[tuple[list[str], list[VoucherOCRResult]]]:
    """
    以 is_voucher=True 的圖片為群組起點切割批次。
    - 出現在第一個憑證之前的非憑證圖：各自獨立建一個群組
    - 出現在某個憑證之後的非憑證圖：歸入前一個憑證的群組
    """
    if not entries:
        return []

    groups: list[tuple[list[str], list[VoucherOCRResult]]] = []
    current_paths: list[str] = []
    current_ocr: list[VoucherOCRResult] = []
    has_seen_voucher = False

    for entry, result in zip(entries, ocr_results):
        if result.success and result.is_voucher:
            if current_paths:
                groups.append((current_paths, current_ocr))
            current_paths = [entry.path]
            current_ocr = [result]
            has_seen_voucher = True
        else:
            if not has_seen_voucher:
                # 第一個憑證之前的非憑證圖 → 各自獨立建群組
                groups.append(([entry.path], [result]))
            else:
                current_paths.append(entry.path)
                current_ocr.append(result)

    if current_paths:
        groups.append((current_paths, current_ocr))

    return groups


def multi_split_logic_v2(
    entries: list[_ImageEntry],
    ocr_results: list[VoucherOCRResult],
) -> tuple[list[tuple[list[str], list[VoucherOCRResult]]], list[str]]:
    """
    兩階段切割：先掃描整個 batch 找出所有 is_voucher=True，再分組。

    Phase 1 — 掃描整個 batch，識別所有憑證的索引位置。
    Phase 2 — 以每個憑證為群組起點；第一個憑證「之前」的非憑證圖
              歸入 orphan_paths（需呼叫者向前關聯 DB 最近的報帳）。

    回傳：
        groups      — [(image_paths, ocr_results), ...]  每筆對應一個 Expense
        orphan_paths — batch 開頭的孤立物品圖路徑清單
    """
    if not entries:
        return [], []

    voucher_indices = [
        i for i, r in enumerate(ocr_results)
        if r.success and r.is_voucher
    ]

    if not voucher_indices:
        # 整批都是非憑證圖 → 全部歸入 orphan（由呼叫方決定如何處理）
        return [], [e.path for e in entries]

    first_voucher_idx = voucher_indices[0]
    orphan_paths = [entries[i].path for i in range(first_voucher_idx)]

    groups: list[tuple[list[str], list[VoucherOCRResult]]] = []
    current_paths: list[str] = []
    current_ocr: list[VoucherOCRResult] = []

    for i in range(first_voucher_idx, len(entries)):
        entry = entries[i]
        result = ocr_results[i]
        if result.success and result.is_voucher:
            if current_paths:
                groups.append((current_paths, current_ocr))
            current_paths = [entry.path]
            current_ocr = [result]
        else:
            current_paths.append(entry.path)
            current_ocr.append(result)

    if current_paths:
        groups.append((current_paths, current_ocr))

    return groups, orphan_paths


def distribute_description(pending_description: str, num_groups: int) -> list[str]:
    """
    將說明文字分配給各群組。

    支援兩種格式：
    1. 新格式（JSON array）：[{"text": "...", "timestamp": 毫秒Unix}, ...]
       → 純段落分配（此函式不感知圖片時序，時序分配請用 distribute_description_by_timestamps）
    2. 舊格式（純字串）：以雙換行（空行）為段落邊界向後相容
    """
    if num_groups <= 1:
        return [_flatten_description(pending_description)]

    flat = _flatten_description(pending_description)
    if not flat:
        return [""] * num_groups

    paragraphs = [p.strip() for p in flat.split("\n\n") if p.strip()]
    if len(paragraphs) < num_groups:
        return [flat] + [""] * (num_groups - 1)
    return [paragraphs[i] if i < len(paragraphs) else "" for i in range(num_groups)]


def _flatten_description(pending_description: str) -> str:
    """
    將 pending_description 統一轉為純文字。
    新格式（JSON array）→ 合併為 \n\n 分隔段落；舊格式直接回傳。
    """
    if not pending_description:
        return ""
    try:
        entries = json.loads(pending_description)
        if isinstance(entries, list) and entries and isinstance(entries[0], dict):
            return "\n\n".join(e.get("text", "") for e in entries if e.get("text"))
    except Exception:
        pass
    return pending_description


def distribute_description_by_timestamps(
    pending_description: str,
    voucher_timestamps: list[int],
) -> list[str]:
    """
    依時序將備註分配給各憑證群組（治本方案）。

    原理：
    - 每個群組的時間範圍 = [voucher_timestamps[i], voucher_timestamps[i+1])
    - 最後一個群組無右邊界，收集所有剩餘備註
    - 備註的 timestamp 落在哪個區間，就歸入對應群組

    參數：
        pending_description  — UserState.pending_description（JSON array 或舊純字串）
        voucher_timestamps   — 各群組憑證圖的 LINE event.timestamp（毫秒 Unix，ASC 排序）

    回傳：
        各群組的備註字串清單（長度 == len(voucher_timestamps)）
    """
    num_groups = len(voucher_timestamps)
    if num_groups == 0:
        return []
    if num_groups == 1:
        return [_flatten_description(pending_description)]

    # 解析新格式 text entries
    text_entries: list[dict] = []
    try:
        parsed = json.loads(pending_description or "[]")
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            text_entries = sorted(parsed, key=lambda e: e.get("timestamp", 0))
        else:
            # 舊格式：無時序資訊，降級為段落分配
            return distribute_description(pending_description, num_groups)
    except Exception:
        return distribute_description(pending_description, num_groups)

    buckets: list[list[str]] = [[] for _ in range(num_groups)]
    for entry in text_entries:
        ts = entry.get("timestamp", 0)
        text = entry.get("text", "")
        if not text:
            continue
        # 找到此備註所屬的群組（最後一個 voucher timestamp <= 備註 timestamp）
        assigned_group = 0
        for i in range(num_groups - 1, -1, -1):
            if ts >= voucher_timestamps[i]:
                assigned_group = i
                break
        buckets[assigned_group].append(text)

    return ["\n".join(bucket) for bucket in buckets]
