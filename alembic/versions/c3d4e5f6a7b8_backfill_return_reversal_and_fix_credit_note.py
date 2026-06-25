"""backfill return_reversal records and fix credit_note positive amounts

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-22 00:00:02.000000

兩個修正：
1. 補產生 RETURN_REVERSAL：
   找出所有 WAITING_RETURN + voided_at IS NOT NULL 且尚無 RETURN_REVERSAL 子記錄的費用，
   自動補建沖銷分錄（負數、upload_date = voided_at）。

2. 修正現有 CREDIT_NOTE 正數金額：
   OCR 可能回傳正數折讓金額，強制轉為負數，確保 CSV 匯出加總正確。

downgrade：
  - 刪除所有 RETURN_REVERSAL 記錄
  - 將 CREDIT_NOTE 的負數金額還原為正數（無法區分原始正負，保守還原）
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, tuple, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. 補建 RETURN_REVERSAL ──────────────────────────────────────
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
        WHERE e.status = 'WAITING_RETURN'
          AND e.voided_at IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM expenses r
              WHERE r.parent_id = e.id
                AND r.relation_type = 'RETURN_REVERSAL'
          )
    """)).fetchall()

    for row in rows:
        reversal_date = row.reversal_date
        prefix = reversal_date.strftime('%Y%m') if reversal_date else '202606'

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
                :serial_number, 'PENDING', 'RETURN_REVERSAL', :parent_id,
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
            "total_amount": -row.total_amount if row.total_amount is not None else None,
            "net_amount": -row.net_amount if row.net_amount is not None else None,
            "tax_amount": -row.tax_amount if row.tax_amount is not None else None,
            "seller_tax_id": row.seller_tax_id,
            "seller_name": row.seller_name,
            "item_description": row.item_description,
            "voucher_categories": row.voucher_categories,
            "voucher_subtypes": row.voucher_subtypes,
            "expense_categories": row.expense_categories,
            "serial_number": serial,
            "parent_id": row.id,
        })

    # ── 2. 修正現有 CREDIT_NOTE 正數金額（OCR 回傳正數的歷史資料）──
    conn.execute(sa.text("""
        UPDATE expenses
        SET
            total_amount = -total_amount,
            net_amount   = CASE WHEN net_amount  > 0 THEN -net_amount  ELSE net_amount  END,
            tax_amount   = CASE WHEN tax_amount  > 0 THEN -tax_amount  ELSE tax_amount  END,
            updated_at   = NOW()
        WHERE relation_type = 'CREDIT_NOTE'
          AND total_amount  > 0
    """))


def downgrade() -> None:
    conn = op.get_bind()
    # 移除補建的 RETURN_REVERSAL
    conn.execute(sa.text("DELETE FROM expenses WHERE relation_type = 'RETURN_REVERSAL'"))
    # 將 CREDIT_NOTE 負數金額還原為正數
    conn.execute(sa.text("""
        UPDATE expenses
        SET
            total_amount = -total_amount,
            net_amount   = CASE WHEN net_amount  < 0 THEN -net_amount  ELSE net_amount  END,
            tax_amount   = CASE WHEN tax_amount  < 0 THEN -tax_amount  ELSE tax_amount  END
        WHERE relation_type = 'CREDIT_NOTE'
          AND total_amount  < 0
    """))
