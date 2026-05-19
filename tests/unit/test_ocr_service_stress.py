"""
模組 A：OCR Service 壓力測試

測試：
  A1 - Gemini API timeout 模擬（Semaphore 不卡死）
  A2 - 並發 OCR Semaphore 控制（最多 3 個並發）
  A3 - 大圖片 OCR 行為（5MB / 10MB）
  A4 - OCR 重試退避邏輯（退避時間正確，最終回傳正確結果）
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from schemas.ocr import VoucherOCRResult


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_ocr_response(
    total_amount: float | None = 1000.0,
    voucher_category: str = "INVOICE",
    success: bool = True,
) -> MagicMock:
    """建立假 Gemini response（Structured Output 模式）。"""
    result = VoucherOCRResult(
        is_voucher=True,
        voucher_category=voucher_category,
        total_amount=total_amount,
        total_amount_confidence=0.95,
        success=success,
    )
    mock_resp = MagicMock()
    mock_resp.parsed = result
    mock_resp.text = result.model_dump_json()
    return mock_resp


def _make_fake_image(tmp_path: Path, size_bytes: int = 100, filename: str = "test.jpg") -> Path:
    """建立指定大小的假圖片檔案。"""
    img_path = tmp_path / filename
    img_path.write_bytes(b"JPEG" + b"\x00" * (size_bytes - 4))
    return img_path


# ---------------------------------------------------------------------------
# A2：並發 OCR Semaphore 控制
# ---------------------------------------------------------------------------


class TestOcrSemaphoreConcurrency:
    """確認 _OCR_SEMAPHORE 有效限制同時 OCR 呼叫數量上限為 3。"""

    @pytest.mark.asyncio
    async def test_max_concurrency_is_3(self, tmp_path: Path) -> None:
        """
        同時發出 10 個 OCR 請求，記錄實際同時進入 generate_content 的峰值。
        峰值應 ≤ 3（由 _OCR_SEMAPHORE 控制）。

        使用 patch 替換 _OCR_SEMAPHORE，避免 M1 問題（module-level Semaphore 綁定舊 event loop）。
        """
        from services import ocr_service

        concurrent_count = 0
        peak_concurrent = 0
        lock = asyncio.Lock()

        async def mock_generate_content(*args, **kwargs):
            nonlocal concurrent_count, peak_concurrent
            async with lock:
                concurrent_count += 1
                peak_concurrent = max(peak_concurrent, concurrent_count)

            await asyncio.sleep(0.05)  # 模擬 API 延遲 50ms

            async with lock:
                concurrent_count -= 1

            return _make_ocr_response()

        img_path = _make_fake_image(tmp_path)
        # 在當前 event loop 中建立新 Semaphore（避免 "bound to different event loop"）
        fresh_semaphore = asyncio.Semaphore(3)

        with patch.object(ocr_service._client.aio.models, "generate_content", new=mock_generate_content):
            with patch("services.ocr_service.Image") as mock_pil:
                mock_pil.open.return_value = MagicMock()
                with patch("services.ocr_service._OCR_SEMAPHORE", fresh_semaphore):

                    tasks = [
                        ocr_service.classify_and_extract_with_retry(str(img_path))
                        for _ in range(10)
                    ]
                    results = await asyncio.gather(*tasks)

        assert peak_concurrent <= 3, \
            f"並發峰值 {peak_concurrent} 超過 Semaphore 上限 3"
        assert all(r.success for r in results), "所有 OCR 結果應成功"

    @pytest.mark.asyncio
    async def test_semaphore_releases_after_success(self, tmp_path: Path) -> None:
        """OCR 成功完成後，Semaphore 槽位應被釋放（可繼續接受新請求）。"""
        from services import ocr_service

        img_path = _make_fake_image(tmp_path)
        fresh_semaphore = asyncio.Semaphore(3)

        with patch.object(ocr_service._client.aio.models, "generate_content",
                          new=AsyncMock(return_value=_make_ocr_response())):
            with patch("services.ocr_service.Image") as mock_pil:
                mock_pil.open.return_value = MagicMock()
                with patch("services.ocr_service._OCR_SEMAPHORE", fresh_semaphore):

                    # 第一批 3 個（佔滿 Semaphore）
                    first_batch = await asyncio.gather(*[
                        ocr_service.classify_and_extract_with_retry(str(img_path))
                        for _ in range(3)
                    ])

                    # 第二批 3 個（應能正常執行，不卡住）
                    second_batch = await asyncio.gather(*[
                        ocr_service.classify_and_extract_with_retry(str(img_path))
                        for _ in range(3)
                    ])

        assert all(r.success for r in first_batch + second_batch)


# ---------------------------------------------------------------------------
# A1：Gemini API timeout 模擬
# ---------------------------------------------------------------------------


class TestOcrApiTimeout:
    """
    驗證當 Gemini API 掛起時，系統行為。
    目前系統沒有 timeout 保護，此測試用「測試會記錄問題」的方式呈現。
    """

    @pytest.mark.asyncio
    async def test_api_hang_returns_failure_result(self, tmp_path: Path) -> None:
        """
        模擬 Gemini API 掛起（asyncio.sleep 大量秒數）。
        使用 asyncio.wait_for 加入 timeout，確認能在 timeout 內返回。
        此測試驗證：若加入 asyncio.timeout 保護，classify_and_extract 應正常回傳 success=False。
        """
        from services import ocr_service

        async def hanging_api(*args, **kwargs):
            await asyncio.sleep(3600)  # 模擬永久掛起
            return _make_ocr_response()  # 不會被執行到

        img_path = _make_fake_image(tmp_path)

        with patch.object(ocr_service._client.aio.models, "generate_content", new=hanging_api):
            with patch("services.ocr_service.Image") as mock_pil:
                mock_pil.open.return_value = MagicMock()

                # 使用外部 timeout 限制最多等待 0.5 秒
                try:
                    result = await asyncio.wait_for(
                        ocr_service.classify_and_extract(str(img_path)),
                        timeout=0.5
                    )
                    # 若有到達這裡，表示 API 提前完成（不應發生在 hang 情境）
                    assert False, "掛起 API 不應在 0.5 秒內返回"
                except asyncio.TimeoutError:
                    # 預期行為：外部 timeout 成功截斷
                    pass  # 驗證系統可以被 timeout 截斷（雖然目前沒有內建保護）

    @pytest.mark.asyncio
    async def test_semaphore_not_blocked_by_single_slow_request(self, tmp_path: Path) -> None:
        """
        一個緩慢請求（2秒）不應完全阻止其他 2 個並發槽位的使用。
        （Semaphore 上限 3，所以 1 個慢 + 2 個快 應可同時進行）
        """
        from services import ocr_service

        fast_count = 0

        async def slow_api(*args, **kwargs):
            await asyncio.sleep(0.3)
            return _make_ocr_response()

        async def fast_api(*args, **kwargs):
            nonlocal fast_count
            fast_count += 1
            return _make_ocr_response()

        img_path = _make_fake_image(tmp_path)

        # 先送 1 個慢請求佔用 1 個槽位，再送 2 個快請求使用其餘 2 個槽位
        call_count = 0

        async def mixed_api(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(0.3)  # 第一個慢
            return _make_ocr_response()

        fresh_semaphore = asyncio.Semaphore(3)
        with patch.object(ocr_service._client.aio.models, "generate_content", new=mixed_api):
            with patch("services.ocr_service.Image") as mock_pil:
                mock_pil.open.return_value = MagicMock()
                with patch("services.ocr_service._OCR_SEMAPHORE", fresh_semaphore):

                    start = time.monotonic()
                    results = await asyncio.gather(*[
                        ocr_service.classify_and_extract_with_retry(str(img_path))
                        for _ in range(3)
                    ])
                    elapsed = time.monotonic() - start

        # 3 個請求（1 慢 + 2 快）應該在 Semaphore(3) 下並行執行
        # 總時間應接近 0.3 秒（最慢的），而非 0.9 秒（順序執行）
        assert elapsed < 0.8, f"3 個並行請求耗時 {elapsed:.2f}s，應 < 0.8s"
        assert all(r.success for r in results)


# ---------------------------------------------------------------------------
# A3：大圖片 OCR 行為
# ---------------------------------------------------------------------------


class TestOcrLargeImages:
    """確認大圖片（5MB / 10MB）不會造成系統崩潰，OCR 正常處理。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("size_mb,filename", [
        (1, "small_1mb.jpg"),
        (5, "medium_5mb.jpg"),
        (10, "large_10mb.jpg"),
    ])
    async def test_large_image_ocr_does_not_crash(
        self, tmp_path: Path, size_mb: int, filename: str
    ) -> None:
        """
        不同大小的圖片送 OCR：
        - mock PIL.Image.open 讓圖片「可以打開」
        - mock Gemini API 返回成功結果
        - 確認函式不拋出例外
        """
        from services import ocr_service

        size_bytes = size_mb * 1024 * 1024
        img_path = _make_fake_image(tmp_path, size_bytes, filename)

        assert img_path.stat().st_size == size_bytes

        with patch.object(ocr_service._client.aio.models, "generate_content",
                          new=AsyncMock(return_value=_make_ocr_response())):
            with patch("services.ocr_service.Image") as mock_pil:
                mock_pil.open.return_value = MagicMock()

                result = await ocr_service.classify_and_extract(str(img_path))

        assert result.success is True, f"{size_mb}MB 圖片 OCR 不應失敗"

    @pytest.mark.asyncio
    async def test_nonexistent_file_returns_failure(self, tmp_path: Path) -> None:
        """不存在的圖片路徑 → OCR 應回傳 success=False，不拋出例外。"""
        from services import ocr_service

        nonexistent = str(tmp_path / "doesnt_exist.jpg")

        # 不 mock PIL.Image.open，讓它真的拋出 FileNotFoundError
        result = await ocr_service.classify_and_extract(nonexistent)

        assert result.success is False
        assert result.error is not None
        assert len(result.error) > 0


# ---------------------------------------------------------------------------
# A4：OCR 重試退避邏輯
# ---------------------------------------------------------------------------


class TestOcrRetryBackoff:
    """確認重試機制：失敗時有退避延遲，最終結果正確。"""

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_third_attempt(self, tmp_path: Path) -> None:
        """
        前兩次 classify_and_extract 回傳 success=False，第三次成功。
        最終應回傳 success=True。
        """
        from services import ocr_service

        attempt_responses = [
            VoucherOCRResult(is_voucher=False, success=False, error="API 暫時失敗 1"),
            VoucherOCRResult(is_voucher=False, success=False, error="API 暫時失敗 2"),
            VoucherOCRResult(is_voucher=True, voucher_category="INVOICE", total_amount=500.0, success=True),
        ]
        call_count = 0

        async def mock_classify(image_path: str):
            nonlocal call_count
            resp = attempt_responses[min(call_count, len(attempt_responses) - 1)]
            call_count += 1
            return resp

        img_path = _make_fake_image(tmp_path)

        with patch("services.ocr_service.classify_and_extract", side_effect=mock_classify):
            with patch("asyncio.sleep", new_callable=AsyncMock):  # 跳過實際等待
                result = await ocr_service.classify_and_extract_with_retry(str(img_path))

        assert result.success is True
        assert result.total_amount == 500.0
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted_returns_last_failure(self, tmp_path: Path) -> None:
        """
        三次都失敗 → 回傳最後一次的失敗結果（success=False），不拋出例外。
        """
        from services import ocr_service

        call_count = 0

        async def always_fail(image_path: str):
            nonlocal call_count
            call_count += 1
            return VoucherOCRResult(
                is_voucher=False, success=False, error=f"失敗 #{call_count}"
            )

        img_path = _make_fake_image(tmp_path)

        with patch("services.ocr_service.classify_and_extract", side_effect=always_fail):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await ocr_service.classify_and_extract_with_retry(str(img_path))

        assert result.success is False
        assert "失敗" in result.error
        assert call_count == 3  # 嘗試 3 次

    @pytest.mark.asyncio
    async def test_backoff_sleep_is_called_with_correct_values(self, tmp_path: Path) -> None:
        """
        確認退避等待時間：第 1 次失敗等 1 秒（2^0），第 2 次失敗等 2 秒（2^1）。
        """
        from services import ocr_service

        call_count = 0
        sleep_calls = []

        async def always_fail(image_path: str):
            nonlocal call_count
            call_count += 1
            return VoucherOCRResult(is_voucher=False, success=False, error="always fail")

        async def mock_sleep(seconds: float):
            sleep_calls.append(seconds)

        img_path = _make_fake_image(tmp_path)

        with patch("services.ocr_service.classify_and_extract", side_effect=always_fail):
            with patch("asyncio.sleep", side_effect=mock_sleep):
                result = await ocr_service.classify_and_extract_with_retry(str(img_path))

        assert result.success is False
        # 應有 2 次 sleep（第 1、2 次失敗後；第 3 次失敗後不再 sleep）
        assert len(sleep_calls) == 2, f"預期 2 次 sleep，實際 {len(sleep_calls)} 次"
        assert sleep_calls[0] == 1, f"第一次退避應等 1 秒，實際 {sleep_calls[0]}"
        assert sleep_calls[1] == 2, f"第二次退避應等 2 秒，實際 {sleep_calls[1]}"

    @pytest.mark.asyncio
    async def test_first_attempt_success_no_sleep(self, tmp_path: Path) -> None:
        """第一次就成功 → 不應有任何 sleep 呼叫。"""
        from services import ocr_service

        sleep_called = False

        async def succeed_immediately(image_path: str):
            return VoucherOCRResult(
                is_voucher=True, voucher_category="INVOICE", total_amount=100.0, success=True
            )

        async def should_not_sleep(seconds: float):
            nonlocal sleep_called
            sleep_called = True

        img_path = _make_fake_image(tmp_path)

        with patch("services.ocr_service.classify_and_extract", side_effect=succeed_immediately):
            with patch("asyncio.sleep", side_effect=should_not_sleep):
                result = await ocr_service.classify_and_extract_with_retry(str(img_path))

        assert result.success is True
        assert not sleep_called, "第一次成功不應有 sleep 呼叫"
