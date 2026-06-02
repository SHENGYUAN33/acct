"""
PostgreSQL 整合測試專用 conftest。

與 tests/conftest.py 完全獨立：
- 不使用 SQLite mock；直接連線 DATABASE_URL 指向的 PostgreSQL
- 若環境變數非 PostgreSQL URL，所有測試自動 skip
- CI 中由 integration-test job 提供 PostgreSQL 16 Service Container

使用方式：
    pytest tests/postgres/ -v
    (需先設定 DATABASE_URL=postgresql+psycopg2://postgres:...@localhost:5432/acctassist_test)
"""

import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

PG_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_IS_POSTGRES = "postgresql" in PG_DATABASE_URL

requires_postgres = pytest.mark.skipif(
    not _IS_POSTGRES,
    reason="跳過：需要 PostgreSQL DATABASE_URL（測試本地端無 PG 時可忽略）",
)


@pytest.fixture(scope="session")
def pg_engine():
    """Session 級別的 PostgreSQL 引擎。"""
    if not _IS_POSTGRES:
        pytest.skip("需要 PostgreSQL DATABASE_URL")
    engine = create_engine(PG_DATABASE_URL, echo=False)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def pg_db(pg_engine) -> Session:
    """每個測試取得獨立 connection + transaction，測試後 rollback。"""
    connection = pg_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, autocommit=False, autoflush=False)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
