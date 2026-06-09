"""delete_legacy_completed_supplemented_records

Revision ID: 27c47f415d3f
Revises: p1q2r3s4t5u6
Create Date: 2026-06-10

刪除舊版流程遺留的 COMPLETED / SUPPLEMENTED 狀態資料。
這兩個 status 在現行程式中已不再被設定，僅有歷史測試資料殘留。
PostgreSQL enum type 無法直接移除值，保留 DB 層定義但程式層不再使用。
"""
from typing import Sequence, Union

from alembic import op

revision: str = '27c47f415d3f'
down_revision: Union[str, None] = 'p1q2r3s4t5u6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM expenses WHERE status IN ('COMPLETED', 'SUPPLEMENTED')"
    )


def downgrade() -> None:
    # 資料已刪除，無法還原
    pass
