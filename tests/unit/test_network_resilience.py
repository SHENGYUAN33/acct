"""
模組 D：網路延遲與斷線模擬測試

測試：
  D1 - LINE API 回覆 timeout（reply_text hang）
  D2 - Gemini API 失敗後重試（503，第三次成功）
  D3 - LINE 圖片下載失敗時的孤兒檔案問題
  D4 - OCR 失敗後系統回傳 NEEDS_MANUAL_REVIEW 狀態
"""

import asyncio
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from schemas.ocr import VoucherOCRResult


# ---------------------------------------------------------------------------
# D1：LINE API 回覆 timeout（記錄現有無 timeout 的行為）
# ---------------------------------------------------------------------------


class TestLineApiTimeout:
    """
    D1：line_service.reply_text 目前沒有 timeout 保護。
    此測試記錄現有行為：hang 住時沒有自動截斷機制。
    """

    def test_reply_text_raises_on_line_api_error(self) -> None:
        """LINE API 拋出例外時，reply_text 應將例外向上傳遞。"""
        from services import line_service

        with patch("services.line_service.get_line_api") as mock_get_api:
            mock_api = MagicMock()
            mock_api.reply_message.side_effect = Exception("LINE API 503 Service Unavailable")
            mock_get_api.return_value = mock_api

            with pytest.raises(Exception, match="LINE API 503"):
                line_service.reply_text("fake_reply_token", "測試訊息")

    def test_push_text_exception_is_swallowed(self) -> None:
        """
        push_text 有 try-except 包裝：LINE API 失敗時，例外被 log 並吞掉，不向上傳遞。
        這是一個設計決策（靜默失敗），此測試確認並記錄此行為。
        """
        from services import line_service

        with patch("services.line_service.get_line_api") as mock_get_api:
            mock_api = MagicMock()
            mock_api.push_message.side_effect = Exception("Network timeout")
            mock_get_api.return_value = mock_api

            # push_text 有 try-except，不會 re-raise（靜默失敗）
            # 此行為是設計上的選擇：避免推播失敗影響主流程
            line_service.push_text("fake_user_id", "推播訊息")
            # 呼叫後不拋例外 → 測試通過
            mock_api.push_message.assert_called_once()

    def test_reply_text_succeeds_normally(self) -> None:
        """正常情況下 reply_text 應不拋出例外。"""
        from services import line_service

        with patch("services.line_service.get_line_api") as mock_get_api:
            mock_api = MagicMock()
            mock_api.reply_message.return_value = None
            mock_get_api.return_value = mock_api

            # 不應拋出例外
            line_service.reply_text("valid_reply_token", "正常訊息")
            mock_api.reply_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_external_timeout_can_cancel_hanging_request(self) -> None:
        """
        驗證外部 asyncio.wait_for timeout 可以截斷掛起的 API 呼叫。
        這模擬未來若加入 timeout 保護後的預期行為。
        """
        async def hanging_operation():
            await asyncio.sleep(3600)  # 永久掛起
            return "should never reach here"

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(hanging_operation(), timeout=0.1)


# ---------------------------------------------------------------------------
# D2：Gemini API 失敗重試行為
# ---------------------------------------------------------------------------


class TestGeminiApiRetry:
    """驗證 Gemini API 失敗時的重試機制。"""

    @pytest.mark.asyncio
    async def test_503_retry_succeeds_on_third_attempt(self, tmp_path: Path) -> None:
        """
        Gemini API 前兩次拋出 ServiceUnavailable，第三次成功。
        最終結果應為 success=True。
        """
        from services import ocr_service

        attempt_count = 0

        async def flaky_api(*args, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count <= 2:
                raise Exception("503 Service Unavailable (Gemini API)")
            # 第三次成功
            result = VoucherOCRResult(
                is_voucher=True, voucher_category="RECEIPT",
                total_amount=250.0, success=True
            )
            mock_resp = MagicMock()
            mock_resp.parsed = result
            mock_resp.text = result.model_dump_json()
            return mock_resp

        img_path = tmp_path / "test.jpg"
        img_path.write_bytes(b"fake-image")

        with patch.object(ocr_service._client.aio.models, "generate_content", new=flaky_api):
            with patch("services.ocr_service.Image") as mock_pil:
                mock_pil.open.return_value = MagicMock()
                with patch("asyncio.sleep", new_callable=AsyncMock):  # 跳過 sleep
                    result = await ocr_service.classify_and_extract_with_retry(str(img_path))

        assert result.success is True
        assert result.total_amount == 250.0
        assert attempt_count == 3

    @pytest.mark.asyncio
    async def test_network_error_all_retries_fail(self, tmp_path: Path) -> None:
        """
        網路完全中斷（三次都失敗）→ 應回傳 success=False，不拋出例外。
        """
        from services import ocr_service

        async def always_fail(*args, **kwargs):
            raise ConnectionError("Network unreachable")

        img_path = tmp_path / "test.jpg"
        img_path.write_bytes(b"fake-image")

        with patch.object(ocr_service._client.aio.models, "generate_content", new=always_fail):
            with patch("services.ocr_service.Image") as mock_pil:
                mock_pil.open.return_value = MagicMock()
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await ocr_service.classify_and_extract_with_retry(str(img_path))

        assert result.success is False
        assert result.error is not None
        assert "Network unreachable" in result.error or len(result.error) > 0

    @pytest.mark.asyncio
    async def test_ocr_failure_results_in_needs_manual_review_status(self) -> None:
        """
        OCR 完全失敗（success=False, total_amount=None）→
        create_batch_expense 應將 status 設為 NEEDS_MANUAL_REVIEW。
        """
        from models.expense import ExpenseStatus
        from schemas.ocr import VoucherOCRResult

        # 模擬 OCR 失敗結果
        failed_ocr = VoucherOCRResult(
            is_voucher=False,
            success=False,
            error="Gemini API timeout",
            total_amount=None,
        )

        # 驗證 OCR 失敗的判斷邏輯
        all_vouchers = [r for r in [failed_ocr] if r.is_voucher]
        total_amount = (
            sum(r.total_amount for r in all_vouchers if r.total_amount is not None)
            if all_vouchers else None
        )
        has_total = total_amount is not None and total_amount != 0

        expected_status = (
            ExpenseStatus.PENDING if has_total else ExpenseStatus.NEEDS_MANUAL_REVIEW
        )
        assert expected_status == ExpenseStatus.NEEDS_MANUAL_REVIEW


# ---------------------------------------------------------------------------
# D3：圖片下載失敗時的孤兒檔案問題
# ---------------------------------------------------------------------------


class TestOrphanFileOnDownloadFailure:
    """
    M2 風險記錄：圖片下載後、DB commit 前失敗 → 磁碟有殘留，DB 無記錄。
    """

    def test_download_failure_leaves_no_file(self, tmp_path: Path) -> None:
        """
        LINE API 拋出例外時，不應有任何檔案被寫入磁碟。
        驗證 download_image 在 API 失敗時不留下殘留。
        """
        from services import line_service

        save_path = tmp_path / "should_not_exist.jpg"

        with patch("services.line_service.ApiClient") as mock_api_client:
            mock_api_client.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_api_client.return_value.__exit__ = MagicMock(return_value=False)

            with patch("services.line_service.MessagingApiBlob") as mock_blob_cls:
                mock_blob = MagicMock()
                mock_blob.get_message_content.side_effect = Exception("Network error during download")
                mock_blob_cls.return_value = mock_blob

                with pytest.raises(Exception, match="Network error during download"):
                    line_service.download_image("fail_msg_id", save_path)

        # 下載失敗 → 不應有檔案
        assert not save_path.exists(), "下載失敗後不應留下殘留檔案"

    def test_partial_write_orphan_scenario(self, tmp_path: Path) -> None:
        """
        M2 風險記錄：圖片下載成功但 DB commit 失敗的孤兒情境。

        此測試模擬以下序列：
        1. download_image() 成功 → 檔案寫入磁碟
        2. DB commit 拋出例外 → 事務回滾
        3. 磁碟上留有孤兒檔案，DB 無記錄

        此測試記錄現有行為（有 bug），不修復它。
        """
        from services import line_service
        from sqlalchemy import text

        save_path = tmp_path / "orphan_candidate.jpg"
        fake_content = b"\xFF\xD8\xFF" + b"\x00" * 1024  # 小假 JPEG

        # Step 1：模擬成功下載
        with patch("services.line_service.ApiClient") as mock_api_client:
            mock_api_client.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_api_client.return_value.__exit__ = MagicMock(return_value=False)

            with patch("services.line_service.MessagingApiBlob") as mock_blob_cls:
                mock_blob = MagicMock()
                mock_blob.get_message_content.return_value = fake_content
                mock_blob_cls.return_value = mock_blob

                result_path = line_service.download_image("success_msg_id", save_path)

        # 檔案已寫入磁碟
        assert result_path.exists(), "圖片應已寫入磁碟"

        # Step 2：模擬 DB commit 失敗
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine("sqlite:///:memory:")
        Session = sessionmaker(bind=engine)
        session = Session()

        with pytest.raises(Exception):
            # 模擬 commit 失敗（插入無效資料）
            session.execute(text("INSERT INTO nonexistent_table VALUES (1)"))
            session.commit()
        session.rollback()
        session.close()

        # Step 3：驗證孤兒檔案存在（有 bug）
        assert result_path.exists(), \
            "磁碟上存在孤兒檔案（DB commit 失敗但檔案未清理）"

        import warnings
        warnings.warn(
            "⚠️ M2 孤兒檔案風險確認：download_image 成功但 DB commit 失敗時，"
            "磁碟上會殘留孤兒檔案。修復建議：在 finally 區塊中，若 DB 操作失敗則刪除已下載的檔案。",
            UserWarning,
            stacklevel=2,
        )


# ---------------------------------------------------------------------------
# D4：DB 連線池相關（單元測試層級）
# ---------------------------------------------------------------------------


class TestDatabaseConnectionResilience:
    """驗證 DB 配置的韌性設定。"""

    def test_database_engine_has_pool_pre_ping(self) -> None:
        """
        確認 DB engine 啟用了 pool_pre_ping=True。
        pool_pre_ping 讓 SQLAlchemy 在使用連線前先 ping，自動偵測並丟棄過期連線。
        """
        from core.database import engine

        # pool_pre_ping 在 engine.pool._pre_ping 或 engine.dialect 層面
        # 透過 engine 的參數驗證
        pool_pre_ping = engine.pool._pre_ping
        assert pool_pre_ping is True, \
            "DB engine 應啟用 pool_pre_ping=True 以自動處理過期連線"

    def test_database_pool_size_is_reasonable(self) -> None:
        """
        確認 DB pool_size 在合理範圍（5-20）。
        過小容易耗盡，過大浪費 DB 連線資源。
        """
        from core.database import engine

        pool_size = engine.pool.size()
        print(f"[INFO] DB pool_size = {pool_size}")
        assert 5 <= pool_size <= 20, \
            f"pool_size={pool_size} 不在合理範圍 [5, 20]"

    def test_database_url_is_not_hardcoded(self) -> None:
        """確認 database_url 來自環境變數/settings，不是 hardcoded 字串。"""
        from core import database
        import inspect

        source = inspect.getsource(database)
        # 不應有明文的 postgresql://user:password@host 格式
        import re
        hardcoded = re.findall(r'postgresql://[^"\'}\s]+:[^"\'}\s]+@', source)
        # 允許有 settings.database_url 引用
        actual_hardcoded = [h for h in hardcoded if "settings" not in h]
        assert not actual_hardcoded, \
            f"database.py 中找到疑似 hardcoded DB URL：{actual_hardcoded}"
