"""migrate user_states step WAITING_PHOTO to COLLECTING

Revision ID: m0f1a2b3c4d5
Revises: l9e0f1a2b3c4
Create Date: 2026-04-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "m0f1a2b3c4d5"
down_revision: Union[str, None] = "l9e0f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE user_states SET step='COLLECTING' WHERE step='WAITING_PHOTO'")


def downgrade() -> None:
    op.execute("UPDATE user_states SET step='WAITING_PHOTO' WHERE step='COLLECTING'")
