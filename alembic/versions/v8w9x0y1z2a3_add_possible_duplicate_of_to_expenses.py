"""新增 expenses.possible_duplicate_of 欄位（重複憑證偵測）

Revision ID: v8w9x0y1z2a3
Revises: u7v8w9x0y1z2
Create Date: 2026-05-22

當同一使用者上傳相同 invoice_number 的憑證時，
系統自動將新建的 Expense.possible_duplicate_of 指向最早那筆，
供 Dashboard 顯示警示並由管理員裁決。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'v8w9x0y1z2a3'
down_revision = 'u7v8w9x0y1z2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'expenses',
        sa.Column(
            'possible_duplicate_of',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('expenses.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('expenses', 'possible_duplicate_of')
