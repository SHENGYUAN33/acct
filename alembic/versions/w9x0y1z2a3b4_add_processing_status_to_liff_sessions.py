"""新增 liff_upload_sessions.processing_status 欄位（背景任務狀態追蹤）

Revision ID: w9x0y1z2a3b4
Revises: v8w9x0y1z2a3
Create Date: 2026-05-25

OCR 與 Expense 建立改為背景任務執行後，需追蹤各 session 的處理狀態：
  pending    — session 已送出，背景任務尚未開始
  processing — 背景任務執行中
  done       — 建帳完成
  failed     — 建帳失敗（OCR 全失敗或其他例外）
"""

from alembic import op
import sqlalchemy as sa

revision = 'w9x0y1z2a3b4'
down_revision = 'v8w9x0y1z2a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'liff_upload_sessions',
        sa.Column(
            'processing_status',
            sa.String(16),
            nullable=False,
            server_default='pending',
        ),
    )


def downgrade() -> None:
    op.drop_column('liff_upload_sessions', 'processing_status')
