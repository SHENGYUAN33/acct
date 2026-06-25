"""add voided_at to expenses

Revision ID: a1b2c3d4e5f6
Revises: z3a4b5c6d7e8
Create Date: 2026-06-22 00:00:00.000000

新增 voided_at 欄位，記錄沖銷/退貨確認動作發生的時間點。
用途：CSV 匯出時，沖銷類記錄（REPLACED_VOID / VOID_ORIGINAL / WAITING_RETURN 已配對）
     改用 voided_at 做日期篩選，避免跨期記帳時原始期間報表被污染。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, tuple, None] = ("z3a4b5c6d7e8", "c1d2e3f4a5b6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "expenses",
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
    )
    # 歷史資料回填：REPLACED_VOID 與 VOID_ORIGINAL 以 updated_at 作為 voided_at
    op.execute("""
        UPDATE expenses
        SET voided_at = updated_at
        WHERE (status::text = 'REPLACED_VOID' OR relation_type = 'VOID_ORIGINAL')
          AND voided_at IS NULL
    """)


def downgrade() -> None:
    op.drop_column("expenses", "voided_at")
