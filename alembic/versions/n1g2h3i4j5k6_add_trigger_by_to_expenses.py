"""add trigger_by column to expenses

Revision ID: n1g2h3i4j5k6
Revises: m0f1a2b3c4d5
Create Date: 2026-04-13 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "n1g2h3i4j5k6"
down_revision: Union[str, None] = "m0f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS trigger_by VARCHAR(32)"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "ALTER TABLE expenses DROP COLUMN IF EXISTS trigger_by"
        )
    )
