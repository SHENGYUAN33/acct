"""create admin_users table with employee_id and display_name

Revision ID: i6d7e8f9a0b1
Revises: h5c6d7e8f9a0
Create Date: 2026-04-10 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "i6d7e8f9a0b1"
down_revision: Union[str, None] = "h5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("hashed_password", sa.String(256), nullable=False),
        sa.Column("employee_id", sa.String(64), nullable=True),
        sa.Column("display_name", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint("uq_admin_users_username", "admin_users", ["username"])
    op.create_index("ix_admin_users_username", "admin_users", ["username"])
    op.create_unique_constraint("uq_admin_users_employee_id", "admin_users", ["employee_id"])
    op.create_index("ix_admin_users_employee_id", "admin_users", ["employee_id"])


def downgrade() -> None:
    op.drop_index("ix_admin_users_employee_id", table_name="admin_users")
    op.drop_constraint("uq_admin_users_employee_id", "admin_users", type_="unique")
    op.drop_index("ix_admin_users_username", table_name="admin_users")
    op.drop_constraint("uq_admin_users_username", "admin_users", type_="unique")
    op.drop_table("admin_users")
