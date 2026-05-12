"""add relation fields, is_active, group_id, void_reason and new expense_status values

Revision ID: p3q4r5s6t7u8
Revises: o2p3q4r5s6t7
Create Date: 2026-04-20 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p3q4r5s6t7u8"
down_revision: Union[str, None] = "o2p3q4r5s6t7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 擴充 PostgreSQL enum（ADD VALUE IF NOT EXISTS 幂等）
    op.execute("ALTER TYPE expense_status ADD VALUE IF NOT EXISTS 'WAITING_RETURN'")
    op.execute("ALTER TYPE expense_status ADD VALUE IF NOT EXISTS 'COMPLETED'")
    op.execute("ALTER TYPE expense_status ADD VALUE IF NOT EXISTS 'REPLACED_VOID'")

    conn = op.get_bind()

    # 2. 關聯鏈：parent_id（self-referential FK）
    conn.execute(sa.text(
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS parent_id UUID"
        " REFERENCES expenses(id) ON DELETE SET NULL"
    ))

    # 3. 關聯類型：VOID_REPLACE | CREDIT_NOTE | SUPPLEMENT
    conn.execute(sa.text(
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS relation_type VARCHAR(32)"
    ))

    # 4. 軟刪除：is_active=False 的記錄不計入 Dashboard 金額加總
    conn.execute(sa.text(
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"
    ))

    # 5. 作廢原因（人類可讀說明，如「換貨換單」）
    conn.execute(sa.text(
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS void_reason TEXT"
    ))

    # 6. 參考發票號碼（從 OCR 或說明文字提取）
    conn.execute(sa.text(
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS referenced_invoice_number VARCHAR(64)"
    ))

    # 7. Bundle group ID：同批次的所有報帳共用，供 Dashboard 整捆操作
    conn.execute(sa.text(
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS group_id UUID"
    ))

    # 8. 索引
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_expenses_parent_id ON expenses (parent_id)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_expenses_is_active ON expenses (is_active)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_expenses_group_id ON expenses (group_id)"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_expenses_group_id"))
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_expenses_is_active"))
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_expenses_parent_id"))
    conn.execute(sa.text("ALTER TABLE expenses DROP COLUMN IF EXISTS group_id"))
    conn.execute(sa.text("ALTER TABLE expenses DROP COLUMN IF EXISTS referenced_invoice_number"))
    conn.execute(sa.text("ALTER TABLE expenses DROP COLUMN IF EXISTS void_reason"))
    conn.execute(sa.text("ALTER TABLE expenses DROP COLUMN IF EXISTS is_active"))
    conn.execute(sa.text("ALTER TABLE expenses DROP COLUMN IF EXISTS relation_type"))
    conn.execute(sa.text("ALTER TABLE expenses DROP COLUMN IF EXISTS parent_id"))
    # PostgreSQL 不支援 DROP VALUE from enum，降版後 enum 值仍存在（可忽略）
