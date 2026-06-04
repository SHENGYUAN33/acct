"""extend staff_roster: add line_id/account_role/line_name/email/petty_cash/bank_account, drop employee_id

Revision ID: y2z3a4b5c6d7
Revises: x1y2z3a4b5c6
Create Date: 2026-06-04 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "y2z3a4b5c6d7"
down_revision: Union[str, None] = "x1y2z3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("staff_roster", sa.Column("line_id", sa.String(100), nullable=True))
    op.add_column("staff_roster", sa.Column("account_role", sa.String(50), nullable=True))
    op.add_column("staff_roster", sa.Column("line_name", sa.String(128), nullable=True))
    op.add_column("staff_roster", sa.Column("email", sa.String(255), nullable=True))
    op.add_column(
        "staff_roster",
        sa.Column("is_petty_cash_target", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("staff_roster", sa.Column("bank_account", sa.String(100), nullable=True))

    op.drop_index("uq_staff_roster_employee_id", table_name="staff_roster")
    op.drop_column("staff_roster", "employee_id")


def downgrade() -> None:
    op.add_column("staff_roster", sa.Column("employee_id", sa.String(50), nullable=True))
    op.create_index(
        "uq_staff_roster_employee_id",
        "staff_roster",
        ["employee_id"],
        unique=True,
    )

    op.drop_column("staff_roster", "bank_account")
    op.drop_column("staff_roster", "is_petty_cash_target")
    op.drop_column("staff_roster", "email")
    op.drop_column("staff_roster", "line_name")
    op.drop_column("staff_roster", "account_role")
    op.drop_column("staff_roster", "line_id")
