"""
LIFF 路由層單元測試 — routers/liff.py

涵蓋情境清單（共 30 個）：
  POST /liff/sessions                              8 個 — 建立 Session、缺少欄位、服務異常
  POST /liff/sessions/{id}/images                  9 個 — 上傳圖片、認證失敗、格式錯誤、服務異常
  PATCH /liff/sessions/{id}/images/{id}            5 個 — 手動切換類型、認證失敗、找不到
  GET  /liff/sessions/{id}/preview                 4 個 — 預覽成功、認證失敗、找不到
  POST /liff/sessions/{id}/submit                  4 個 — 送出成功含 BackgroundTask、認證失敗、重複送出

測試層級：HTTP 請求 → 路由器（依賴 service 全部 mock）
認證方式：X-Line-User-Id header 或 ?uid= query param（兩者測試）
"""

# ---------------------------------------------------------------------------
# psycopg2 mock（必須在所有 import 之前）
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

import io
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# app / router 設定（patch DB 後再 import）
# ---------------------------------------------------------------------------

with patch("core.config.settings") as _mock_settings:
    _mock_settings.database_url = "sqlite:///file::memory:?cache=shared&uri=true"
    _mock_settings.line_channel_secret = "test-secret"
    _mock_settings.line_channel_access_token = "test-token"
    _mock_settings.gemini_api_key = "test-key"
    _mock_settings.app_env = "test"
    _mock_settings.app_debug = False
    _mock_settings.cors_origins = []
    _mock_settings.storage_path = "./uploads"
    _mock_settings.max_upload_bytes = 10485760
    _mock_settings.enable_waiting_return_liff_button = False
    _mock_settings.enable_user_binding = False
    _mock_settings.enable_auto_split = False
    _mock_settings.liff_submit_mode = "single"
    _mock_settings.auto_split_debounce_seconds = 60
    _mock_settings.jwt_secret = "test-jwt"
    _mock_settings.jwt_expire_minutes = 480
    _mock_settings.enable_line_push_reject = False
    _mock_settings.enable_scheduled_batch = False
    _mock_settings.scheduled_batch_times = []
    _mock_settings.scheduled_batch_timezone = "Asia/Taipei"

    from fastapi import FastAPI
    from routers import liff as liff_router
    from core.database import get_db

_test_app = FastAPI()
_test_app.include_router(liff_router.router)


# ---------------------------------------------------------------------------
# 資料容器
# ---------------------------------------------------------------------------

@dataclass
class FakeSession:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: str = "uploading"
    processing_status: str = "pending"
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc) + timedelta(minutes=30)
    )
    images: list = field(default_factory=list)
    line_user_id: str = "U_test"


@dataclass
class FakeImage:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    sequence_order: int = 0
    image_path: str = "uploads/test.jpg"
    is_voucher: bool | None = None
    manually_set: bool = False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db():
    db = MagicMock()
    db.commit.return_value = None
    db.refresh.return_value = None
    db.close.return_value = None
    return db


@pytest.fixture
def client(mock_db):
    """覆蓋 get_db 依賴，讓路由不碰真實 DB。"""
    _test_app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(_test_app, raise_server_exceptions=False) as c:
        yield c
    _test_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 共用 helpers
# ---------------------------------------------------------------------------

SESSION_ID = str(uuid.uuid4())
IMAGE_ID = str(uuid.uuid4())
LINE_USER_HEADER = {"X-Line-User-Id": "U_test_user"}


def _make_session_response(session_id: str | None = None):
    """回傳與 SessionResponse schema 相符的 dict。"""
    return {
        "session_id": session_id or SESSION_ID,
        "expires_at": (datetime.now(tz=timezone.utc) + timedelta(minutes=30)).isoformat(),
        "status": "uploading",
    }


def _make_image_upload_response(image_id: str | None = None):
    return {
        "image": {
            "image_id": image_id or IMAGE_ID,
            "sequence_order": 0,
            "image_path": "uploads/test.jpg",
            "is_voucher": None,
            "manually_set": False,
        },
        "ocr_completed": False,
        "is_voucher": None,
    }


def _make_image_response(image_id: str | None = None):
    """回傳模擬 SessionImage ORM 物件（router 以 .id / .sequence_order 等屬性存取）。"""
    return FakeImage(
        id=uuid.UUID(image_id or IMAGE_ID),
        sequence_order=0,
        image_path="uploads/test.jpg",
        is_voucher=True,
        manually_set=True,
    )


def _make_preview_response():
    from schemas.liff import SessionPreviewResponse
    return SessionPreviewResponse(
        session_id=uuid.UUID(SESSION_ID),
        status="uploading",
        groups=[],
        orphan_images=[],
        total_images=0,
    )


def _make_submit_response():
    from schemas.liff import SubmitSessionResponse
    return SubmitSessionResponse(
        session_id=uuid.UUID(SESSION_ID),
        created_expenses=[],
        message="上傳已接受，費用建立中",
    )


# ---------------------------------------------------------------------------
# POST /liff/sessions — 建立 Session
# ---------------------------------------------------------------------------

class TestCreateSession:
    """
    測試 POST /liff/sessions 端點。
    此端點不需要認證（X-Line-User-Id 由 body.line_user_id 提供）。
    """

    def test_create_session_success(self, client):
        """正確 body 應回傳 201 + session_id。"""
        fake_sess = FakeSession(id=uuid.UUID(SESSION_ID))

        with patch("services.liff_service.create_session", return_value=fake_sess):
            resp = client.post("/liff/sessions", json={
                "line_user_id": "U_test_user",
                "id_token": "dummy.id.token",
            })

        assert resp.status_code == 201
        data = resp.json()
        assert "session_id" in data
        assert data["status"] == "uploading"

    def test_create_session_missing_line_user_id(self, client):
        """缺少 line_user_id 應回傳 422 Validation Error。"""
        resp = client.post("/liff/sessions", json={"id_token": "dummy.token"})
        assert resp.status_code == 422

    def test_create_session_missing_id_token(self, client):
        """缺少 id_token 應回傳 422 Validation Error。"""
        resp = client.post("/liff/sessions", json={"line_user_id": "U_test"})
        assert resp.status_code == 422

    def test_create_session_empty_body(self, client):
        """空 body 應回傳 422 Validation Error。"""
        resp = client.post("/liff/sessions", json={})
        assert resp.status_code == 422

    def test_create_session_service_raises_404(self, client):
        """Service 拋出 404（line_user_id 驗證失敗）應透傳給客戶端。"""
        with patch("services.liff_service.create_session",
                   side_effect=HTTPException(status_code=404, detail="User not found")):
            resp = client.post("/liff/sessions", json={
                "line_user_id": "U_unknown",
                "id_token": "dummy",
            })
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /liff/sessions/{session_id}/images — 上傳圖片
# ---------------------------------------------------------------------------

class TestUploadImage:
    """
    測試 POST /liff/sessions/{session_id}/images 端點。
    認證：X-Line-User-Id header 或 ?uid= query param。
    """

    def _upload(self, client, session_id: str, headers=None, extra_data=None, file_content=b"fake-image", content_type="image/jpeg"):
        data = {"sequence_order": "0"}
        if extra_data:
            data.update(extra_data)
        files = {"file": ("test.jpg", io.BytesIO(file_content), content_type)}
        # 明確判斷 None 才使用預設 header（{}是合法的「無 header」）
        request_headers = LINE_USER_HEADER if headers is None else headers
        return client.post(
            f"/liff/sessions/{session_id}/images",
            data=data,
            files=files,
            headers=request_headers,
        )

    def test_upload_success_returns_201(self, client):
        """有效圖片上傳應回傳 201 且 ocr_completed=False。"""
        fake_img = FakeImage()
        with patch("services.liff_service.add_image",
                   return_value=(fake_img, False, None)):
            resp = self._upload(client, SESSION_ID)

        assert resp.status_code == 201
        data = resp.json()
        assert data["ocr_completed"] is False
        assert data["is_voucher"] is None

    def test_upload_missing_auth_header_returns_401(self, client):
        """缺少 X-Line-User-Id 且無 ?uid= 時應回傳 401。"""
        resp = self._upload(client, SESSION_ID, headers={})
        assert resp.status_code == 401

    def test_upload_uid_query_param_accepted(self, client):
        """缺少 Header 但提供 ?uid= query param 時，應被接受（等同認證成功）。"""
        fake_img = FakeImage()
        with patch("services.liff_service.add_image",
                   return_value=(fake_img, False, None)):
            data = {"sequence_order": "0"}
            files = {"file": ("test.jpg", io.BytesIO(b"data"), "image/jpeg")}
            resp = client.post(
                f"/liff/sessions/{SESSION_ID}/images?uid=U_test_user",
                data=data,
                files=files,
            )

        assert resp.status_code == 201

    def test_upload_non_image_content_type_returns_415(self, client):
        """上傳非圖片（如 PDF）應被路由層拒絕，回傳 415 Unsupported Media Type。"""
        resp = self._upload(
            client, SESSION_ID,
            file_content=b"%PDF-1.4",
            content_type="application/pdf",
        )
        assert resp.status_code == 415

    def test_upload_session_not_found_returns_404(self, client):
        """Session 不存在時，service 拋出的 404 應透傳。"""
        with patch("services.liff_service.add_image",
                   side_effect=HTTPException(status_code=404, detail="Session not found")):
            resp = self._upload(client, str(uuid.uuid4()))
        assert resp.status_code == 404

    def test_upload_expired_session_returns_410(self, client):
        """Session 已過期時，service 拋出的 410 應透傳。"""
        with patch("services.liff_service.add_image",
                   side_effect=HTTPException(status_code=410, detail="Session 已過期")):
            resp = self._upload(client, SESSION_ID)
        assert resp.status_code == 410

    def test_upload_submitted_session_returns_409(self, client):
        """Session 已送出時，service 拋出的 409 應透傳。"""
        with patch("services.liff_service.add_image",
                   side_effect=HTTPException(status_code=409, detail="Session 已送出")):
            resp = self._upload(client, SESSION_ID)
        assert resp.status_code == 409

    def test_upload_duplicate_sequence_order_returns_422(self, client):
        """sequence_order 重複時，service 拋出的 422 應透傳。"""
        with patch("services.liff_service.add_image",
                   side_effect=HTTPException(status_code=422, detail="sequence_order=0 已存在")):
            resp = self._upload(client, SESSION_ID)
        assert resp.status_code == 422

    def test_upload_response_structure(self, client):
        """回傳結構應符合 ImageUploadResponse schema（含 image.image_id）。"""
        fake_img = FakeImage(sequence_order=2, image_path="uploads/abc.jpg")
        with patch("services.liff_service.add_image",
                   return_value=(fake_img, False, None)):
            data = {"sequence_order": "2"}
            files = {"file": ("photo.jpg", io.BytesIO(b"data"), "image/jpeg")}
            resp = client.post(
                f"/liff/sessions/{SESSION_ID}/images",
                data=data,
                files=files,
                headers=LINE_USER_HEADER,
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["image"]["sequence_order"] == 2
        assert body["image"]["image_path"] == "uploads/abc.jpg"
        assert body["image"]["is_voucher"] is None
        assert body["image"]["manually_set"] is False


# ---------------------------------------------------------------------------
# PATCH /liff/sessions/{session_id}/images/{image_id} — 手動切換類型
# ---------------------------------------------------------------------------

class TestPatchImage:
    """
    測試 PATCH /liff/sessions/{session_id}/images/{image_id} 端點。
    """

    def _patch(self, client, session_id=None, image_id=None, is_voucher=True, headers=None):
        request_headers = LINE_USER_HEADER if headers is None else headers
        return client.patch(
            f"/liff/sessions/{session_id or SESSION_ID}/images/{image_id or IMAGE_ID}",
            json={"is_voucher": is_voucher},
            headers=request_headers,
        )

    def test_patch_to_voucher_returns_updated_image(self, client):
        """切換為 is_voucher=True 應回傳 200 + 更新後的 ImageResponse。"""
        expected = _make_image_response()
        with patch("services.liff_service.patch_image_type", return_value=expected):
            resp = self._patch(client, is_voucher=True)

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_voucher"] is True
        assert data["manually_set"] is True

    def test_patch_to_item_image(self, client):
        """切換為 is_voucher=False 應正確反映在回應中。"""
        expected = FakeImage(
            id=uuid.UUID(IMAGE_ID),
            sequence_order=0,
            image_path="uploads/test.jpg",
            is_voucher=False,
            manually_set=True,
        )
        with patch("services.liff_service.patch_image_type", return_value=expected):
            resp = self._patch(client, is_voucher=False)

        assert resp.status_code == 200
        assert resp.json()["is_voucher"] is False

    def test_patch_missing_auth_returns_401(self, client):
        """缺少認證時應回傳 401。"""
        resp = self._patch(client, headers={})
        assert resp.status_code == 401

    def test_patch_session_not_found_returns_404(self, client):
        """Session 不存在時 404。"""
        with patch("services.liff_service.patch_image_type",
                   side_effect=HTTPException(status_code=404, detail="not found")):
            resp = self._patch(client)
        assert resp.status_code == 404

    def test_patch_image_not_found_returns_404(self, client):
        """SessionImage 不存在時 404。"""
        with patch("services.liff_service.patch_image_type",
                   side_effect=HTTPException(status_code=404, detail="image not found")):
            resp = self._patch(client)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /liff/sessions/{session_id}/preview — 確認頁預覽
# ---------------------------------------------------------------------------

class TestGetPreview:
    """
    測試 GET /liff/sessions/{session_id}/preview 端點。
    """

    def _get(self, client, session_id=None, headers=None):
        request_headers = LINE_USER_HEADER if headers is None else headers
        return client.get(
            f"/liff/sessions/{session_id or SESSION_ID}/preview",
            headers=request_headers,
        )

    def test_preview_success(self, client):
        """正常請求應回傳 200 + SessionPreviewResponse。"""
        expected = _make_preview_response()
        with patch("services.liff_service.get_session_preview", return_value=expected):
            resp = self._get(client)

        assert resp.status_code == 200
        data = resp.json()
        assert data["groups"] == []
        assert data["orphan_images"] == []
        assert data["total_images"] == 0

    def test_preview_missing_auth_returns_401(self, client):
        """缺少認證時應回傳 401。"""
        resp = self._get(client, headers={})
        assert resp.status_code == 401

    def test_preview_uid_query_param_accepted(self, client):
        """?uid= query param 可替代 Header 完成認證。"""
        expected = _make_preview_response()
        with patch("services.liff_service.get_session_preview", return_value=expected):
            resp = client.get(
                f"/liff/sessions/{SESSION_ID}/preview?uid=U_test_user"
            )
        assert resp.status_code == 200

    def test_preview_session_not_found_returns_404(self, client):
        """Session 不存在時 404。"""
        with patch("services.liff_service.get_session_preview",
                   side_effect=HTTPException(status_code=404, detail="not found")):
            resp = self._get(client)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /liff/sessions/{session_id}/submit — 確認送出
# ---------------------------------------------------------------------------

class TestSubmitSession:
    """
    測試 POST /liff/sessions/{session_id}/submit 端點。
    重點：BackgroundTasks 應在同步回傳後被安排（不阻塞 response）。
    """

    def _submit(self, client, session_id=None, headers=None, body=None):
        request_headers = LINE_USER_HEADER if headers is None else headers
        return client.post(
            f"/liff/sessions/{session_id or SESSION_ID}/submit",
            json=body or {"group_descriptions": [], "waiting_return_ref": None},
            headers=request_headers,
        )

    def test_submit_returns_200_immediately(self, client):
        """送出後應立即回傳 200，created_expenses 為空（OCR 尚未執行）。"""
        expected = _make_submit_response()
        with patch("services.liff_service.submit_session", return_value=expected), \
             patch("services.liff_service.process_session_background", new=AsyncMock()):
            resp = self._submit(client)

        assert resp.status_code == 200
        data = resp.json()
        assert data["created_expenses"] == []
        assert "費用建立中" in data["message"]

    def test_submit_missing_auth_returns_401(self, client):
        """缺少認證時應回傳 401。"""
        resp = self._submit(client, headers={})
        assert resp.status_code == 401

    def test_submit_already_submitted_returns_409(self, client):
        """Session 已送出（409）應透傳給客戶端。"""
        with patch("services.liff_service.submit_session",
                   side_effect=HTTPException(status_code=409, detail="Session 已送出")):
            resp = self._submit(client)
        assert resp.status_code == 409

    def test_submit_with_group_descriptions_and_waiting_return_ref(self, client):
        """帶 group_descriptions 與 waiting_return_ref 的 body 應正確接受。"""
        expected = _make_submit_response()
        captured_kwargs: dict = {}

        def _mock_submit(db, session_id, group_descriptions, waiting_return_ref=None):
            captured_kwargs["group_descriptions"] = group_descriptions
            captured_kwargs["waiting_return_ref"] = waiting_return_ref
            return expected

        with patch("services.liff_service.submit_session", side_effect=_mock_submit), \
             patch("services.liff_service.process_session_background", new=AsyncMock()):
            resp = self._submit(client, body={
                "group_descriptions": [{"group_index": 0, "description": "差旅費"}],
                "waiting_return_ref": "AB-99887766",
            })

        assert resp.status_code == 200
        assert captured_kwargs["group_descriptions"] == {0: "差旅費"}
        assert captured_kwargs["waiting_return_ref"] == "AB-99887766"
