import concurrent.futures
import uuid
from datetime import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from .conftest import requires_postgres


def _truncate_public_tables(pg_engine) -> None:
    """Clear data before migration downgrade tests."""
    with pg_engine.begin() as conn:
        tables = conn.execute(text("""
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename != 'alembic_version'
        """)).scalars().all()
        if tables:
            quoted = ", ".join(f'"{table}"' for table in tables)
            conn.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))


@requires_postgres
class TestArrayFields:
    def test_insert_and_read_array_image_url(self, pg_db) -> None:
        eid = str(uuid.uuid4())
        pg_db.execute(text("""
            INSERT INTO expenses (
                id, serial_number, image_url, item_image_url, status, is_active
            ) VALUES (
                :id, :serial,
                ARRAY['uploads/a.jpg', 'uploads/b.jpg'],
                ARRAY['uploads/item1.jpg'],
                'PENDING', true
            )
        """), {"id": eid, "serial": f"EXP-TEST-A{eid[:4]}"})
        pg_db.commit()

        row = pg_db.execute(
            text("SELECT image_url, item_image_url FROM expenses WHERE id = :id"),
            {"id": eid},
        ).fetchone()

        assert row.image_url == ["uploads/a.jpg", "uploads/b.jpg"]
        assert row.item_image_url == ["uploads/item1.jpg"]

    def test_array_append_via_concatenation(self, pg_db) -> None:
        eid = str(uuid.uuid4())
        pg_db.execute(text("""
            INSERT INTO expenses (id, serial_number, image_url, item_image_url, status, is_active)
            VALUES (:id, :serial, ARRAY['uploads/orig.jpg'], '{}', 'PENDING', true)
        """), {"id": eid, "serial": f"EXP-TEST-B{eid[:4]}"})
        pg_db.commit()

        pg_db.execute(text("""
            UPDATE expenses
            SET image_url = array_append(image_url, 'uploads/new.jpg')
            WHERE id = :id
        """), {"id": eid})
        pg_db.commit()

        row = pg_db.execute(
            text("SELECT image_url FROM expenses WHERE id = :id"),
            {"id": eid},
        ).fetchone()

        assert row.image_url == ["uploads/orig.jpg", "uploads/new.jpg"]

    def test_empty_array_default(self, pg_db) -> None:
        eid = str(uuid.uuid4())
        pg_db.execute(text("""
            INSERT INTO expenses (id, serial_number, status, is_active)
            VALUES (:id, :serial, 'PENDING', true)
        """), {"id": eid, "serial": f"EXP-TEST-C{eid[:4]}"})
        pg_db.commit()

        row = pg_db.execute(
            text("SELECT image_url, item_image_url FROM expenses WHERE id = :id"),
            {"id": eid},
        ).fetchone()

        assert row.image_url is not None
        assert isinstance(row.image_url, list)
        assert row.item_image_url is not None
        assert isinstance(row.item_image_url, list)


@requires_postgres
class TestSerialNumberUniqueness:
    def test_concurrent_50_inserts_no_duplicate_serial(self, pg_engine) -> None:
        prefix = datetime.now().strftime("%Y%m")
        inserted_serials: list[str] = []

        def insert_one(_: int) -> str:
            SessionLocal = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)
            session = SessionLocal()
            try:
                seq = session.execute(text("SELECT nextval('expense_serial_seq')")).scalar_one()
                serial = f"EXP-{prefix}-{int(seq):04d}"
                session.execute(text("""
                    INSERT INTO expenses (
                        id, serial_number, image_url, item_image_url, status, is_active
                    ) VALUES (
                        :id, :serial, '{}', '{}', 'PENDING', true
                    )
                """), {"id": str(uuid.uuid4()), "serial": serial})
                session.commit()
                return serial
            finally:
                session.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(insert_one, i) for i in range(50)]
            for future in concurrent.futures.as_completed(futures):
                inserted_serials.append(future.result())

        assert len(inserted_serials) == 50
        assert len(set(inserted_serials)) == 50


@requires_postgres
class TestILIKESearch:
    def test_ilike_case_insensitive_uploader_name(self, pg_db) -> None:
        eid = str(uuid.uuid4())
        pg_db.execute(text("""
            INSERT INTO expenses (
                id, serial_number, uploader_name, status, image_url, item_image_url, is_active
            ) VALUES (
                :id, :serial, 'Alice Chen', 'PENDING', '{}', '{}', true
            )
        """), {"id": eid, "serial": f"EXP-ILIKE-{eid[:6]}"})
        pg_db.commit()

        lower = pg_db.execute(
            text("SELECT id FROM expenses WHERE uploader_name ILIKE :q"),
            {"q": "%alice%"},
        ).fetchall()
        upper = pg_db.execute(
            text("SELECT id FROM expenses WHERE uploader_name ILIKE :q"),
            {"q": "%ALICE%"},
        ).fetchall()

        assert eid in [str(row.id) for row in lower]
        assert eid in [str(row.id) for row in upper]


@requires_postgres
class TestAlembicMigrations:
    def test_upgrade_head_creates_all_tables(self, pg_engine) -> None:
        from alembic import command
        from alembic.config import Config

        # 直接 drop/recreate schema，避免呼叫 downgrade（部分 migration 不支援）
        with pg_engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", str(pg_engine.url))
        command.upgrade(alembic_cfg, "head")

        with pg_engine.connect() as conn:
            existing_names = set(conn.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
            """)).scalars().all())

        required_tables = {
            "users",
            "user_states",
            "expenses",
            "expense_images",
            "admin_users",
        }
        assert required_tables <= existing_names

    def test_upgrade_creates_expense_status_enum(self, pg_engine) -> None:
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", str(pg_engine.url))
        command.upgrade(alembic_cfg, "head")

        with pg_engine.connect() as conn:
            labels = set(conn.execute(text("""
                SELECT enumlabel
                FROM pg_enum
                JOIN pg_type ON pg_enum.enumtypid = pg_type.oid
                WHERE pg_type.typname = 'expense_status'
                ORDER BY enumsortorder
            """)).scalars().all())

        required_statuses = {
            "PENDING",
            "APPROVED",
            "REJECTED",
            "NEEDS_MANUAL_REVIEW",
            "SUPPLEMENTED",
            "WAITING_RETURN",
            "COMPLETED",
            "REPLACED_VOID",
        }
        assert required_statuses <= labels
