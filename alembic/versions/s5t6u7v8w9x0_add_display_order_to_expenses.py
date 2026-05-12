"""add display_order to expenses

Revision ID: s5t6u7v8w9x0
Revises: r5s6t7u8v9w0
Create Date: 2026-05-04 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 's5t6u7v8w9x0'
down_revision: Union[str, None] = 'r5s6t7u8v9w0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'expenses',
        sa.Column('display_order', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('expenses', 'display_order')
