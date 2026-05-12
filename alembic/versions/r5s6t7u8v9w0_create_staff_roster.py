"""create staff_roster table

Revision ID: r5s6t7u8v9w0
Revises: q4r5s6t7u8v9
Create Date: 2026-04-29 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "r5s6t7u8v9w0"
down_revision: Union[str, None] = "q4r5s6t7u8v9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "staff_roster",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("department", sa.String(100), nullable=False),
        sa.Column("employee_id", sa.String(50), nullable=True),
        sa.Column("line_user_id", sa.String(100), nullable=True),
        sa.Column("is_bound", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("bound_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # unique index：employee_id
    op.create_index(
        "uq_staff_roster_employee_id",
        "staff_roster",
        ["employee_id"],
        unique=True,
    )
    # unique index：line_user_id
    op.create_index(
        "uq_staff_roster_line_user_id",
        "staff_roster",
        ["line_user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_staff_roster_line_user_id", table_name="staff_roster")
    op.drop_index("uq_staff_roster_employee_id", table_name="staff_roster")
    op.drop_table("staff_roster")
