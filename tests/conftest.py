"""
共用 pytest fixtures — SQLite in-memory DB + FastAPI TestClient。

注意：因 core/database.py 在 import 時即建立 PostgreSQL engine，
需在最早期 patch settings.database_url 為 SQLite URL，
避免 psycopg2 ModuleNotFoundError。
"""

import importlib
import json
import sys
import uuid
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


# ---------------------------------------------------------------------------
# 在任何 app 模組 import 前，patch core.config.settings.database_url
# 讓 core.database 使用 SQLite 而非 PostgreSQL
# ---------------------------------------------------------------------------

SQLITE_MEMORY_URL = "sqlite:///file::memory:?cache=shared&uri=true"

# 先 patch settings，再讓其他模組 import（conftest 在 test collection 最早執行）
_settings_patcher = patch(
    "core.config.settings",
    **{
        "database_url": SQLITE_MEMORY_URL,
        "line_channel_secret": "test-channel-secret",
        "line_channel_access_token": "test-access-token",
        "gemini_api_key": "test-gemini-key",
        "gemini_model": "gemini-2.5-flash",
        "storage_path": "./uploads",
        "app_env": "test",
        "app_debug": False,
        "jwt_secret": "test-jwt-secret",
        "jwt_expire_minutes": 480,
        "cors_origins": [],
        "max_upload_bytes": 10485760,
        "enable_line_push_reject": True,
        "enable_user_binding": False,  # 測試時預設關閉綁定，簡化流程
        "enable_auto_split": False,    # 測試時預設關閉，需測試自動切割時個別覆寫
        "auto_split_debounce_seconds": 60,
        "app_host": "0.0.0.0",
        "app_port": 8000,
    },
)


# ---------------------------------------------------------------------------
# SQLite in-memory 引擎
# ---------------------------------------------------------------------------

def _create_sqlite_engine():
    """建立 SQLite in-memory 引擎並手動建表（繞過 PostgreSQL 型別限制）。"""
    engine = create_engine(
        SQLITE_MEMORY_URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
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
            CREATE TABLE IF NOT EXISTS user_states (
                line_user_id TEXT PRIMARY KEY,
                step TEXT NOT NULL,
                dept TEXT,
                pending_images TEXT NOT NULL DEFAULT '[]',
                pending_description TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS expenses (
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
                voucher_subtypes TEXT,
                expense_categories TEXT,
                trigger_by TEXT,
                group_id TEXT,
                parent_id TEXT,
                possible_duplicate_of TEXT,
                relation_type TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                void_reason TEXT,
                referenced_invoice_number TEXT,
                display_order INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS expense_images (
                id TEXT PRIMARY KEY,
                expense_id TEXT NOT NULL,
                image_url TEXT NOT NULL,
                is_voucher INTEGER NOT NULL DEFAULT 0,
                voucher_category TEXT,
                voucher_subtype TEXT,
                expense_category TEXT,
                sequence_order INTEGER NOT NULL DEFAULT 1,
                ocr_result TEXT,
                ocr_confidence NUMERIC(4,3),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS admin_users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                hashed_password TEXT NOT NULL,
                display_name TEXT,
                employee_id TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS staff_roster (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                department TEXT NOT NULL,
                employee_id TEXT,
                line_user_id TEXT,
                is_bound INTEGER NOT NULL DEFAULT 0,
                bound_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS liff_upload_sessions (
                id TEXT PRIMARY KEY,
                line_user_id TEXT NOT NULL,
                user_id TEXT,
                status TEXT NOT NULL DEFAULT 'uploading',
                processing_status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS liff_session_images (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                sequence_order INTEGER NOT NULL,
                image_path TEXT NOT NULL,
                is_voucher INTEGER,
                manually_set INTEGER NOT NULL DEFAULT 0,
                ocr_result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.commit()
    return engine


@pytest.fixture(scope="session")
def sqlite_engine():
    """Session 級別的 SQLite in-memory 引擎，整個測試 session 共用。"""
    engine = _create_sqlite_engine()
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(sqlite_engine) -> Generator[Session, None, None]:
    """每個測試取得獨立 DB Session；測試完成後回滾，不汙染其他測試。"""
    connection = sqlite_engine.connect()
    transaction = connection.begin()
    TestingSessionLocal = sessionmaker(bind=connection, autocommit=False, autoflush=False)
    session = TestingSessionLocal()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
