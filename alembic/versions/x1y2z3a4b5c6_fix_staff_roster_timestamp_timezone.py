"""fix staff_roster bound_at and created_at to TIMESTAMPTZ

Revision ID: x1y2z3a4b5c6
Revises: w9x0y1z2a3b4
Create Date: 2026-06-02 00:00:00.000000

將 staff_roster 的 bound_at / created_at 從無時區 TIMESTAMP 改為 TIMESTAMPTZ。
USING 子句明確指定既有資料以 UTC 解讀，確保升級前後時間值語意一致。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "x1y2z3a4b5c6"
down_revision: Union[str, None] = "w9x0y1z2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE staff_roster "
        "ALTER COLUMN bound_at TYPE TIMESTAMPTZ "
        "USING bound_at AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE staff_roster "
        "ALTER COLUMN created_at TYPE TIMESTAMPTZ "
        "USING created_at AT TIME ZONE 'UTC'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE staff_roster "
        "ALTER COLUMN bound_at TYPE TIMESTAMP WITHOUT TIME ZONE "
        "USING bound_at AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE staff_roster "
        "ALTER COLUMN created_at TYPE TIMESTAMP WITHOUT TIME ZONE "
        "USING created_at AT TIME ZONE 'UTC'"
    )
