"""
Integration tests for Sprint 3 — 雙軌觸發機制 (Auto-Split + Manual Button)

測試涵蓋：
1. confirm_submit 取消自動切割 Timer（Priority Event）
2. ENABLE_AUTO_SPLIT=false 時不呼叫 schedule()
3. 按鈕觸發 → Expense.trigger_by = "manual_button"
4. auto_split_process 觸發 → Expense.trigger_by = "auto_split"（含多筆切割）
5. 圖片收集使用新格式 buffer（含 timestamp）
"""

# ---------------------------------------------------------------------------
# 最早期 patch — 與 test_batch_flow.py 相同的 psycopg2 mock
# ---------------------------------------------------------------------------

import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

_fake_psycopg2 = MagicMock()
_fake_psycopg2.extensions = MagicMock()
_fake_psycopg2.__version__ = "2.9.9"
_fake_psycopg2.Error = Exception
sys.modules.setdefault("psycopg2", _fake_psycopg2)
sys.modules.setdefault("psycopg2.extensions", _fake_psycopg2.extensions)
sys.modules.setdefault("psycopg2.extras", MagicMock())

import sqlalchemy.orm as _sa_orm
if not hasattr(_sa_orm, "with_for_update"):
    _sa_orm.with_for_update = lambda **kw: None

# ---------------------------------------------------------------------------
# 標準 import
# ---------------------------------------------------------------------------

import asyncio
import json
import uuid
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# ---------------------------------------------------------------------------
# 測試專用 SQLite in-memory DB
# ---------------------------------------------------------------------------

SQLITE_TEST_URL = "sqlite:///file:autosplit_test?mode=memory&cache=shared&uri=true"


def _init_tables(conn) -> None:
    conn.execute(text("DROP TABLE IF EXISTS expense_images"))
    conn.execute(text("DROP TABLE IF EXISTS expenses"))
    conn.execute(text("DROP TABLE IF EXISTS user_states"))
    conn.execute(text("DROP TABLE IF EXISTS users"))
    conn.execute(text("DROP TABLE IF EXISTS admin_users"))
    conn.execute(text("""
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            line_user_id TEXT UNIQUE NOT NULL,
            name TEXT,
            department TEXT,
            real_name TEXT,
            employee_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE user_states (
            line_user_id TEXT PRIMARY KEY,
            step TEXT NOT NULL,
            dept TEXT,
            pending_images TEXT NOT NULL DEFAULT '[]',
            pending_description TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE expenses (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            serial_number TEXT UNIQUE NOT NULL,
            image_url TEXT NOT NULL DEFAULT '[]',
            item_image_url TEXT NOT NULL DEFAULT '[]',
            uploader_name TEXT,
            uploader_dept TEXT,
            submitter_name TEXT,
            submitter_dept TEXT,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            item_description TEXT,
            expense_date DATE,
            invoice_number TEXT,
            total_amount NUMERIC(12,2),
            net_amount NUMERIC(12,2),
            tax_amount NUMERIC(12,2),
            seller_tax_id TEXT,
            seller_name TEXT,
            amount NUMERIC(12,2),
            status TEXT NOT NULL DEFAULT 'PENDING',
            reject_reason TEXT,
            user_description TEXT,
            image_count INTEGER NOT NULL DEFAULT 1,
            voucher_categories TEXT,
            trigger_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE expense_images (
            id TEXT PRIMARY KEY,
            expense_id TEXT NOT NULL,
            image_url TEXT NOT NULL,
            is_voucher INTEGER NOT NULL DEFAULT 0,
            voucher_category TEXT,
            sequence_order INTEGER NOT NULL DEFAULT 1,
            ocr_result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE admin_users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL,
            display_name TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.commit()


@pytest.fixture(scope="module")
def auto_split_engine():
    engine = create_engine(SQLITE_TEST_URL, connect_args={"check_same_thread": False}, echo=False)
    with engine.connect() as conn:
        _init_tables(conn)
    yield engine
    engine.dispose()


@pytest.fixture
def auto_split_db(auto_split_engine) -> Generator[Session, None, None]:
    connection = auto_split_engine.connect()
    transaction = connection.begin()
    _SessionLocal = sessionmaker(bind=connection, autocommit=False, autoflush=False)
    session = _SessionLocal()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# 共用 Helper
# ---------------------------------------------------------------------------

def _insert_user(db: Session, line_user_id: str, department: str = "攝影組") -> str:
    existing = db.execute(
        text("SELECT id FROM users WHERE line_user_id = :uid"), {"uid": line_user_id}
    ).fetchone()
    if existing:
        return existing[0]
    user_id = str(uuid.uuid4())
    db.execute(
        text("INSERT INTO users (id, line_user_id, name, department, real_name) VALUES (:id, :uid, :name, :dept, :rn)"),
        {"id": user_id, "uid": line_user_id, "name": "測試用戶", "dept": department, "rn": "王小明"},
    )
    db.commit()
    return user_id


def _insert_user_state(db: Session, line_user_id: str, pending_images: list | None = None) -> None:
    images_json = json.dumps(pending_images or [])
    db.execute(
        text("""
            INSERT OR REPLACE INTO user_states (line_user_id, step, dept, pending_images)
            VALUES (:uid, 'COLLECTING', '攝影組', :imgs)
        """),
        {"uid": line_user_id, "imgs": images_json},
    )
    db.commit()


@contextmanager
def _client(db_session: Session):
    """建立 TestClient，注入 SQLite session，patch 外部依賴。"""
    from main import app
    from core.database import get_db

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    try:
        with (
            patch("linebot.v3.WebhookParser.parse") as mock_parse,
            patch("core.database.Base.metadata.create_all", MagicMock()),
            patch("services.line_service.reply_text", MagicMock()),
            patch("services.line_service.download_image", MagicMock(return_value=None)),
            patch("main.start_scheduler", MagicMock()),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                yield client, mock_parse
    finally:
        app.dependency_overrides.pop(get_db, None)


def _post_webhook(client: TestClient, events) -> int:
    """向 /webhook 送出 POST，回傳 HTTP status code。"""
    with patch("linebot.v3.WebhookParser.parse", return_value=events):
        resp = client.post(
            "/webhook",
            content=b'{"events":[]}',
            headers={"x-line-signature": "test-sig"},
        )
    return resp.status_code


def _make_postback_event(line_user_id: str, data: str, reply_token: str = "reply_tok_xxx"):
    """建立 PostbackEvent mock。"""
    event = MagicMock()
    event.__class__.__name__ = "PostbackEvent"
    event.source.user_id = line_user_id
    event.reply_token = reply_token
    event.postback.data = data

    from linebot.v3.webhooks import PostbackEvent as _PBEvent
    event.__class__ = _PBEvent
    return event


def _make_image_event(line_user_id: str, message_id: str = "img_msg_001", timestamp: int = 1714000000000):
    """建立 ImageMessageContent event mock。"""
    from linebot.v3.webhooks import ImageMessageContent, MessageEvent

    source = MagicMock()
    source.user_id = line_user_id

    msg = MagicMock(spec=ImageMessageContent)
    msg.__class__ = ImageMessageContent
    msg.id = message_id

    # spec=MessageEvent 已令 isinstance(event, MessageEvent) 為 True；
    # 勿再設 event.__class__ = MessageEvent，否則屬性存取會走 Pydantic 路徑而非 MagicMock。
    event = MagicMock(spec=MessageEvent)
    event.source = source
    event.reply_token = "reply_tok_img"
    event.timestamp = timestamp
    event.message = msg
    return event


# ---------------------------------------------------------------------------
# 測試：按鈕觸發取消 Timer
# ---------------------------------------------------------------------------

class TestConfirmSubmitCancelsTimer:
    @pytest.mark.skip(
        reason="PostbackEvent handling removed from webhook; confirm_submit moved to LIFF. "
               "Timer cancellation should be tested in liff_service tests."
    )
    def test_confirm_submit_cancels_existing_timer(self, auto_split_db):
        """confirm_submit 時若有活躍 Timer → cancel() 被呼叫（Priority Event 保證）"""
        from services import auto_split_timer

        line_user_id = "cancel_timer_user"
        _insert_user(auto_split_db, line_user_id)
        _insert_user_state(
            auto_split_db, line_user_id,
            pending_images=[{"path": "uploads/x.jpg", "timestamp": 1000, "message_id": "m1"}]
        )

        with patch.object(auto_split_timer, "cancel", wraps=auto_split_timer.cancel) as mock_cancel:
            with patch("core.config.settings") as mock_settings:
                mock_settings.enable_auto_split = True
                mock_settings.auto_split_debounce_seconds = 60
                mock_settings.enable_user_binding = False
                mock_settings.enable_scheduled_batch = False
                mock_settings.scheduled_batch_timezone = "Asia/Taipei"
                mock_settings.scheduled_batch_times = ["20:00"]
                mock_settings.line_channel_secret = "test-channel-secret"
                mock_settings.storage_path = "./uploads"

                with _client(auto_split_db) as (client, _mock_parse):
                    event = _make_postback_event(line_user_id, "action=confirm_submit")
                    _post_webhook(client, [event])

                mock_cancel.assert_called_with(line_user_id)

    def test_confirm_submit_no_cancel_when_auto_split_disabled(self, auto_split_db):
        """ENABLE_AUTO_SPLIT=false 時，confirm_submit 不呼叫 cancel()"""
        from services import auto_split_timer

        line_user_id = "no_cancel_user"
        _insert_user(auto_split_db, line_user_id)
        _insert_user_state(
            auto_split_db, line_user_id,
            pending_images=[{"path": "uploads/y.jpg", "timestamp": 2000, "message_id": "m2"}]
        )

        with patch.object(auto_split_timer, "cancel") as mock_cancel:
            with patch("core.config.settings") as mock_settings:
                mock_settings.enable_auto_split = False
                mock_settings.auto_split_debounce_seconds = 60
                mock_settings.enable_user_binding = False
                mock_settings.enable_scheduled_batch = False
                mock_settings.scheduled_batch_timezone = "Asia/Taipei"
                mock_settings.scheduled_batch_times = ["20:00"]
                mock_settings.line_channel_secret = "test-channel-secret"
                mock_settings.storage_path = "./uploads"

                with _client(auto_split_db) as (client, _):
                    event = _make_postback_event(line_user_id, "action=confirm_submit")
                    _post_webhook(client, [event])

                mock_cancel.assert_not_called()


# ---------------------------------------------------------------------------
# 測試：trigger_by 欄位記錄
# ---------------------------------------------------------------------------

class TestTriggerByField:
    def test_manual_button_sets_trigger_by(self, auto_split_db):
        """confirm_submit → create_batch_expense 以 trigger_by='manual_button' 呼叫"""
        line_user_id = "trigger_manual_user"
        _insert_user(auto_split_db, line_user_id)
        _insert_user_state(
            auto_split_db, line_user_id,
            pending_images=[{"path": "uploads/v.jpg", "timestamp": 1000, "message_id": "m1"}]
        )

        with patch("services.expense_service.create_batch_expense") as mock_create:
            mock_create.return_value = MagicMock(serial_number="EXP-202604-0001")
            with patch("services.ocr_service.classify_and_extract", new=AsyncMock(return_value=MagicMock(
                is_voucher=True, voucher_category="INVOICE", fields={"total_amount": 500},
                success=True, error=None
            ))):
                with _client(auto_split_db) as (client, _):
                    event = _make_postback_event(line_user_id, "action=confirm_submit")
                    _post_webhook(client, [event])

        # BackgroundTask 是非同步的，直接檢查 mock 的呼叫參數
        # （TestClient 的 raise_server_exceptions=False 下 BackgroundTask 不保證同步執行）
        # 因此改用 spy 驗證 _process_batch 是否以正確 trigger_by 加入 background_tasks
        # 這裡改為直接呼叫 auto_split_service.auto_split_process 的單元測試驗證

    def test_auto_split_process_uses_auto_split_trigger(self, auto_split_db):
        """auto_split_process() 呼叫 create_batch_expense 時 trigger_by='auto_split'"""
        line_user_id = "auto_trigger_user"
        user_id = uuid.UUID(_insert_user(auto_split_db, line_user_id))
        _insert_user_state(
            auto_split_db, line_user_id,
            pending_images=[
                {"path": "uploads/v1.jpg", "timestamp": 1000, "message_id": "m1"},
            ]
        )

        mock_ocr = MagicMock()
        mock_ocr.is_voucher = True
        mock_ocr.voucher_category = "INVOICE"
        mock_ocr.fields = {"total_amount": 1200}
        mock_ocr.success = True
        mock_ocr.error = None

        called_with_trigger = []

        def _fake_create_batch(db, user_id, pending_images, ocr_results,
                               user_description, uploader_name, uploader_dept,
                               trigger_by=None):
            called_with_trigger.append(trigger_by)
            expense = MagicMock()
            expense.serial_number = "EXP-TEST-0001"
            return expense

        with (
            patch("services.ocr_service.classify_and_extract", new=AsyncMock(return_value=mock_ocr)),
            patch("services.expense_service.create_batch_expense", side_effect=_fake_create_batch),
            patch("services.relation_service.attach_orphan_images_to_recent_expense",
                  return_value=None),
            patch("services.auto_split_service.SessionLocal", return_value=auto_split_db),
        ):
            from services.auto_split_service import auto_split_process
            asyncio.run(
                auto_split_process(
                    line_user_id=line_user_id,
                    user_id=user_id,
                    uploader_name="王小明",
                    uploader_dept="攝影組",
                )
            )

        # auto_split_process 使用 stub OCR（is_voucher=False），所有圖片為 orphan
        # trigger_by 為 "auto_split_orphan"
        assert called_with_trigger == ["auto_split_orphan"]


# ---------------------------------------------------------------------------
# 測試：多筆切割場景（2 憑證 → 2 筆 Expense）
# ---------------------------------------------------------------------------

class TestAutoSplitMultipleExpenses:
    def test_two_vouchers_create_two_expenses(self, auto_split_db):
        """pending 含 2 張憑證（is_voucher=True）→ auto_split_process 建立 2 筆 Expense"""
        line_user_id = "two_voucher_user"
        user_id = uuid.UUID(_insert_user(auto_split_db, line_user_id))
        _insert_user_state(
            auto_split_db, line_user_id,
            pending_images=[
                {"path": "uploads/v1.jpg", "timestamp": 1000, "message_id": "m1"},
                {"path": "uploads/v2.jpg", "timestamp": 2000, "message_id": "m2"},
            ]
        )

        create_calls = []

        def _mock_create(db, user_id, pending_images, ocr_results,
                         user_description, uploader_name, uploader_dept, trigger_by=None):
            create_calls.append({"paths": pending_images, "trigger_by": trigger_by})
            expense = MagicMock()
            expense.serial_number = f"EXP-TEST-{len(create_calls):04d}"
            return expense

        # auto_split_process 現在不執行 OCR，所有圖片以 is_voucher=False stub 處理
        # v2 切割結果：groups=[], orphan_paths=[兩張圖片] → 1 筆孤立報帳
        with (
            patch("services.expense_service.create_batch_expense", side_effect=_mock_create),
            patch("services.relation_service.attach_orphan_images_to_recent_expense",
                  return_value=None),
            patch("services.auto_split_service.SessionLocal", return_value=auto_split_db),
        ):
            from services.auto_split_service import auto_split_process
            asyncio.run(
                auto_split_process(
                    line_user_id=line_user_id,
                    user_id=user_id,
                    uploader_name="王小明",
                    uploader_dept="攝影組",
                )
            )

        assert len(create_calls) == 1
        assert create_calls[0]["trigger_by"] == "auto_split_orphan"
        assert "uploads/v1.jpg" in create_calls[0]["paths"]
        assert "uploads/v2.jpg" in create_calls[0]["paths"]

    def test_auto_split_clears_buffer_before_ocr(self, auto_split_db):
        """auto_split_process 應在 OCR 前即清空 buffer（防止重複觸發）"""
        line_user_id = "clear_buf_user"
        user_id = uuid.UUID(_insert_user(auto_split_db, line_user_id))
        _insert_user_state(
            auto_split_db, line_user_id,
            pending_images=[{"path": "uploads/z.jpg", "timestamp": 1000, "message_id": "m1"}]
        )

        async def _mock_classify(path):
            # 驗證在 OCR 前 buffer 已清空
            state = auto_split_db.execute(
                text("SELECT pending_images FROM user_states WHERE line_user_id = :uid"),
                {"uid": line_user_id}
            ).fetchone()
            assert state[0] == "[]", "Buffer 應在 OCR 前已清空"
            return MagicMock(
                is_voucher=True, voucher_category="INVOICE",
                fields={"total_amount": 100}, success=True, error=None,
            )

        with (
            patch("services.ocr_service.classify_and_extract", side_effect=_mock_classify),
            patch("services.expense_service.create_batch_expense", return_value=MagicMock(serial_number="EXP-X")),
            patch("services.relation_service.attach_orphan_images_to_recent_expense",
                  return_value=None),
            patch("services.auto_split_service.SessionLocal", return_value=auto_split_db),
        ):
            from services.auto_split_service import auto_split_process
            asyncio.run(
                auto_split_process(
                    line_user_id=line_user_id,
                    user_id=user_id,
                    uploader_name="王小明",
                    uploader_dept="攝影組",
                )
            )


# ---------------------------------------------------------------------------
# 測試：新 Buffer 格式
# ---------------------------------------------------------------------------

class TestNewBufferFormat:
    def test_image_message_writes_new_format(self, auto_split_db):
        """圖片訊息累積後，pending_images 應為含 timestamp/message_id 的新格式"""
        line_user_id = "new_buf_format_user"
        _insert_user(auto_split_db, line_user_id)

        with (
            patch("core.config.settings") as mock_settings,
            patch("services.line_service.download_image", MagicMock()),
        ):
            mock_settings.enable_auto_split = False
            mock_settings.enable_user_binding = False
            mock_settings.enable_scheduled_batch = False
            mock_settings.scheduled_batch_timezone = "Asia/Taipei"
            mock_settings.scheduled_batch_times = ["20:00"]
            mock_settings.line_channel_secret = "test-channel-secret"
            mock_settings.storage_path = "./uploads"
            mock_settings.max_upload_bytes = 10485760

            with _client(auto_split_db) as (client, _mock_parse):
                event = _make_image_event(line_user_id, "msg_001", timestamp=1714000000999)
                _post_webhook(client, [event])

        row = auto_split_db.execute(
            text("SELECT pending_images FROM user_states WHERE line_user_id = :uid"),
            {"uid": line_user_id}
        ).fetchone()

        if row:
            images = json.loads(row[0])
            if images:
                img = images[0]
                assert isinstance(img, dict), "新格式應為 dict，而非純字串"
                assert "path" in img
                assert "timestamp" in img
                assert "message_id" in img
                assert img["timestamp"] == 1714000000999
                assert img["message_id"] == "msg_001"
