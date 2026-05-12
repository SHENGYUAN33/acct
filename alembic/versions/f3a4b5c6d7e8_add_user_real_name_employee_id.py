"""add real_name and employee_id to users

Revision ID: f3a4b5c6d7e8
Revises: e1f2a3b4c5d6
Create Date: 2026-04-07 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("real_name", sa.String(128), nullable=True))
    op.add_column("users", sa.Column("employee_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "employee_id")
    op.drop_column("users", "real_name")
