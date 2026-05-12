"""add expense_images table and batch fields to expenses

Revision ID: k8d9e0f1a2b3
Revises: j7c8d9e0f1a2
Create Date: 2026-04-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import text

revision: str = "k8d9e0f1a2b3"
down_revision: Union[str, None] = "j7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 建立 expense_images 表（IF NOT EXISTS 防止 create_all 已建立時衝突）
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS expense_images (
            id UUID DEFAULT gen_random_uuid() NOT NULL,
            expense_id UUID NOT NULL,
            image_url VARCHAR(512) NOT NULL,
            is_voucher BOOLEAN DEFAULT false NOT NULL,
            voucher_category VARCHAR(64),
            sequence_order INTEGER DEFAULT 1 NOT NULL,
            ocr_result TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT fk_expense_images_expense
                FOREIGN KEY (expense_id) REFERENCES expenses(id) ON DELETE CASCADE
        )
    """))

    # 建立 expense_id 索引（IF NOT EXISTS）
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_expense_images_expense_id
        ON expense_images (expense_id)
    """))

    # expenses 表新增欄位（ADD COLUMN IF NOT EXISTS 防止重複新增）
    conn.execute(text(
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS user_description TEXT"
    ))
    conn.execute(text(
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS image_count INTEGER NOT NULL DEFAULT 1"
    ))
    conn.execute(text(
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS voucher_categories TEXT"
    ))


def downgrade() -> None:
    op.drop_column("expenses", "voucher_categories")
    op.drop_column("expenses", "image_count")
    op.drop_column("expenses", "user_description")
    op.drop_table("expense_images")
