"""add return_record to expenses

Revision ID: d4e5f6a7b8c9_rr
Revises: c3d4e5f6a7b8
Create Date: 2026-06-24 00:00:00.000000

新增 return_record 欄位：
  - 換新發票（VOID_REPLACE）/ 折讓單（CREDIT_NOTE）：儲存原發票號碼
  - 換貨收據（RETURN_SUPPLEMENT）/ 改金額（AMOUNT_CORRECTION）：儲存「日期 / 金額」
  - 對沖筆與一般記錄：null
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9_rr"
depends_on: Union[str, Sequence[str], None] = None
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "expenses",
        sa.Column("return_record", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("expenses", "return_record")
