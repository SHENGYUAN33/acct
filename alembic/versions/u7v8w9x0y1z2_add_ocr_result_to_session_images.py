"""新增 liff_session_images.ocr_result 欄位

Revision ID: u7v8w9x0y1z2
Revises: t6u7v8w9x0y1
Create Date: 2026-05-21

將 OCR 完整 JSON 結果儲存於 SessionImage，
以供 submit_session() 還原完整的 VoucherOCRResult，
避免 Expense 欄位因空殼 stub 而全部為 null。
"""

from alembic import op
import sqlalchemy as sa

revision = 'u7v8w9x0y1z2'
down_revision = 't6u7v8w9x0y1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'liff_session_images',
        sa.Column('ocr_result', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('liff_session_images', 'ocr_result')
