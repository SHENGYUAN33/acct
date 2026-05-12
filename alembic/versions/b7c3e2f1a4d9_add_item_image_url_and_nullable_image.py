"""add item_image_url and make image_url nullable

Revision ID: b7c3e2f1a4d9
Revises: a3f2c1d0e5b8
Create Date: 2026-03-27 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c3e2f1a4d9"
down_revision: Union[str, None] = "a3f2c1d0e5b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # image_url 改為可為 null（手動新增費用無初始圖片）
    op.alter_column("expenses", "image_url", existing_type=sa.String(512), nullable=True)
    # 新增物品影像欄位
    op.add_column("expenses", sa.Column("item_image_url", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("expenses", "item_image_url")
    op.alter_column("expenses", "image_url", existing_type=sa.String(512), nullable=False)
