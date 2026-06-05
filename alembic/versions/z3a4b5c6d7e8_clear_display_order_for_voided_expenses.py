"""clear display_order for REPLACED_VOID expenses

Revision ID: z3a4b5c6d7e8
Revises: y2z3a4b5c6d7
Create Date: 2026-06-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "z3a4b5c6d7e8"
down_revision: Union[str, None] = "y2z3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE expenses
        SET display_order = NULL
        WHERE status = 'REPLACED_VOID'
          AND display_order IS NOT NULL
    """)


def downgrade() -> None:
    pass
