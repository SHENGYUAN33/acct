"""add_dismissed_from_waiting_return_to_expenses

Revision ID: b0c1d2e3f4a5
Revises: 27c47f415d3f
Create Date: 2026-06-10

新增 dismissed_from_waiting_return 布林欄位：
使用者從待退貨管理移出孤立補件時設為 True，保留資料與 relation_type badge，
僅從孤立補件清單隱藏。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b0c1d2e3f4a5'
down_revision: Union[str, None] = '27c47f415d3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'expenses',
        sa.Column(
            'dismissed_from_waiting_return',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )


def downgrade() -> None:
    op.drop_column('expenses', 'dismissed_from_waiting_return')
