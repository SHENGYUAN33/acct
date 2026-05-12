"""add user_states table

Revision ID: a3f2c1d0e5b8
Revises: 8bd1dbb125a7
Create Date: 2026-03-24 17:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3f2c1d0e5b8"
down_revision: Union[str, None] = "8bd1dbb125a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_states",
        sa.Column("line_user_id", sa.String(64), primary_key=True),
        sa.Column("step", sa.String(32), nullable=False),
        sa.Column("dept", sa.String(64), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("user_states")
