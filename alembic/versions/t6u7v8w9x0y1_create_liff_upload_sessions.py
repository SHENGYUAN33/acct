"""建立 LIFF 批次上傳 Session 表

Revision ID: t6u7v8w9x0y1
Revises: s5t6u7v8w9x0
Create Date: 2026-05-18

新增兩張表：
  liff_upload_sessions — 一次 LIFF 上傳流程的容器（TTL 30 分鐘）
  liff_session_images  — 單張圖片及其 sequence_order、is_voucher 狀態
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 't6u7v8w9x0y1'
down_revision = 's5t6u7v8w9x0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # liff_upload_sessions
    # -----------------------------------------------------------------------
    op.create_table(
        'liff_upload_sessions',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column('line_user_id', sa.String(64), nullable=False),
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'status',
            sa.String(16),
            nullable=False,
            server_default='uploading',
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        'ix_liff_upload_sessions_line_user_id',
        'liff_upload_sessions',
        ['line_user_id'],
    )

    # -----------------------------------------------------------------------
    # liff_session_images
    # -----------------------------------------------------------------------
    op.create_table(
        'liff_session_images',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            'session_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('liff_upload_sessions.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('sequence_order', sa.Integer(), nullable=False),
        sa.Column('image_path', sa.String(512), nullable=False),
        sa.Column('is_voucher', sa.Boolean(), nullable=True),
        sa.Column(
            'manually_set',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        'ix_liff_session_images_session_id',
        'liff_session_images',
        ['session_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_liff_session_images_session_id', table_name='liff_session_images')
    op.drop_table('liff_session_images')
    op.drop_index('ix_liff_upload_sessions_line_user_id', table_name='liff_upload_sessions')
    op.drop_table('liff_upload_sessions')
