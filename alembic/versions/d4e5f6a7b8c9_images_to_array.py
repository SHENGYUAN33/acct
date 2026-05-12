"""images_to_array: convert image_url and item_image_url from VARCHAR to VARCHAR[]

Revision ID: d4e5f6a7b8c9
Revises: b7c3e2f1a4d9
Create Date: 2026-03-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "b7c3e2f1a4d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # image_url: VARCHAR(512) → VARCHAR[]
    # NULL → 空陣列；有值 → 單元素陣列
    op.execute("""
        ALTER TABLE expenses
        ALTER COLUMN image_url TYPE VARCHAR[]
        USING CASE WHEN image_url IS NULL THEN ARRAY[]::VARCHAR[]
                   ELSE ARRAY[image_url] END
    """)
    # 移除 NOT NULL 限制（ARRAY 欄位以空陣列為預設，不應強制非 NULL）
    op.execute("ALTER TABLE expenses ALTER COLUMN image_url SET DEFAULT '{}'")

    # item_image_url: VARCHAR(512) → VARCHAR[]
    op.execute("""
        ALTER TABLE expenses
        ALTER COLUMN item_image_url TYPE VARCHAR[]
        USING CASE WHEN item_image_url IS NULL THEN ARRAY[]::VARCHAR[]
                   ELSE ARRAY[item_image_url] END
    """)
    op.execute("ALTER TABLE expenses ALTER COLUMN item_image_url SET DEFAULT '{}'")

    # 將既有 NULL 值統一補為空陣列
    op.execute("UPDATE expenses SET image_url = '{}' WHERE image_url IS NULL")
    op.execute("UPDATE expenses SET item_image_url = '{}' WHERE item_image_url IS NULL")

    # 設定 NOT NULL（已確保無 NULL 值）
    op.execute("ALTER TABLE expenses ALTER COLUMN image_url SET NOT NULL")
    op.execute("ALTER TABLE expenses ALTER COLUMN item_image_url SET NOT NULL")


def downgrade() -> None:
    # VARCHAR[] → VARCHAR(512)，取陣列第一個元素；空陣列轉為 NULL
    op.execute("ALTER TABLE expenses ALTER COLUMN image_url DROP NOT NULL")
    op.execute("ALTER TABLE expenses ALTER COLUMN item_image_url DROP NOT NULL")
    op.execute("ALTER TABLE expenses ALTER COLUMN image_url DROP DEFAULT")
    op.execute("ALTER TABLE expenses ALTER COLUMN item_image_url DROP DEFAULT")

    op.execute("""
        ALTER TABLE expenses
        ALTER COLUMN image_url TYPE VARCHAR(512)
        USING CASE WHEN image_url = '{}' THEN NULL ELSE image_url[1] END
    """)
    op.execute("""
        ALTER TABLE expenses
        ALTER COLUMN item_image_url TYPE VARCHAR(512)
        USING CASE WHEN item_image_url = '{}' THEN NULL ELSE item_image_url[1] END
    """)
