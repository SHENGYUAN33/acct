"""add voucher_subtype, expense_category, ocr_confidence to expense_images;
   add voucher_subtypes, expense_categories to expenses

Revision ID: o2p3q4r5s6t7
Revises: n1g2h3i4j5k6
Create Date: 2026-04-15 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o2p3q4r5s6t7"
down_revision: Union[str, None] = "n1g2h3i4j5k6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # expense_images：新增子類型、費用科目、信心分數
    conn.execute(sa.text(
        "ALTER TABLE expense_images ADD COLUMN IF NOT EXISTS voucher_subtype VARCHAR(64)"
    ))
    conn.execute(sa.text(
        "ALTER TABLE expense_images ADD COLUMN IF NOT EXISTS expense_category VARCHAR(64)"
    ))
    conn.execute(sa.text(
        "ALTER TABLE expense_images ADD COLUMN IF NOT EXISTS ocr_confidence NUMERIC(4,3)"
    ))
    # expenses：新增彙總子類型與費用科目 JSON array
    conn.execute(sa.text(
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS voucher_subtypes TEXT"
    ))
    conn.execute(sa.text(
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS expense_categories TEXT"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        "ALTER TABLE expense_images DROP COLUMN IF EXISTS voucher_subtype"
    ))
    conn.execute(sa.text(
        "ALTER TABLE expense_images DROP COLUMN IF EXISTS expense_category"
    ))
    conn.execute(sa.text(
        "ALTER TABLE expense_images DROP COLUMN IF EXISTS ocr_confidence"
    ))
    conn.execute(sa.text(
        "ALTER TABLE expenses DROP COLUMN IF EXISTS voucher_subtypes"
    ))
    conn.execute(sa.text(
        "ALTER TABLE expenses DROP COLUMN IF EXISTS expense_categories"
    ))
