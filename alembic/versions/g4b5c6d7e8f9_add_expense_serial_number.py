"""add serial_number to expenses with PostgreSQL sequence

Revision ID: g4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-04-07 14:00:00.000000

單號格式：EXP-YYYYMM-NNNN（例：EXP-202604-0001）
生成機制：依賴 PostgreSQL sequence「expense_serial_seq」，高併發下不會重複。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g4b5c6d7e8f9"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 建立 PostgreSQL sequence（從 1 開始）
    op.execute("CREATE SEQUENCE IF NOT EXISTS expense_serial_seq START 1")

    # 2. 新增 nullable 欄位（先 nullable 才能 backfill 舊資料）
    op.add_column(
        "expenses",
        sa.Column("serial_number", sa.String(32), nullable=True),
    )

    # 3. 回填現有資料：依 created_at 順序分配單號
    #    格式：EXP-{YYYYMM 取自 created_at}-{流水號 4 位}
    op.execute(
        """
        UPDATE expenses
        SET serial_number =
            'EXP-' ||
            TO_CHAR(created_at AT TIME ZONE 'UTC', 'YYYYMM') ||
            '-' ||
            LPAD(nextval('expense_serial_seq')::text, 4, '0')
        WHERE serial_number IS NULL
        """
    )

    # 4. 設定 NOT NULL（回填後才能設）
    op.alter_column("expenses", "serial_number", nullable=False)

    # 5. 加上 UNIQUE constraint 與 index
    op.create_unique_constraint("uq_expenses_serial_number", "expenses", ["serial_number"])
    op.create_index("ix_expenses_serial_number", "expenses", ["serial_number"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_expenses_serial_number", table_name="expenses")
    op.drop_constraint("uq_expenses_serial_number", "expenses", type_="unique")
    op.drop_column("expenses", "serial_number")
    op.execute("DROP SEQUENCE IF EXISTS expense_serial_seq")
