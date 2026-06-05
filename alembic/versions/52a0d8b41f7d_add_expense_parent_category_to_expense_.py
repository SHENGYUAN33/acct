"""add_expense_parent_category_to_expense_images

Revision ID: 52a0d8b41f7d
Revises: z3a4b5c6d7e8
Create Date: 2026-06-05 17:44:13.507105

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '52a0d8b41f7d'
down_revision: Union[str, None] = 'z3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('expense_images', sa.Column('expense_parent_category', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('expense_images', 'expense_parent_category')
