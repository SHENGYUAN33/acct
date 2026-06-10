"""add job_title to staff_roster

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-06-10

新增 job_title（職稱）欄位至 staff_roster 表。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b0c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("staff_roster", sa.Column("job_title", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("staff_roster", "job_title")
