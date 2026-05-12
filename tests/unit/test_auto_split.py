"""
Unit tests for Sprint 3 auto-split logic.

涵蓋範圍：
- multi_split_logic()：各種切割場景（純函式，無 DB / 網路依賴）
- _parse_buffer()：新舊格式解析 + timestamp 排序
- auto_split_timer：schedule / cancel / 滑動視窗行為
"""

import asyncio
import json
import sys
from unittest.mock import MagicMock

# 在所有 app import 前 patch psycopg2（測試環境無 PostgreSQL）
_fake_psycopg2 = MagicMock()
_fake_psycopg2.__version__ = "2.9.9"
sys.modules.setdefault("psycopg2", _fake_psycopg2)
sys.modules.setdefault("psycopg2.extensions", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())

import pytest

from services.auto_split_service import _ImageEntry, _parse_buffer, multi_split_logic
from schemas.ocr import VoucherOCRResult


# ---------------------------------------------------------------------------
# 輔助工廠
# ---------------------------------------------------------------------------

def _entry(path: str, timestamp: int = 0, message_id: str = "") -> _ImageEntry:
    return _ImageEntry(path=path, timestamp=timestamp, message_id=message_id)


def _voucher_ocr(category: str = "INVOICE", amount: float = 1000.0) -> VoucherOCRResult:
    return VoucherOCRResult(
        is_voucher=True,
        voucher_category=category,
        total_amount=amount,
        success=True,
    )


def _non_voucher_ocr() -> VoucherOCRResult:
    return VoucherOCRResult(
        is_voucher=False,
        success=True,
    )


# ---------------------------------------------------------------------------
# multi_split_logic — 切割規則測試
# ---------------------------------------------------------------------------

class TestMultiSplitLogic:
    def test_split_empty_input(self):
        """空輸入 → 回傳空清單"""
        result = multi_split_logic([], [])
        assert result == []

    def test_split_single_voucher(self):
        """1 張憑證 → 1 個群組"""
        entries = [_entry("a.jpg")]
        ocr = [_voucher_ocr()]
        groups = multi_split_logic(entries, ocr)
        assert len(groups) == 1
        assert groups[0][0] == ["a.jpg"]

    def test_split_voucher_with_items(self):
        """1 張憑證 + 2 張物品照 → 1 個群組（3 張）"""
        entries = [_entry("v.jpg"), _entry("i1.jpg"), _entry("i2.jpg")]
        ocr = [_voucher_ocr(), _non_voucher_ocr(), _non_voucher_ocr()]
        groups = multi_split_logic(entries, ocr)
        assert len(groups) == 1
        assert groups[0][0] == ["v.jpg", "i1.jpg", "i2.jpg"]
        assert len(groups[0][1]) == 3

    def test_split_two_vouchers_no_items(self):
        """2 張憑證（無物品照）→ 2 個群組，各 1 張"""
        entries = [_entry("v1.jpg"), _entry("v2.jpg")]
        ocr = [_voucher_ocr(), _voucher_ocr("RECEIPT")]
        groups = multi_split_logic(entries, ocr)
        assert len(groups) == 2
        assert groups[0][0] == ["v1.jpg"]
        assert groups[1][0] == ["v2.jpg"]

    def test_split_two_vouchers_with_items(self):
        """2 張憑證各帶 1 張物品照 → 2 個群組"""
        entries = [
            _entry("v1.jpg"), _entry("i1.jpg"),
            _entry("v2.jpg"), _entry("i2.jpg"),
        ]
        ocr = [_voucher_ocr(), _non_voucher_ocr(), _voucher_ocr("RECEIPT"), _non_voucher_ocr()]
        groups = multi_split_logic(entries, ocr)
        assert len(groups) == 2
        assert groups[0][0] == ["v1.jpg", "i1.jpg"]
        assert groups[1][0] == ["v2.jpg", "i2.jpg"]

    def test_split_non_voucher_first(self):
        """第 1 張非憑證 → 獨立成一筆；第 2 張憑證開啟新群組"""
        entries = [_entry("item.jpg"), _entry("v.jpg")]
        ocr = [_non_voucher_ocr(), _voucher_ocr()]
        groups = multi_split_logic(entries, ocr)
        assert len(groups) == 2
        assert groups[0][0] == ["item.jpg"]
        assert groups[1][0] == ["v.jpg"]

    def test_split_all_non_vouchers(self):
        """全部非憑證 → 每張各自一筆"""
        entries = [_entry("a.jpg"), _entry("b.jpg"), _entry("c.jpg")]
        ocr = [_non_voucher_ocr(), _non_voucher_ocr(), _non_voucher_ocr()]
        groups = multi_split_logic(entries, ocr)
        assert len(groups) == 3
        assert groups[0][0] == ["a.jpg"]
        assert groups[1][0] == ["b.jpg"]
        assert groups[2][0] == ["c.jpg"]

    def test_split_preserves_ocr_results(self):
        """OCR 結果與 image_paths 一一對應，切割後不錯亂"""
        entries = [_entry("v1.jpg"), _entry("v2.jpg")]
        ocr_v1 = _voucher_ocr("INVOICE", 100.0)
        ocr_v2 = _voucher_ocr("RECEIPT", 200.0)
        groups = multi_split_logic(entries, [ocr_v1, ocr_v2])
        assert groups[0][1][0].total_amount == 100.0
        assert groups[1][1][0].total_amount == 200.0


# ---------------------------------------------------------------------------
# _parse_buffer — 格式解析測試
# ---------------------------------------------------------------------------

class TestParseBuffer:
    def test_parse_empty_string(self):
        """空字串 / '[]' → 空清單"""
        assert _parse_buffer("") == []
        assert _parse_buffer("[]") == []

    def test_parse_new_format(self):
        """新格式（dict with path/timestamp/message_id）正確解析"""
        raw = json.dumps([
            {"path": "a.jpg", "timestamp": 2000, "message_id": "msg2"},
            {"path": "b.jpg", "timestamp": 1000, "message_id": "msg1"},
        ])
        entries = _parse_buffer(raw)
        # 應依 timestamp ASC 排序
        assert len(entries) == 2
        assert entries[0].path == "b.jpg"
        assert entries[0].timestamp == 1000
        assert entries[1].path == "a.jpg"
        assert entries[1].timestamp == 2000

    def test_parse_old_format_backward_compat(self):
        """舊格式（純字串路徑）→ timestamp=0 兜底，不 raise error"""
        raw = json.dumps(["path1.jpg", "path2.jpg"])
        entries = _parse_buffer(raw)
        assert len(entries) == 2
        assert entries[0].path in ("path1.jpg", "path2.jpg")
        assert entries[0].timestamp == 0
        assert entries[0].message_id == ""

    def test_parse_mixed_format(self):
        """混合格式（新舊並存）→ 正常解析，不 raise error"""
        raw = json.dumps([
            {"path": "new.jpg", "timestamp": 500, "message_id": "msg"},
            "old.jpg",
        ])
        entries = _parse_buffer(raw)
        assert len(entries) == 2

    def test_parse_missing_fields_use_defaults(self):
        """新格式缺少部分欄位 → 使用預設值"""
        raw = json.dumps([{"path": "x.jpg"}])
        entries = _parse_buffer(raw)
        assert entries[0].path == "x.jpg"
        assert entries[0].timestamp == 0
        assert entries[0].message_id == ""


# ---------------------------------------------------------------------------
# auto_split_timer — Timer 行為測試
# ---------------------------------------------------------------------------

class TestAutoSplitTimer:
    def test_timer_cancel_before_fire(self):
        """schedule 後立即 cancel → callback 不執行，cancel 返回 True"""
        from services import auto_split_timer

        fired = []

        async def run():
            async def callback():
                fired.append(True)

            auto_split_timer.schedule("user1", delay_seconds=0.05, callback=callback)
            cancelled = auto_split_timer.cancel("user1")
            assert cancelled is True
            # 等待足夠時間確認 callback 未執行
            await asyncio.sleep(0.1)
            assert fired == []

        asyncio.get_event_loop().run_until_complete(run())

    def test_timer_fires_after_delay(self):
        """schedule 後等待超過 delay → callback 執行"""
        from services import auto_split_timer

        fired = []

        async def run():
            async def callback():
                fired.append(True)

            auto_split_timer.schedule("user2", delay_seconds=0.05, callback=callback)
            await asyncio.sleep(0.15)
            assert fired == [True]

        asyncio.get_event_loop().run_until_complete(run())

    def test_timer_sliding_window(self):
        """連續 schedule 重設視窗，只保留最後一個 task（舊 task 被取消）"""
        from services import auto_split_timer

        fired_count = []

        async def run():
            async def callback():
                fired_count.append(1)

            # 快速連續 schedule 3 次（間距 0.05s << 延遲 0.3s，確保前兩個被取消）
            # Windows asyncio.sleep 精度約 15ms，需拉大間距避免 timing race
            auto_split_timer.schedule("user3", delay_seconds=0.3, callback=callback)
            await asyncio.sleep(0.05)
            auto_split_timer.schedule("user3", delay_seconds=0.3, callback=callback)
            await asyncio.sleep(0.05)
            auto_split_timer.schedule("user3", delay_seconds=0.3, callback=callback)
            # 等待最後一次 delay 結束（0.1 + 0.3 + 0.1 margin）
            await asyncio.sleep(0.5)
            # 只應觸發一次
            assert len(fired_count) == 1

        asyncio.get_event_loop().run_until_complete(run())

    def test_cancel_nonexistent_user_returns_false(self):
        """對不存在的 user_id 執行 cancel → 返回 False，不 raise"""
        from services import auto_split_timer
        result = auto_split_timer.cancel("nonexistent_user_xyz")
        assert result is False

    def test_active_count(self):
        """active_count 正確反映活躍 timer 數量"""
        from services import auto_split_timer

        async def run():
            async def noop():
                pass

            initial = auto_split_timer.active_count()
            auto_split_timer.schedule("count_user_a", 10.0, noop)
            auto_split_timer.schedule("count_user_b", 10.0, noop)
            assert auto_split_timer.active_count() == initial + 2
            auto_split_timer.cancel("count_user_a")
            auto_split_timer.cancel("count_user_b")
            assert auto_split_timer.active_count() == initial

        asyncio.get_event_loop().run_until_complete(run())
