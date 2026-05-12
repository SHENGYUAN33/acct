"""add pending_images and pending_description to user_states

Revision ID: l9e0f1a2b3c4
Revises: k8d9e0f1a2b3
Create Date: 2026-04-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "l9e0f1a2b3c4"
down_revision: Union[str, None] = "k8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # ADD COLUMN IF NOT EXISTS 防止重複新增（startup create_all 不會加欄位，但保持冪等）
    conn.execute(sa.text(
        "ALTER TABLE user_states ADD COLUMN IF NOT EXISTS pending_images TEXT NOT NULL DEFAULT '[]'"
    ))
    conn.execute(sa.text(
        "ALTER TABLE user_states ADD COLUMN IF NOT EXISTS pending_description TEXT NOT NULL DEFAULT ''"
    ))


def downgrade() -> None:
    op.drop_column("user_states", "pending_description")
    op.drop_column("user_states", "pending_images")
