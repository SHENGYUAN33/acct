"""backfill void_reversal records for existing void_original expenses

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-22 00:00:01.000000

為所有現有的 VOID_ORIGINAL 記錄（換新發票的舊發票）自動補產生 VOID_REVERSAL 沖銷分錄。
原因：原設計以 voided_at COALESCE 改變日期落點；新設計改為明確建立沖銷分錄記錄，
      金額為負數、upload_date = voided_at（舊單被換掉的時間），parent_id 指向原始記錄。

downgrade：刪除所有 relation_type = 'VOID_REVERSAL' 的記錄。
"""
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, tuple, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 取得所有 VOID_ORIGINAL 且尚無 VOID_REVERSAL 子記錄的費用
    rows = conn.execute(sa.text("""
        SELECT
            e.id,
            e.user_id,
            e.uploader_name,
            e.uploader_dept,
            e.expense_date,
            e.invoice_number,
            e.total_amount,
            e.net_amount,
            e.tax_amount,
            e.seller_tax_id,
            e.seller_name,
            e.item_description,
            e.voucher_categories,
            e.voucher_subtypes,
            e.expense_categories,
            COALESCE(e.voided_at, e.updated_at, e.upload_date) AS reversal_date
        FROM expenses e
        WHERE e.relation_type = 'VOID_ORIGINAL'
          AND NOT EXISTS (
              SELECT 1 FROM expenses r
              WHERE r.parent_id = e.id
                AND r.relation_type = 'VOID_REVERSAL'
          )
    """)).fetchall()

    for row in rows:
        reversal_date = row.reversal_date
        if isinstance(reversal_date, datetime) and reversal_date.tzinfo is None:
            reversal_date = reversal_date.replace(tzinfo=timezone.utc)

        # 產生唯一 serial_number（以 reversal_date 所在月份）
        prefix = reversal_date.strftime('%Y%m') if reversal_date else datetime.now().strftime('%Y%m')

        # 取當月最大序號後加 1（可能有 race condition，但遷移為單一 worker 執行，風險極低）
        max_serial = conn.execute(sa.text(
            f"SELECT MAX(serial_number) FROM expenses WHERE serial_number LIKE 'EXP-{prefix}-%'"
        )).scalar()

        if max_serial:
            try:
                last_seq = int(max_serial.rsplit('-', 1)[-1])
            except (ValueError, IndexError):
                last_seq = 0
        else:
            last_seq = 0

        serial = f"EXP-{prefix}-{last_seq + 1:04d}"

        def neg(val):
            return -val if val is not None else None

        conn.execute(sa.text("""
            INSERT INTO expenses (
                id, user_id, uploader_name, uploader_dept,
                upload_date, expense_date, invoice_number,
                total_amount, net_amount, tax_amount,
                seller_tax_id, seller_name, item_description,
                voucher_categories, voucher_subtypes, expense_categories,
                serial_number, status, relation_type, parent_id,
                referenced_invoice_number, is_active,
                image_url, item_image_url, image_count,
                created_at, updated_at
            ) VALUES (
                gen_random_uuid(), :user_id, :uploader_name, :uploader_dept,
                :upload_date, :expense_date, :invoice_number,
                :total_amount, :net_amount, :tax_amount,
                :seller_tax_id, :seller_name, :item_description,
                :voucher_categories, :voucher_subtypes, :expense_categories,
                :serial_number, 'PENDING', 'VOID_REVERSAL', :parent_id,
                :invoice_number, true,
                '{}', '{}', 0,
                NOW(), NOW()
            )
        """), {
            "user_id": row.user_id,
            "uploader_name": row.uploader_name,
            "uploader_dept": row.uploader_dept,
            "upload_date": reversal_date,
            "expense_date": row.expense_date,
            "invoice_number": row.invoice_number,
            "total_amount": neg(row.total_amount),
            "net_amount": neg(row.net_amount),
            "tax_amount": neg(row.tax_amount),
            "seller_tax_id": row.seller_tax_id,
            "seller_name": row.seller_name,
            "item_description": row.item_description,
            "voucher_categories": row.voucher_categories,
            "voucher_subtypes": row.voucher_subtypes,
            "expense_categories": row.expense_categories,
            "serial_number": serial,
            "parent_id": row.id,
        })


def downgrade() -> None:
    # 移除所有系統自動產生的 VOID_REVERSAL 沖銷分錄
    op.execute("DELETE FROM expenses WHERE relation_type = 'VOID_REVERSAL'")
