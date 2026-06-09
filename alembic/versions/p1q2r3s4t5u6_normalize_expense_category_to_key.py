"""normalize_expense_category_to_key

將 expense_images.expense_category 與 expenses.expense_categories
從中文 label（如「勞-交通費-計程車資」）改為穩定的英文 key（如「TRANS_TAXI」）。

Revision ID: p1q2r3s4t5u6
Revises: 52a0d8b41f7d
Create Date: 2026-06-09
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.expense_categories import normalize_to_key  # noqa: E402

revision: str = "p1q2r3s4t5u6"
down_revision: Union[str, None] = "52a0d8b41f7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. 修正 expense_images.expense_category ────────────────────────
    rows = conn.execute(
        sa.text("SELECT id, expense_category FROM expense_images WHERE expense_category IS NOT NULL")
    ).fetchall()

    for row in rows:
        img_id, old_val = row
        new_val = normalize_to_key(old_val)
        if new_val != old_val:
            conn.execute(
                sa.text("UPDATE expense_images SET expense_category = :v WHERE id = :id"),
                {"v": new_val, "id": str(img_id)},
            )

    # ── 2. 重建 expenses.expense_categories（從子圖彙總 key）──────────
    expenses = conn.execute(sa.text("SELECT id FROM expenses")).fetchall()

    for (exp_id,) in expenses:
        images = conn.execute(
            sa.text(
                "SELECT expense_category FROM expense_images "
                "WHERE expense_id = :eid AND expense_category IS NOT NULL"
            ),
            {"eid": str(exp_id)},
        ).fetchall()

        seen: list[str] = []
        for (cat,) in images:
            key = normalize_to_key(cat)
            if key and key not in seen:
                seen.append(key)

        new_json = json.dumps(seen, ensure_ascii=False) if seen else None
        conn.execute(
            sa.text("UPDATE expenses SET expense_categories = :v WHERE id = :id"),
            {"v": new_json, "id": str(exp_id)},
        )


def downgrade() -> None:
    raise NotImplementedError("此 migration 不支援 downgrade（key→label 逆向映射無法保證唯一）")
