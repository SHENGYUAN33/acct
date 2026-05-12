"""create expense_serial_seq sequence (start 1001)

Revision ID: h5c6d7e8f9a0
Revises: g4b5c6d7e8f9
Create Date: 2026-04-07 15:00:00.000000

獨立補丁：確保 expense_serial_seq 存在，讓單號從 1001 開始。
使用 IF NOT EXISTS / IF EXISTS 確保冪等，重複執行不會失敗。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "h5c6d7e8f9a0"
down_revision: Union[str, None] = "g4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS expense_serial_seq START 1001")


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS expense_serial_seq")
