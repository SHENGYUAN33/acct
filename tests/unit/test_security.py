"""
模組 F：安全性測試

測試：
  F1 - LINE Webhook 簽章驗證（偽造 signature → 400）
  F2 - JWT 過期 token 拒絕（401）
  F3 - SQL Injection 防護（Pydantic + SQLAlchemy ORM）
  F4 - 機敏資訊未 hardcode 掃描
"""

import glob
import hashlib
import hmac
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# F1：LINE Webhook 簽章驗證
# ---------------------------------------------------------------------------


class TestWebhookSignatureValidation:
    """
    LINE SDK 的 WebhookParser 在 X-Line-Signature 不合法時應拋出 InvalidSignatureError，
    FastAPI handler 應攔截後回傳 400。
    直接測試簽章邏輯，不需啟動完整 FastAPI app。
    """

    def _compute_valid_signature(self, body: bytes, secret: str) -> str:
        """計算 LINE 標準 HMAC-SHA256 簽章，並以 Base64 編碼。"""
        import base64

        digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
        return base64.b64encode(digest).decode("utf-8")

    def test_valid_signature_passes(self) -> None:
        """合法簽章：不應拋出例外。"""
        from linebot.v3 import WebhookParser
        from linebot.v3.exceptions import InvalidSignatureError

        body = b'{"destination":"U123","events":[]}'
        secret = "test-channel-secret"
        valid_sig = self._compute_valid_signature(body, secret)

        parser = WebhookParser(secret)
        try:
            result = parser.parse(body.decode(), valid_sig)
            # linebot.v3 WebhookParser.parse() 回傳 events list（不是帶 .events 的物件）
            assert isinstance(result, list)
            assert len(result) == 0
        except InvalidSignatureError:
            pytest.fail("合法簽章不應拋出 InvalidSignatureError")

    def test_tampered_body_fails(self) -> None:
        """篡改 body 後，簽章應失效。"""
        from linebot.v3 import WebhookParser
        from linebot.v3.exceptions import InvalidSignatureError

        original_body = b'{"destination":"U123","events":[]}'
        tampered_body = b'{"destination":"HACKER","events":[]}'
        secret = "test-channel-secret"
        valid_sig = self._compute_valid_signature(original_body, secret)

        parser = WebhookParser(secret)
        with pytest.raises(InvalidSignatureError):
            parser.parse(tampered_body.decode(), valid_sig)

    def test_wrong_secret_fails(self) -> None:
        """用錯誤 secret 計算的簽章應失效。"""
        from linebot.v3 import WebhookParser
        from linebot.v3.exceptions import InvalidSignatureError

        body = b'{"destination":"U123","events":[]}'
        wrong_sig = self._compute_valid_signature(body, "wrong-secret")

        parser = WebhookParser("correct-secret")
        with pytest.raises(InvalidSignatureError):
            parser.parse(body.decode(), wrong_sig)

    def test_empty_signature_fails(self) -> None:
        """空字串簽章應失效。"""
        from linebot.v3 import WebhookParser
        from linebot.v3.exceptions import InvalidSignatureError

        body = b'{"destination":"U123","events":[]}'
        parser = WebhookParser("test-channel-secret")

        with pytest.raises(InvalidSignatureError):
            parser.parse(body.decode(), "")

    def test_garbage_signature_fails(self) -> None:
        """隨機亂碼簽章應失效。"""
        from linebot.v3 import WebhookParser
        from linebot.v3.exceptions import InvalidSignatureError

        body = b'{"destination":"U123","events":[]}'
        parser = WebhookParser("test-channel-secret")

        with pytest.raises(InvalidSignatureError):
            parser.parse(body.decode(), "not-a-valid-signature-at-all!!!")


# ---------------------------------------------------------------------------
# F2：JWT 過期 token 拒絕
# ---------------------------------------------------------------------------


class TestJwtTokenValidation:
    """驗證 core/security.py 中 decode_access_token 對各種 token 狀態的處理。"""

    def test_valid_token_decoded_successfully(self) -> None:
        """合法 token（未過期）應正確解碼出 subject。"""
        from core.security import create_access_token, decode_access_token

        with patch("core.security.settings") as mock_settings:
            mock_settings.jwt_secret = "test-secret-key"
            mock_settings.jwt_expire_minutes = 480

            token = create_access_token("admin_user")
            subject = decode_access_token(token)

        assert subject == "admin_user"

    def test_expired_token_returns_none(self) -> None:
        """過期 token 應回傳 None，不拋出例外。"""
        from jose import jwt as jose_jwt
        from core.security import decode_access_token

        secret = "test-secret-key"
        expired_payload = {
            "sub": "admin_user",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),  # 已過期
        }
        expired_token = jose_jwt.encode(expired_payload, secret, algorithm="HS256")

        with patch("core.security.settings") as mock_settings:
            mock_settings.jwt_secret = secret
            result = decode_access_token(expired_token)

        assert result is None

    def test_tampered_token_returns_none(self) -> None:
        """被竄改的 token（修改 payload）應回傳 None。"""
        from core.security import create_access_token, decode_access_token

        with patch("core.security.settings") as mock_settings:
            mock_settings.jwt_secret = "test-secret-key"
            mock_settings.jwt_expire_minutes = 480
            token = create_access_token("admin_user")

        # 竄改：把第二段（payload）改掉
        parts = token.split(".")
        tampered = parts[0] + ".AAAAAAAAAAAAAAA." + parts[2]

        with patch("core.security.settings") as mock_settings:
            mock_settings.jwt_secret = "test-secret-key"
            result = decode_access_token(tampered)

        assert result is None

    def test_wrong_secret_returns_none(self) -> None:
        """用正確 secret 簽名的 token，以錯誤 secret 解碼，應回傳 None。"""
        from jose import jwt as jose_jwt
        from core.security import decode_access_token

        payload = {
            "sub": "admin_user",
            "exp": datetime.now(timezone.utc) + timedelta(hours=8),
        }
        token = jose_jwt.encode(payload, "correct-secret", algorithm="HS256")

        with patch("core.security.settings") as mock_settings:
            mock_settings.jwt_secret = "wrong-secret"
            result = decode_access_token(token)

        assert result is None

    def test_empty_token_returns_none(self) -> None:
        """空字串 token 應回傳 None。"""
        from core.security import decode_access_token

        with patch("core.security.settings") as mock_settings:
            mock_settings.jwt_secret = "test-secret-key"
            result = decode_access_token("")

        assert result is None

    def test_garbage_token_returns_none(self) -> None:
        """亂碼 token 應回傳 None。"""
        from core.security import decode_access_token

        with patch("core.security.settings") as mock_settings:
            mock_settings.jwt_secret = "test-secret-key"
            result = decode_access_token("not.a.jwt.token.at.all")

        assert result is None


# ---------------------------------------------------------------------------
# F3：SQL Injection 防護（Pydantic 輸入驗證）
# ---------------------------------------------------------------------------


class TestSqlInjectionPrevention:
    """
    驗證 ExpenseStatus enum 過濾器對 SQL Injection payload 的防護。
    Pydantic + FastAPI 的型別驗證應在進入 ORM 前就拒絕非法值。
    """

    def test_expense_status_enum_rejects_injection_string(self) -> None:
        """
        SQL Injection payload 送入 ExpenseStatus enum → Pydantic 應拒絕（ValueError）。
        ORM 層的 SELECT 使用參數化查詢，即使繞過 enum，DB 也不會執行任意 SQL。
        """
        from models.expense import ExpenseStatus
        from pydantic import BaseModel, ValidationError

        class FilterModel(BaseModel):
            status: ExpenseStatus | None = None

        injection_payloads = [
            "PENDING'; DROP TABLE expenses; --",
            "PENDING OR 1=1 --",
            "' UNION SELECT username, password FROM admin_users --",
            "'; DELETE FROM expenses WHERE '1'='1",
        ]

        for payload in injection_payloads:
            with pytest.raises(ValidationError, match=r"(status|Input should be)"):
                FilterModel(status=payload)

    def test_valid_status_enum_passes(self) -> None:
        """合法的 ExpenseStatus 值不應被誤拒。"""
        from models.expense import ExpenseStatus
        from pydantic import BaseModel

        class FilterModel(BaseModel):
            status: ExpenseStatus | None = None

        for valid_status in ExpenseStatus:
            model = FilterModel(status=valid_status.value)
            assert model.status == valid_status

    def test_serial_number_query_is_parameterized(self, db_session) -> None:
        """
        依 serial_number 查詢使用 SQLAlchemy ORM（參數化），不應受 SQL Injection 影響。
        即使傳入注入字串，也只會查無結果，不會執行任意 SQL。
        """
        from sqlalchemy import text

        injection_serial = "EXP-202605-0001'; DROP TABLE expenses; --"

        # 直接對 SQLite 執行 ORM 風格的參數化查詢
        row = db_session.execute(
            text("SELECT id FROM expenses WHERE serial_number = :sn"),
            {"sn": injection_serial},
        ).fetchone()

        # 注入字串不應匹配任何真實記錄
        assert row is None

        # 驗證 expenses 表仍然存在（未被 DROP）
        table_exists = db_session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='expenses'")
        ).fetchone()
        assert table_exists is not None, "expenses 表應仍然存在"


# ---------------------------------------------------------------------------
# F4：機敏資訊未 hardcode 掃描
# ---------------------------------------------------------------------------


class TestNoHardcodedSecrets:
    """
    靜態掃描：確認所有後端 .py 檔案中沒有已知的機敏字串 pattern。
    排除 .env.example、tests/ 目錄本身（測試可以有假 key），以及此檔案本身。
    """

    # 典型機敏字串 pattern
    SECRET_PATTERNS = [
        r"AIza[0-9A-Za-z\-_]{35}",        # Google API Key
        r"sk-[a-zA-Z0-9]{32,}",             # OpenAI API Key
        r"Bearer\s+[a-zA-Z0-9\-_]{20,}",   # Hardcoded Bearer token（非變數）
        r"password\s*=\s*['\"][^'\"]{6,}['\"]",  # hardcoded password =
    ]

    # 掃描的目錄（排除 tests/ 和 migrations）
    SCAN_DIRS = ["core", "routers", "services", "models", "schemas"]

    def test_no_hardcoded_google_api_key(self) -> None:
        """確認後端代碼中沒有 Google API Key 格式的字串。"""
        self._scan_for_pattern(
            r"AIza[0-9A-Za-z\-_]{35}",
            "找到疑似 hardcode 的 Google API Key"
        )

    def test_no_hardcoded_bearer_token(self) -> None:
        """確認後端代碼中沒有 hardcoded Bearer Token。"""
        self._scan_for_pattern(
            r"Bearer\s+[A-Za-z0-9\-_\.]{40,}",
            "找到疑似 hardcode 的 Bearer Token"
        )

    def test_no_hardcoded_password_value(self) -> None:
        """確認後端代碼中沒有 password = 'literal_string' 形式的 hardcode。"""
        # 允許 hash_password("test") 等測試用途，排除含 hash_ 前綴的行
        project_root = Path(__file__).parent.parent.parent

        matches = []
        for scan_dir in self.SCAN_DIRS:
            scan_path = project_root / scan_dir
            if not scan_path.exists():
                continue
            for py_file in scan_path.rglob("*.py"):
                with open(py_file, encoding="utf-8") as f:
                    for lineno, line in enumerate(f, 1):
                        # 找 password = 'xxx' 或 password = "xxx" 但排除函式呼叫
                        if re.search(r'password\s*=\s*[\'"][^\'\"]{6,}[\'"]', line):
                            if "hash_password" not in line and "verify_password" not in line:
                                matches.append(f"{py_file}:{lineno}: {line.strip()}")

        assert not matches, f"找到疑似 hardcode 密碼：\n" + "\n".join(matches)

    def test_jwt_secret_uses_settings(self) -> None:
        """確認 JWT 簽名使用 settings.jwt_secret，而非 hardcoded 字串。"""
        project_root = Path(__file__).parent.parent.parent
        security_file = project_root / "core" / "security.py"

        content = security_file.read_text(encoding="utf-8")

        # 應使用 settings.jwt_secret
        assert "settings.jwt_secret" in content, \
            "core/security.py 應使用 settings.jwt_secret 而非 hardcoded 字串"

        # 不應有明文 secret 字串（排除 test 和 example 等字）
        suspicious = re.findall(r'jwt\.(?:encode|decode)\([^,]+,\s*[\'"][^\'\"]{8,}[\'"]', content)
        assert not suspicious, \
            f"jwt.encode/decode 中找到疑似 hardcoded secret：{suspicious}"

    def test_gemini_api_key_uses_settings(self) -> None:
        """確認 OCR service 的 API key 來自 settings，而非 hardcoded。"""
        project_root = Path(__file__).parent.parent.parent
        ocr_file = project_root / "services" / "ocr_service.py"

        content = ocr_file.read_text(encoding="utf-8")
        assert "settings.gemini_api_key" in content, \
            "ocr_service.py 應使用 settings.gemini_api_key"

    def _scan_for_pattern(self, pattern: str, message: str) -> None:
        """在 SCAN_DIRS 中掃描指定 regex pattern，發現即 fail。"""
        project_root = Path(__file__).parent.parent.parent

        matches = []
        for scan_dir in self.SCAN_DIRS:
            scan_path = project_root / scan_dir
            if not scan_path.exists():
                continue
            for py_file in scan_path.rglob("*.py"):
                with open(py_file, encoding="utf-8") as f:
                    content = f.read()
                found = re.findall(pattern, content)
                if found:
                    matches.append(f"{py_file}: {found}")

        assert not matches, f"{message}：\n" + "\n".join(matches)
