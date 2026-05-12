"""add SUPPLEMENTED to expense_status enum

Revision ID: j7c8d9e0f1a2
Revises: i6d7e8f9a0b1
Create Date: 2026-04-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "j7c8d9e0f1a2"
down_revision: Union[str, None] = "i6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL 允許以 ALTER TYPE ... ADD VALUE 安全新增 enum 值
    op.execute("ALTER TYPE expense_status ADD VALUE IF NOT EXISTS 'SUPPLEMENTED'")


def downgrade() -> None:
    # PostgreSQL 不支援直接移除 enum 值；需重建 type 並遷移資料
    # 將 SUPPLEMENTED 的資料退回 PENDING，再重建 enum
    op.execute("""
        UPDATE expenses SET status = 'PENDING' WHERE status = 'SUPPLEMENTED'
    """)
    op.execute("""
        ALTER TYPE expense_status RENAME TO expense_status_old
    """)
    op.execute("""
        CREATE TYPE expense_status AS ENUM (
            'PENDING', 'APPROVED', 'REJECTED', 'NEEDS_MANUAL_REVIEW'
        )
    """)
    op.execute("""
        ALTER TABLE expenses
            ALTER COLUMN status TYPE expense_status
            USING status::text::expense_status
    """)
    op.execute("DROP TYPE expense_status_old")
