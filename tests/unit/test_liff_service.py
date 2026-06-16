"""
LIFF 批次上傳服務單元測試 — services/liff_service.py

涵蓋情境清單（共 38 個）：
  add_image()                   7 個 — 上傳即回傳、不觸發 OCR、各種錯誤狀態
  submit_session()              7 個 — 立即鎖定、processing_status 設定、各種錯誤狀態
  process_session_background()  16 個 — OCR 成功/失敗、建帳、孤立圖片、模式切換
  patch_image_type()            4 個 — 手動切換、flag 設定、找不到
  get_session_preview()         4 個 — 空 session、單群組、孤立圖片、多群組
"""

# ---------------------------------------------------------------------------
# psycopg2 mock 必須在所有 import 之前（讓 SQLAlchemy PostgreSQL dialect 可載入）
# ---------------------------------------------------------------------------

import sys
from unittest.mock import MagicMock

_fake_psycopg2 = MagicMock()
_fake_psycopg2.extensions = MagicMock()
_fake_psycopg2.__version__ = "2.9.9"
sys.modules.setdefault("psycopg2", _fake_psycopg2)
sys.modules.setdefault("psycopg2.extensions", _fake_psycopg2.extensions)
sys.modules.setdefault("psycopg2.extras", MagicMock())

# ---------------------------------------------------------------------------
# 標準 import
# ---------------------------------------------------------------------------

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from schemas.ocr import VoucherOCRResult
from services import liff_service


# ---------------------------------------------------------------------------
# 資料容器（替代 SQLAlchemy ORM 物件，供 mock 使用）
# ---------------------------------------------------------------------------

@dataclass
class FakeSession:
    """模擬 UploadSession ORM。"""
    line_user_id: str = "U_test_user"
    status: str = "uploading"
    processing_status: str = "pending"
    images: list = field(default_factory=list)
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc) + timedelta(minutes=30)
    )


@dataclass
class FakeImage:
    """模擬 SessionImage ORM。"""
    sequence_order: int = 0
    image_path: str = "uploads/test.jpg"
    is_voucher: bool | None = None
    manually_set: bool = False
    ocr_result: str | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class FakeUser:
    """模擬 User ORM。"""
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    line_user_id: str = "U_test_user"
    real_name: str | None = "測試使用者"
    name: str | None = "Test User"
    department: str | None = "研發部"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def make_voucher_ocr(
    is_voucher: bool = True,
    success: bool = True,
    total_amount: float = 1000.0,
    invoice_number: str = "AB-12345678",
) -> VoucherOCRResult:
    """建立測試用 VoucherOCRResult。"""
    if not success:
        return VoucherOCRResult(success=False, is_voucher=False, error="OCR 辨識失敗")
    return VoucherOCRResult(
        is_voucher=is_voucher,
        success=True,
        voucher_category="INVOICE" if is_voucher else None,
        total_amount=total_amount,
        invoice_number=invoice_number,
    )


def make_mock_db(fake_session: FakeSession, fake_user: FakeUser | None = None) -> MagicMock:
    """建立供 process_session_background() 使用的 mock DB session。"""
    db = MagicMock()
    db.get.return_value = fake_session
    db.scalar.return_value = fake_user
    db.commit.return_value = None
    db.refresh.return_value = None
    db.close.return_value = None
    return db


def _make_expired_session() -> FakeSession:
    sess = FakeSession()
    sess.expires_at = datetime.now(tz=timezone.utc) - timedelta(minutes=1)
    return sess


def _default_settings_mock():
    s = MagicMock()
    s.liff_submit_mode = "single"
    return s


# ---------------------------------------------------------------------------
# TestAddImage — 圖片上傳（OCR 移至背景，不在此執行）
# ---------------------------------------------------------------------------

class TestAddImage:
    """
    測試 add_image() 函式。
    核心特性：上傳圖片後立即回傳，不等待 OCR。
    """

    def _make_uploading_session(self, existing_orders: set | None = None) -> FakeSession:
        sess = FakeSession()
        if existing_orders:
            sess.images = [FakeImage(sequence_order=o) for o in existing_orders]
        return sess

    def _make_db(self, session) -> MagicMock:
        db = MagicMock()
        db.get.return_value = session
        return db

    @patch("services.liff_service.save_uploaded_file", return_value="uploads/uuid-abc.jpg")
    def test_returns_false_none_tuple(self, _mock_save):
        """上傳成功後應回傳 (SessionImage, ocr_completed=False, is_voucher=None)。"""
        session = self._make_uploading_session()
        db = self._make_db(session)

        img_record, ocr_completed, is_voucher = asyncio.run(liff_service.add_image(
            db=db, session_id=session.id,
            upload_file=MagicMock(), sequence_order=0,
        ))

        assert ocr_completed is False
        assert is_voucher is None

    @patch("services.liff_service.save_uploaded_file", return_value="uploads/uuid-abc.jpg")
    def test_image_path_and_sequence_stored(self, _mock_save):
        """SessionImage 應正確記錄 image_path 與 sequence_order。"""
        session = self._make_uploading_session()
        db = self._make_db(session)

        img_record, _, _ = asyncio.run(liff_service.add_image(
            db=db, session_id=session.id,
            upload_file=MagicMock(), sequence_order=2,
        ))

        assert img_record.image_path == "uploads/uuid-abc.jpg"
        assert img_record.sequence_order == 2
        assert img_record.is_voucher is None

    @patch("services.liff_service.save_uploaded_file", return_value="uploads/uuid-abc.jpg")
    def test_ocr_service_never_called(self, _mock_save):
        """OCR（classify_and_extract_with_retry）不應在圖片上傳時被呼叫。"""
        session = self._make_uploading_session()
        db = self._make_db(session)

        with patch("services.liff_service.ocr_service") as mock_ocr:
            asyncio.run(liff_service.add_image(
                db=db, session_id=session.id,
                upload_file=MagicMock(), sequence_order=0,
            ))
            mock_ocr.classify_and_extract_with_retry.assert_not_called()
            mock_ocr.classify_and_extract.assert_not_called()

    @patch("services.liff_service.save_uploaded_file", return_value="uploads/abc.jpg")
    def test_duplicate_sequence_order_raises_422(self, _mock_save):
        """sequence_order 重複時應拋出 422 Unprocessable Entity。"""
        session = self._make_uploading_session(existing_orders={0, 1, 2})
        db = self._make_db(session)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(liff_service.add_image(
                db=db, session_id=session.id,
                upload_file=MagicMock(), sequence_order=1,
            ))
        assert exc_info.value.status_code == 422
        assert "sequence_order=1" in exc_info.value.detail

    def test_session_not_found_raises_404(self):
        """Session 不存在時應拋出 404 Not Found。"""
        db = self._make_db(session=None)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(liff_service.add_image(
                db=db, session_id=uuid.uuid4(),
                upload_file=MagicMock(), sequence_order=0,
            ))
        assert exc_info.value.status_code == 404

    def test_expired_session_raises_410(self):
        """已過期（超過 TTL）的 session 應拋出 410 Gone。"""
        session = _make_expired_session()
        db = self._make_db(session)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(liff_service.add_image(
                db=db, session_id=session.id,
                upload_file=MagicMock(), sequence_order=0,
            ))
        assert exc_info.value.status_code == 410

    def test_submitted_session_raises_409(self):
        """已送出（status=submitted）的 session 不可再上傳，應拋出 409 Conflict。"""
        session = FakeSession(status="submitted")
        db = self._make_db(session)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(liff_service.add_image(
                db=db, session_id=session.id,
                upload_file=MagicMock(), sequence_order=0,
            ))
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# TestSubmitSession — 立即鎖定 session 並回傳
# ---------------------------------------------------------------------------

class TestSubmitSession:
    """
    測試 submit_session() 函式。
    核心特性：立即回傳（不等待 OCR），OCR 由背景任務執行。
    """

    def _make_db(self, session) -> MagicMock:
        db = MagicMock()
        db.get.return_value = session
        return db

    def test_locks_session_status_to_submitted(self):
        """呼叫後 session.status 應立即變更為 'submitted'。"""
        session = FakeSession()
        db = self._make_db(session)

        liff_service.submit_session(db=db, session_id=session.id, group_descriptions={})

        assert session.status == "submitted"

    def test_sets_processing_status_to_pending(self):
        """呼叫後 session.processing_status 應設為 'pending'（背景任務待執行）。"""
        session = FakeSession()
        db = self._make_db(session)

        liff_service.submit_session(db=db, session_id=session.id, group_descriptions={})

        assert session.processing_status == "pending"

    def test_returns_empty_created_expenses(self):
        """立即回傳的 SubmitSessionResponse.created_expenses 應為空清單（尚未建帳）。"""
        session = FakeSession()
        db = self._make_db(session)

        response = liff_service.submit_session(
            db=db, session_id=session.id, group_descriptions={}
        )

        assert response.created_expenses == []

    def test_response_session_id_matches(self):
        """回傳的 session_id 應與傳入的 session_id 一致。"""
        session = FakeSession()
        db = self._make_db(session)

        response = liff_service.submit_session(
            db=db, session_id=session.id, group_descriptions={}
        )

        assert response.session_id == session.id

    def test_db_commit_called(self):
        """狀態變更後應呼叫 db.commit() 持久化。"""
        session = FakeSession()
        db = self._make_db(session)

        liff_service.submit_session(db=db, session_id=session.id, group_descriptions={})

        db.commit.assert_called()

    def test_session_not_found_raises_404(self):
        """Session 不存在應拋出 404。"""
        db = self._make_db(None)

        with pytest.raises(HTTPException) as exc_info:
            liff_service.submit_session(db=db, session_id=uuid.uuid4(), group_descriptions={})
        assert exc_info.value.status_code == 404

    def test_already_submitted_raises_409(self):
        """重複送出（status 已為 submitted）應拋出 409 Conflict，防止建立重複費用。"""
        session = FakeSession(status="submitted")
        db = self._make_db(session)

        with pytest.raises(HTTPException) as exc_info:
            liff_service.submit_session(db=db, session_id=session.id, group_descriptions={})
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# TestProcessSessionBackground — 背景 OCR + 建帳邏輯
# ---------------------------------------------------------------------------

class TestProcessSessionBackground:
    """
    測試 process_session_background() 非同步背景任務。
    此函式使用自己的 SessionLocal()，與 HTTP request DB 完全隔離。
    """

    async def test_processing_status_set_to_processing_at_start(self):
        """任務啟動後應立即將 processing_status 設為 'processing'。"""
        session = FakeSession(images=[])
        db = make_mock_db(session)
        captured = {}

        original_commit = db.commit.side_effect

        def capture_on_first_commit():
            if "status" not in captured:
                captured["status"] = session.processing_status

        db.commit.side_effect = capture_on_first_commit

        with patch("services.liff_service.SessionLocal", return_value=db), \
             patch("services.liff_service.settings", _default_settings_mock()):
            await liff_service.process_session_background(
                session_id=session.id, group_descriptions={}, waiting_return_ref=None
            )

        assert captured["status"] == "processing"

    async def test_no_images_sets_done_and_returns_early(self):
        """Session 無圖片時，processing_status 應設為 'done' 並立即回傳，不呼叫 OCR。"""
        session = FakeSession(images=[])
        db = make_mock_db(session)

        with patch("services.liff_service.SessionLocal", return_value=db), \
             patch("services.liff_service.settings", _default_settings_mock()), \
             patch("services.liff_service.ocr_service.classify_and_extract_with_retry") as mock_ocr:
            await liff_service.process_session_background(
                session_id=session.id, group_descriptions={}, waiting_return_ref=None
            )
            mock_ocr.assert_not_called()

        assert session.processing_status == "done"

    async def test_session_not_found_returns_early_without_crash(self):
        """Session 不存在時應靜默提前回傳，不拋出例外。"""
        db = MagicMock()
        db.get.return_value = None

        with patch("services.liff_service.SessionLocal", return_value=db):
            await liff_service.process_session_background(
                session_id=uuid.uuid4(), group_descriptions={}, waiting_return_ref=None
            )

        db.close.assert_called_once()

    async def test_user_not_found_sets_processing_status_failed(self):
        """LINE 使用者在 DB 中不存在時，processing_status 應設為 'failed'。"""
        session = FakeSession(images=[FakeImage()])
        db = make_mock_db(session, fake_user=None)  # user=None

        with patch("services.liff_service.SessionLocal", return_value=db), \
             patch("services.liff_service.settings", _default_settings_mock()):
            await liff_service.process_session_background(
                session_id=session.id, group_descriptions={}, waiting_return_ref=None
            )

        assert session.processing_status == "failed"

    async def test_single_image_ocr_success_creates_expense(self):
        """單張圖片 OCR 成功後應建立一筆 Expense（trigger_by='liff'）。"""
        img = FakeImage(sequence_order=0, image_path="uploads/receipt.jpg")
        session = FakeSession(images=[img])
        user = FakeUser()
        db = make_mock_db(session, user)
        ocr_result = make_voucher_ocr(is_voucher=True)
        mock_expense = MagicMock()
        mock_expense.serial_number = "EXP-202605-0001"

        with patch("services.liff_service.SessionLocal", return_value=db), \
             patch("services.liff_service.ocr_service.classify_and_extract_with_retry",
                   new=AsyncMock(return_value=ocr_result)), \
             patch("services.liff_service.expense_service.create_batch_expense",
                   return_value=mock_expense) as mock_create, \
             patch("services.liff_service.relation_service.attach_orphan_images_to_recent_expense",
                   return_value=False), \
             patch("services.liff_service.multi_split_logic_v2",
                   return_value=([([img.image_path], [ocr_result])], [])), \
             patch("services.liff_service.settings", _default_settings_mock()):
            await liff_service.process_session_background(
                session_id=session.id, group_descriptions={0: "午餐費用"}, waiting_return_ref=None
            )

        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["trigger_by"] == "liff"
        assert kwargs["user_description"] == "午餐費用"

    async def test_ocr_result_written_back_to_image(self):
        """OCR 成功後應將 is_voucher 與完整 ocr_result JSON 寫回 SessionImage 物件。"""
        img = FakeImage(sequence_order=0, is_voucher=None)
        session = FakeSession(images=[img])
        user = FakeUser()
        db = make_mock_db(session, user)
        ocr_result = make_voucher_ocr(is_voucher=True)
        mock_expense = MagicMock()
        mock_expense.serial_number = "EXP-202605-0001"

        with patch("services.liff_service.SessionLocal", return_value=db), \
             patch("services.liff_service.ocr_service.classify_and_extract_with_retry",
                   new=AsyncMock(return_value=ocr_result)), \
             patch("services.liff_service.expense_service.create_batch_expense",
                   return_value=mock_expense), \
             patch("services.liff_service.relation_service.attach_orphan_images_to_recent_expense",
                   return_value=False), \
             patch("services.liff_service.multi_split_logic_v2",
                   return_value=([([img.image_path], [ocr_result])], [])), \
             patch("services.liff_service.settings", _default_settings_mock()):
            await liff_service.process_session_background(
                session_id=session.id, group_descriptions={}, waiting_return_ref=None
            )

        assert img.is_voucher is True
        assert img.ocr_result is not None  # 完整 JSON 已寫入

    async def test_all_ocr_raise_exception_flow_continues(self):
        """
        所有圖片 OCR 都拋出例外時（return_exceptions=True），
        流程應繼續執行（不中斷），is_voucher 保持 None（視為非憑證），最終 done。
        """
        img = FakeImage(sequence_order=0, is_voucher=None)
        session = FakeSession(images=[img])
        user = FakeUser()
        db = make_mock_db(session, user)
        mock_expense = MagicMock()
        mock_expense.serial_number = "EXP-202605-0001"

        with patch("services.liff_service.SessionLocal", return_value=db), \
             patch("services.liff_service.ocr_service.classify_and_extract_with_retry",
                   new=AsyncMock(side_effect=RuntimeError("Gemini API timeout"))), \
             patch("services.liff_service.expense_service.create_batch_expense",
                   return_value=mock_expense), \
             patch("services.liff_service.relation_service.attach_orphan_images_to_recent_expense",
                   return_value=False), \
             patch("services.liff_service.multi_split_logic_v2",
                   return_value=([], [img.image_path])), \
             patch("services.liff_service.settings", _default_settings_mock()):
            await liff_service.process_session_background(
                session_id=session.id, group_descriptions={}, waiting_return_ref=None
            )

        assert img.is_voucher is None
        assert session.processing_status == "done"

    async def test_partial_ocr_failure_continues_with_successful(self):
        """部分圖片 OCR 失敗時，成功的圖片仍正確辨識，流程不中斷。"""
        img_ok = FakeImage(sequence_order=0, image_path="uploads/ok.jpg", is_voucher=None)
        img_fail = FakeImage(sequence_order=1, image_path="uploads/fail.jpg", is_voucher=None)
        session = FakeSession(images=[img_ok, img_fail])
        user = FakeUser()
        db = make_mock_db(session, user)
        ocr_ok = make_voucher_ocr(is_voucher=True)
        mock_expense = MagicMock()
        mock_expense.serial_number = "EXP-202605-0001"

        with patch("services.liff_service.SessionLocal", return_value=db), \
             patch("services.liff_service.ocr_service.classify_and_extract_with_retry",
                   new=AsyncMock(side_effect=[ocr_ok, RuntimeError("Gemini 逾時")])), \
             patch("services.liff_service.expense_service.create_batch_expense",
                   return_value=mock_expense), \
             patch("services.liff_service.relation_service.attach_orphan_images_to_recent_expense",
                   return_value=False), \
             patch("services.liff_service.multi_split_logic_v2",
                   return_value=([([img_ok.image_path], [ocr_ok])], [img_fail.image_path])), \
             patch("services.liff_service.settings", _default_settings_mock()):
            await liff_service.process_session_background(
                session_id=session.id, group_descriptions={}, waiting_return_ref=None
            )

        assert img_ok.is_voucher is True
        assert img_fail.is_voucher is None  # 失敗者保持 None
        assert session.processing_status == "done"

    async def test_create_batch_expense_failure_continues(self):
        """單筆 create_batch_expense 失敗時，不影響其他群組，任務最終仍為 done。"""
        img = FakeImage(sequence_order=0)
        session = FakeSession(images=[img])
        user = FakeUser()
        db = make_mock_db(session, user)
        ocr_result = make_voucher_ocr()

        with patch("services.liff_service.SessionLocal", return_value=db), \
             patch("services.liff_service.ocr_service.classify_and_extract_with_retry",
                   new=AsyncMock(return_value=ocr_result)), \
             patch("services.liff_service.expense_service.create_batch_expense",
                   side_effect=RuntimeError("DB 序號衝突")), \
             patch("services.liff_service.relation_service.attach_orphan_images_to_recent_expense",
                   return_value=False), \
             patch("services.liff_service.multi_split_logic_v2",
                   return_value=([([img.image_path], [ocr_result])], [])), \
             patch("services.liff_service.settings", _default_settings_mock()):
            await liff_service.process_session_background(
                session_id=session.id, group_descriptions={}, waiting_return_ref=None
            )

        assert session.processing_status == "done"  # 不應設為 failed

    async def test_waiting_return_ref_marks_return_supplement(self):
        """waiting_return_ref 非空時，Expense 應標記 RETURN_SUPPLEMENT 與原始憑證號碼。"""
        img = FakeImage(sequence_order=0, is_voucher=None)
        session = FakeSession(images=[img])
        user = FakeUser()
        db = make_mock_db(session, user)
        ocr_result = make_voucher_ocr(is_voucher=False, success=False)
        mock_expense = MagicMock()
        mock_expense.serial_number = "EXP-202605-0001"
        mock_expense.item_description = None

        with patch("services.liff_service.SessionLocal", return_value=db), \
             patch("services.liff_service.ocr_service.classify_and_extract_with_retry",
                   new=AsyncMock(return_value=ocr_result)), \
             patch("services.liff_service.expense_service.create_batch_expense",
                   return_value=mock_expense), \
             patch("services.liff_service.relation_service.attach_orphan_images_to_recent_expense",
                   return_value=False), \
             patch("services.liff_service.multi_split_logic_v2",
                   return_value=([([img.image_path], [ocr_result])], [])), \
             patch("services.liff_service.settings", _default_settings_mock()):
            await liff_service.process_session_background(
                session_id=session.id, group_descriptions={},
                waiting_return_ref="AB-99887766"
            )

        assert mock_expense.relation_type == "RETURN_SUPPLEMENT"
        assert mock_expense.referenced_invoice_number == "AB-99887766"
        assert "AB-99887766" in (mock_expense.item_description or "")

    async def test_orphan_images_attached_to_recent_expense(self):
        """孤立物品圖能附加至 10 分鐘內近期費用時，不建立獨立 Expense。"""
        img = FakeImage(sequence_order=0, is_voucher=None)
        session = FakeSession(images=[img])
        user = FakeUser()
        db = make_mock_db(session, user)
        ocr_result = make_voucher_ocr(is_voucher=False)

        # batch 模式才會呼叫 multi_split_logic_v2，orphan_paths 才有值
        batch_settings = _default_settings_mock()
        batch_settings.liff_submit_mode = "batch"

        with patch("services.liff_service.SessionLocal", return_value=db), \
             patch("services.liff_service.ocr_service.classify_and_extract_with_retry",
                   new=AsyncMock(return_value=ocr_result)), \
             patch("services.liff_service.expense_service.create_batch_expense") as mock_create, \
             patch("services.liff_service.relation_service.attach_orphan_images_to_recent_expense",
                   return_value=True) as mock_attach, \
             patch("services.liff_service.multi_split_logic_v2",
                   return_value=([], [img.image_path])), \
             patch("services.liff_service.settings", batch_settings):
            await liff_service.process_session_background(
                session_id=session.id, group_descriptions={}, waiting_return_ref=None
            )

        mock_attach.assert_called_once()
        mock_create.assert_not_called()

    async def test_orphan_images_not_attachable_creates_standalone_expense(self):
        """孤立物品圖無法附加近期費用時，應建立獨立 Expense（trigger_by='liff_orphan'）。"""
        img = FakeImage(sequence_order=0, is_voucher=None)
        session = FakeSession(images=[img])
        user = FakeUser()
        db = make_mock_db(session, user)
        ocr_result = make_voucher_ocr(is_voucher=False, success=False)
        mock_expense = MagicMock()
        mock_expense.serial_number = "EXP-202605-9999"

        # batch 模式才會呼叫 multi_split_logic_v2，orphan_paths 才有值
        batch_settings = _default_settings_mock()
        batch_settings.liff_submit_mode = "batch"

        with patch("services.liff_service.SessionLocal", return_value=db), \
             patch("services.liff_service.ocr_service.classify_and_extract_with_retry",
                   new=AsyncMock(return_value=ocr_result)), \
             patch("services.liff_service.expense_service.create_batch_expense",
                   return_value=mock_expense) as mock_create, \
             patch("services.liff_service.relation_service.attach_orphan_images_to_recent_expense",
                   return_value=False), \
             patch("services.liff_service.multi_split_logic_v2",
                   return_value=([], [img.image_path])), \
             patch("services.liff_service.settings", batch_settings):
            await liff_service.process_session_background(
                session_id=session.id, group_descriptions={}, waiting_return_ref=None
            )

        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["trigger_by"] == "liff_orphan"

    async def test_orphan_with_waiting_return_ref_redirected_not_attached(self):
        """
        waiting_return_ref 非空時，孤立圖片應併入 groups 建立 RETURN_SUPPLEMENT，
        不走 attach_orphan 路徑。
        """
        img = FakeImage(sequence_order=0, is_voucher=None)
        session = FakeSession(images=[img])
        user = FakeUser()
        db = make_mock_db(session, user)
        ocr_result = make_voucher_ocr(is_voucher=False, success=False)
        mock_expense = MagicMock()
        mock_expense.serial_number = "EXP-202605-0001"
        mock_expense.item_description = None

        with patch("services.liff_service.SessionLocal", return_value=db), \
             patch("services.liff_service.ocr_service.classify_and_extract_with_retry",
                   new=AsyncMock(return_value=ocr_result)), \
             patch("services.liff_service.expense_service.create_batch_expense",
                   return_value=mock_expense) as mock_create, \
             patch("services.liff_service.relation_service.attach_orphan_images_to_recent_expense") as mock_attach, \
             patch("services.liff_service.multi_split_logic_v2",
                   return_value=([], [img.image_path])), \
             patch("services.liff_service.settings", _default_settings_mock()):
            await liff_service.process_session_background(
                session_id=session.id, group_descriptions={},
                waiting_return_ref="AB-12345678"
            )

        mock_attach.assert_not_called()
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["trigger_by"] == "liff"

    async def test_batch_mode_calls_multi_split_logic(self):
        """liff_submit_mode='batch' 時應呼叫 multi_split_logic_v2 進行憑證斷點切割。"""
        imgs = [
            FakeImage(sequence_order=0, image_path="uploads/a.jpg"),
            FakeImage(sequence_order=1, image_path="uploads/b.jpg"),
        ]
        session = FakeSession(images=imgs)
        user = FakeUser()
        db = make_mock_db(session, user)
        ocr_results = [make_voucher_ocr(is_voucher=True), make_voucher_ocr(is_voucher=False)]
        mock_expense = MagicMock()
        mock_expense.serial_number = "EXP-202605-0001"

        settings_mock = _default_settings_mock()
        settings_mock.liff_submit_mode = "batch"

        with patch("services.liff_service.SessionLocal", return_value=db), \
             patch("services.liff_service.ocr_service.classify_and_extract_with_retry",
                   new=AsyncMock(side_effect=ocr_results)), \
             patch("services.liff_service.expense_service.create_batch_expense",
                   return_value=mock_expense), \
             patch("services.liff_service.relation_service.attach_orphan_images_to_recent_expense",
                   return_value=False), \
             patch("services.liff_service.multi_split_logic_v2",
                   return_value=([([imgs[0].image_path], [ocr_results[0]])], [imgs[1].image_path])
                   ) as mock_split, \
             patch("services.liff_service.settings", settings_mock):
            await liff_service.process_session_background(
                session_id=session.id, group_descriptions={}, waiting_return_ref=None
            )

        mock_split.assert_called_once()

    async def test_single_mode_skips_multi_split(self):
        """liff_submit_mode='single' 時應跳過 multi_split_logic_v2，全部視為一群組。"""
        img = FakeImage(sequence_order=0)
        session = FakeSession(images=[img])
        user = FakeUser()
        db = make_mock_db(session, user)
        ocr_result = make_voucher_ocr()
        mock_expense = MagicMock()
        mock_expense.serial_number = "EXP-202605-0001"

        with patch("services.liff_service.SessionLocal", return_value=db), \
             patch("services.liff_service.ocr_service.classify_and_extract_with_retry",
                   new=AsyncMock(return_value=ocr_result)), \
             patch("services.liff_service.expense_service.create_batch_expense",
                   return_value=mock_expense), \
             patch("services.liff_service.relation_service.attach_orphan_images_to_recent_expense",
                   return_value=False), \
             patch("services.liff_service.multi_split_logic_v2") as mock_split, \
             patch("services.liff_service.settings", _default_settings_mock()):
            await liff_service.process_session_background(
                session_id=session.id, group_descriptions={}, waiting_return_ref=None
            )

        mock_split.assert_not_called()

    async def test_fatal_exception_sets_processing_status_failed(self):
        """
        OCR 後的 multi_split 拋出不預期例外時（batch 模式），
        processing_status 應設為 'failed'，不 crash server。
        注意：single 模式會跳過 multi_split_logic_v2，須用 batch 模式才能觸發此路徑。
        """
        session = FakeSession(images=[FakeImage()])
        db = make_mock_db(session, FakeUser())

        batch_settings = _default_settings_mock()
        batch_settings.liff_submit_mode = "batch"

        with patch("services.liff_service.SessionLocal", return_value=db), \
             patch("services.liff_service.ocr_service.classify_and_extract_with_retry",
                   new=AsyncMock(return_value=make_voucher_ocr())), \
             patch("services.liff_service.settings", batch_settings), \
             patch("services.liff_service.multi_split_logic_v2",
                   side_effect=Exception("切割邏輯內部錯誤")):
            await liff_service.process_session_background(
                session_id=session.id, group_descriptions={}, waiting_return_ref=None
            )

        assert session.processing_status == "failed"

    async def test_db_close_called_on_success(self):
        """正常完成後，db.close() 必定被呼叫（connection pool 回收）。"""
        session = FakeSession(images=[])
        db = make_mock_db(session)

        with patch("services.liff_service.SessionLocal", return_value=db), \
             patch("services.liff_service.settings", _default_settings_mock()):
            await liff_service.process_session_background(
                session_id=session.id, group_descriptions={}, waiting_return_ref=None
            )

        db.close.assert_called_once()

    async def test_db_close_called_on_fatal_error(self):
        """fatal exception 時 db.close() 仍必定被呼叫（finally 保證）。"""
        db = MagicMock()
        db.get.side_effect = RuntimeError("DB 連線完全中斷")

        with patch("services.liff_service.SessionLocal", return_value=db):
            await liff_service.process_session_background(
                session_id=uuid.uuid4(), group_descriptions={}, waiting_return_ref=None
            )

        db.close.assert_called_once()


# ---------------------------------------------------------------------------
# TestPatchImageType — 手動切換圖片類型
# ---------------------------------------------------------------------------

class TestPatchImageType:
    """測試 patch_image_type() 函式。"""

    def _make_db(self, session, image=None):
        """
        patch_image_type 先用 db.get() 取 UploadSession，
        再用 db.scalar() 取 SessionImage，所以兩個都要設定。
        """
        db = MagicMock()
        db.get.return_value = session
        db.scalar.return_value = image
        return db

    def test_sets_is_voucher_true(self):
        """手動切換至 True 後，is_voucher 應正確更新。"""
        session = FakeSession()
        img = FakeImage(is_voucher=None)
        db = self._make_db(session, img)

        result = liff_service.patch_image_type(
            db=db, session_id=session.id, image_id=img.id, is_voucher=True
        )

        assert result.is_voucher is True

    def test_sets_manually_set_flag_to_true(self):
        """手動切換後 manually_set 應設為 True（優先於 OCR 判斷）。"""
        session = FakeSession()
        img = FakeImage(manually_set=False)
        db = self._make_db(session, img)

        liff_service.patch_image_type(
            db=db, session_id=session.id, image_id=img.id, is_voucher=False
        )

        assert img.manually_set is True

    def test_session_not_found_raises_404(self):
        """Session 不存在時應拋出 404。"""
        db = MagicMock()
        db.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            liff_service.patch_image_type(
                db=db, session_id=uuid.uuid4(), image_id=uuid.uuid4(), is_voucher=True
            )
        assert exc_info.value.status_code == 404

    def test_image_not_found_raises_404(self):
        """SessionImage 不存在時應拋出 404。"""
        session = FakeSession()
        db = MagicMock()
        db.get.return_value = session
        db.scalar.return_value = None  # 圖片不存在

        with pytest.raises(HTTPException) as exc_info:
            liff_service.patch_image_type(
                db=db, session_id=session.id, image_id=uuid.uuid4(), is_voucher=True
            )
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# TestGetSessionPreview — 確認頁群組預覽
# ---------------------------------------------------------------------------

class TestGetSessionPreview:
    """測試 get_session_preview() 函式。"""

    def _make_db(self, session) -> MagicMock:
        db = MagicMock()
        db.get.return_value = session
        return db

    def test_empty_session_returns_no_groups_no_orphans(self):
        """無圖片的 session 應回傳 groups=[], orphan_images=[], total_images=0。"""
        session = FakeSession(images=[])
        response = liff_service.get_session_preview(
            db=self._make_db(session), session_id=session.id
        )

        assert response.groups == []
        assert response.orphan_images == []
        assert response.total_images == 0

    def test_single_voucher_one_group_no_orphan(self):
        """單一憑證應形成 1 個群組，無孤立圖片。"""
        session = FakeSession(images=[
            FakeImage(sequence_order=0, is_voucher=True),
        ])
        response = liff_service.get_session_preview(
            db=self._make_db(session), session_id=session.id
        )

        assert len(response.groups) == 1
        assert response.groups[0].voucher_image is not None
        assert response.orphan_images == []

    def test_item_images_before_first_voucher_are_orphans(self):
        """第一張憑證之前的物品照（無論數量）應全部歸入 orphan_images。"""
        session = FakeSession(images=[
            FakeImage(sequence_order=0, is_voucher=False),
            FakeImage(sequence_order=1, is_voucher=False),
            FakeImage(sequence_order=2, is_voucher=True),
            FakeImage(sequence_order=3, is_voucher=False),
        ])
        response = liff_service.get_session_preview(
            db=self._make_db(session), session_id=session.id
        )

        assert len(response.orphan_images) == 2
        assert len(response.groups) == 1
        assert len(response.groups[0].item_images) == 1

    def test_all_item_images_no_voucher_all_orphan(self):
        """全部為物品照（無任何憑證）時，全部歸入 orphan_images，groups 為空。"""
        session = FakeSession(images=[
            FakeImage(sequence_order=0, is_voucher=False),
            FakeImage(sequence_order=1, is_voucher=False),
        ])
        response = liff_service.get_session_preview(
            db=self._make_db(session), session_id=session.id
        )

        assert response.groups == []
        assert len(response.orphan_images) == 2

    def test_multiple_vouchers_multiple_groups(self):
        """多張憑證應各自形成獨立群組，附屬物品照正確分配。"""
        session = FakeSession(images=[
            FakeImage(sequence_order=0, is_voucher=True),
            FakeImage(sequence_order=1, is_voucher=False),
            FakeImage(sequence_order=2, is_voucher=True),
            FakeImage(sequence_order=3, is_voucher=False),
        ])
        response = liff_service.get_session_preview(
            db=self._make_db(session), session_id=session.id
        )

        assert len(response.groups) == 2
        assert len(response.groups[0].item_images) == 1
        assert len(response.groups[1].item_images) == 1
        assert response.orphan_images == []
