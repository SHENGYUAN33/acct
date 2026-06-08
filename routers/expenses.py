"""Expenses Router — Dashboard API for listing and reviewing expense records."""

import csv
import io
import json
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.config import settings
from core.database import get_db
from routers.auth import get_current_user
from models.expense import Expense, ExpenseStatus
from models.user import User
from schemas.expense import ExpenseCreate, ExpenseListResponse, ExpenseRead, ExpenseUpdate, ExpenseWithImages
from schemas.expense_image import ExpenseImageRead, ExpenseImageUpdate, MoveImageRequest
from schemas.ocr import VoucherOCRResult
from services import expense_service, line_service
from services.ocr_service import classify_and_extract_with_retry
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1",
    tags=["expenses"],
    dependencies=[Depends(get_current_user)],
)

UPLOADS_DIR = Path("uploads")
UPLOADS_DIR.mkdir(exist_ok=True)

# CSV 匯出欄位定義
CSV_HEADERS = [
    "案件編號", "ID", "上傳者", "上傳者組別", "費用提報者", "費用提報者組別",
    "上傳日期", "費用日期", "發票號碼", "憑證類別", "含稅金額", "未稅金額", "營業稅額",
    "賣方統編", "賣方公司", "項目說明", "憑證狀態", "退件原因",
    "建立時間", "更新時間",
]

# 憑證類別中文對照
VOUCHER_CATEGORY_ZH: dict[str, str] = {
    "INVOICE": "發票",
    "RECEIPT": "收據",
    "TRANSPORTATION": "交通票據",
    "ACCOMMODATION": "住宿",
    "LABOR_SERVICE": "勞務費",
    "UTILITY": "水電費",
    "RENTAL": "租金",
    "INSURANCE": "保險",
    "POSTAGE": "郵資",
    "CREDIT_NOTE": "折讓單",
    "OTHER": "其他",
}

# 憑證狀態中文對照
STATUS_ZH: dict[str, str] = {
    "PENDING": "待審核",
    "APPROVED": "已核准",
    "REJECTED": "已退件",
    "NEEDS_MANUAL_REVIEW": "需人工審核",
    "SUPPLEMENTED": "已補件",
    "WAITING_RETURN": "待退貨",
    "COMPLETED": "已結清",
    "REPLACED_VOID": "已作廢（沖銷）",
}

# 費用科目中文對照
EXPENSE_CATEGORY_ZH: dict[str, str] = {
    "MEAL": "餐費",
    "TRANSPORTATION": "交通費",
    "STATIONERY": "文具費",
    "ACCOMMODATION": "住宿費",
    "INSURANCE": "保險費",
    "UTILITY": "水電費",
    "RENTAL": "租金",
    "LABOR_SERVICE": "勞務費",
    "POSTAGE": "郵資",
    "ENTERTAINMENT": "交際費",
    "TRAINING": "訓練費",
    "MEDICAL": "醫療費",
    "OTHER": "其他",
}

# 進項稅額明細表欄位定義
TAX_REPORT_HEADERS = [
    "案件編號", "費用日期", "發票號碼", "憑證類型", "憑證子類型", "稅務類別",
    "賣方統編", "賣方名稱", "稅前金額", "營業稅額", "含稅金額",
    "費用科目", "上傳者", "上傳者組別", "項目說明", "使用者備註",
    "憑證狀態", "備注",
]


def _classify_tax_type(voucher_category: str | None, voucher_subtype: str | None) -> str:
    """依憑證類型與子類型對應台灣進項稅額申報書分類。"""
    cat = (voucher_category or "").upper()
    sub = (voucher_subtype or "").upper()

    if cat == "INVOICE":
        if sub == "EXEMPT_INVOICE":
            return "免稅"
        return "三聯式—一般稅額"
    if cat == "RECEIPT":
        return "二聯式/收據"
    if cat == "TRANSPORTATION":
        if sub == "FUEL":
            return "油資—依法可扣"
        return "交通票據"
    if cat == "ACCOMMODATION":
        return "住宿費"
    if cat == "LABOR_SERVICE":
        return "勞務費"
    if cat == "UTILITY":
        return "水電瓦斯費"
    if cat == "RENTAL":
        return "租金"
    if cat == "INSURANCE":
        return "保險費"
    return "其他費用"


# ── GET /expenses（列表）────────────────────────────────────────────
@router.get("/expenses", response_model=dict)
def list_expenses(
    status: ExpenseStatus | None = Query(default=None, description="Filter by status"),
    date_from: datetime | None = Query(default=None, description="Filter from date (ISO 8601)"),
    date_to: datetime | None = Query(default=None, description="Filter to date (ISO 8601)"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    include_inactive: bool = Query(default=False, description="是否包含已作廢（REPLACED_VOID）記錄"),
    q: str | None = Query(default=None, description="模糊搜尋：案件編號或上傳者姓名"),
    referenced_invoice_number: str | None = Query(default=None, description="篩選指定原始憑證號碼的補件"),
    has_duplicate: bool | None = Query(default=None, description="True 時只回傳疑似重複憑證的 Expense"),
    relation_type: str | None = Query(default=None, description="精確篩選補件類型，如 RETURN_SUPPLEMENT"),
    # ── 進階多條件篩選（新增，全部選填，AND 疊加）────────────────────────
    serial_number_q: str | None = Query(default=None, description="案件編號模糊搜尋"),
    invoice_number_q: str | None = Query(default=None, description="發票號碼模糊搜尋"),
    uploader_name_q: str | None = Query(default=None, description="上傳者姓名模糊搜尋"),
    uploader_dept_q: str | None = Query(default=None, description="上傳者組別模糊搜尋"),
    amount_min: float | None = Query(default=None, description="最低金額（含）"),
    amount_max: float | None = Query(default=None, description="最高金額（含）"),
    voucher_category_q: str | None = Query(default=None, description="憑證類別篩選（比對 voucher_categories JSON）"),
    db: Session = Depends(get_db),
) -> dict:
    total, items = expense_service.list_expenses(
        db, status=status, date_from=date_from, date_to=date_to,
        page=page, page_size=page_size, include_inactive=include_inactive, q=q,
        referenced_invoice_number=referenced_invoice_number,
        has_duplicate=has_duplicate,
        relation_type=relation_type,
        serial_number_q=serial_number_q,
        invoice_number_q=invoice_number_q,
        uploader_name_q=uploader_name_q,
        uploader_dept_q=uploader_dept_q,
        amount_min=amount_min,
        amount_max=amount_max,
        voucher_category_q=voucher_category_q,
    )
    return {
        "status": "success",
        "data": ExpenseListResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[ExpenseRead.model_validate(i) for i in items],
        ).model_dump(),
        "message": "ok",
    }


# ── GET /expenses/export（CSV 匯出）────────────────────────────────
# ⚠️ 必須在 /{expense_id} 之前定義，否則 "export" 會被解析為 UUID
@router.get("/expenses/export")
def export_expenses(
    status: ExpenseStatus | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """匯出符合篩選條件的費用清單為 CSV 檔案。"""
    # REPLACED_VOID（換單/換新發票舊記錄）也納入，以負數表示沖銷
    items = expense_service.get_expenses_for_export(
        db, status=status, date_from=date_from, date_to=date_to, include_inactive=True
    )

    buf = io.StringIO()
    # 加 BOM 讓 Excel 正確識別 UTF-8
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(CSV_HEADERS)
    for e in items:
        # REPLACED_VOID（換單/換新發票作廢舊單）與 CREDIT_NOTE（折讓扣減）均顯示負數
        is_void = (
            e.status == ExpenseStatus.REPLACED_VOID
            or e.relation_type == "CREDIT_NOTE"
        )
        sign = Decimal("-1") if is_void else Decimal("1")

        def _fmt_amount(val: Decimal | None, _sign: Decimal = sign) -> str:
            return str(val * _sign) if val is not None else ""

        # REPLACED_VOID 時退件原因欄改填 void_reason（沖銷原因）
        remark = (e.void_reason or e.reject_reason or "") if is_void else (e.reject_reason or "")

        writer.writerow([
            e.serial_number,
            str(e.id),
            e.uploader_name or "",
            e.uploader_dept or "",
            e.submitter_name or "",
            e.submitter_dept or "",
            e.upload_date.strftime("%Y-%m-%d %H:%M") if e.upload_date else "",
            str(e.expense_date) if e.expense_date else "",
            e.invoice_number or "",
            " / ".join(
                VOUCHER_CATEGORY_ZH.get(c, c)
                for c in json.loads(e.voucher_categories or "[]")
            ),
            _fmt_amount(e.total_amount),
            _fmt_amount(e.net_amount),
            _fmt_amount(e.tax_amount),
            e.seller_tax_id or "",
            e.seller_name or "",
            e.item_description or "",
            STATUS_ZH.get(e.status.value, e.status.value),
            remark,
            e.created_at.strftime("%Y-%m-%d %H:%M"),
            e.updated_at.strftime("%Y-%m-%d %H:%M"),
        ])

    # ── 費用科目加總 ──────────────────────────────────────────
    category_totals: dict[str, Decimal] = {}
    for e in items:
        if e.total_amount is None:
            continue
        is_void_sum = (
            e.status == ExpenseStatus.REPLACED_VOID
            or e.relation_type == "CREDIT_NOTE"
        )
        amt = e.total_amount * (Decimal("-1") if is_void_sum else Decimal("1"))
        cats: list[str] = json.loads(e.expense_categories or "[]")
        primary = cats[0] if cats else "OTHER"
        category_totals[primary] = category_totals.get(primary, Decimal("0")) + amt

    if category_totals:
        writer.writerow([])  # 空白分隔列
        writer.writerow(["── 費用科目加總 ──"] + [""] * (len(CSV_HEADERS) - 1))
        total_col = CSV_HEADERS.index("含稅金額")
        for cat, total in sorted(category_totals.items()):
            cat_zh = EXPENSE_CATEGORY_ZH.get(cat, cat)
            row = [""] * len(CSV_HEADERS)
            row[0] = cat_zh
            row[total_col] = str(total)
            writer.writerow(row)
        grand_total = sum(category_totals.values())
        grand_row = [""] * len(CSV_HEADERS)
        grand_row[0] = "合計"
        grand_row[total_col] = str(grand_total)
        writer.writerow(grand_row)

    csv_content = buf.getvalue()
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=expenses.csv"},
    )


# ── GET /expenses/export/tax-report（進項稅額明細表）────────────────────
# ⚠️ 必須在 /{expense_id} 之前定義
@router.get("/expenses/export/tax-report")
def export_tax_report(
    date_from: date = Query(..., description="費用日期起（YYYY-MM-DD，必填）"),
    date_to: date = Query(..., description="費用日期迄（YYYY-MM-DD，必填）"),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """進項稅額明細表：以 expense_date 為基準篩選，僅含 APPROVED / COMPLETED，供申報營業稅使用。"""
    from sqlalchemy import select as sa_select
    from models.expense import Expense as ExpenseModel, ExpenseStatus as ES

    stmt = (
        sa_select(ExpenseModel)
        .where(
            ExpenseModel.expense_date >= date_from,
            ExpenseModel.expense_date <= date_to,
            ExpenseModel.status.in_([
                ES.APPROVED,
                ES.COMPLETED,
                ES.REPLACED_VOID,
            ]),
        )
        .order_by(ExpenseModel.expense_date.asc(), ExpenseModel.serial_number.asc())
    )
    items: list[ExpenseModel] = list(db.scalars(stmt).all())

    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(TAX_REPORT_HEADERS)

    for e in items:
        is_void = e.status == ES.REPLACED_VOID
        sign = Decimal("-1") if is_void else Decimal("1")

        def _tax_fmt(val: Decimal | None, _s: Decimal = sign) -> str:
            return str(val * _s) if val is not None else ""

        subtypes: list[str] = json.loads(e.voucher_subtypes or "[]")
        categories: list[str] = json.loads(e.voucher_categories or "[]")
        exp_cats: list[str] = json.loads(e.expense_categories or "[]")

        v_cat = categories[0] if categories else (e.voucher_categories or "")
        v_sub = subtypes[0] if subtypes else ""
        tax_type = _classify_tax_type(v_cat, v_sub)

        remark = "已沖銷" if is_void else ""

        writer.writerow([
            e.serial_number,
            str(e.expense_date) if e.expense_date else "",
            e.invoice_number or "",
            v_cat,
            v_sub,
            tax_type,
            e.seller_tax_id or "",
            e.seller_name or "",
            _tax_fmt(e.net_amount),
            _tax_fmt(e.tax_amount),
            _tax_fmt(e.total_amount),
            exp_cats[0] if exp_cats else "",
            e.uploader_name or "",
            e.uploader_dept or "",
            e.item_description or "",
            e.user_description or "",
            e.status.value,
            remark,
        ])

    csv_content = buf.getvalue()
    filename = f"tax-report-{date_from}-{date_to}.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── POST /expenses（手動新增）──────────────────────────────────────
@router.post("/expenses", response_model=dict, status_code=201)
def create_expense(body: ExpenseCreate, db: Session = Depends(get_db)) -> dict:
    """Dashboard 手動新增費用（不透過 LINE）。"""
    expense = expense_service.create_expense_manual(db, **body.model_dump(exclude_none=True))
    return {
        "status": "success",
        "data": ExpenseRead.model_validate(expense).model_dump(),
        "message": "Expense created",
    }


# ── GET /expenses/waiting-returns（待退貨管理清單）────────────────
# ⚠️ 必須在 /{expense_id} 之前定義，否則 "waiting-returns" 會被解析為 UUID
@router.get("/expenses/waiting-returns", response_model=dict)
def list_waiting_returns(
    db: Session = Depends(get_db),
) -> dict:
    """
    回傳所有待退貨相關案件：
    - cases：WAITING_RETURN 原始憑證 + 已自動配對的補件
    - orphan_supplements：尚未配對的退貨補件（三種情境：VOID_REPLACE/CREDIT_NOTE/RETURN_SUPPLEMENT）
    - total：WAITING_RETURN 案件數（用於 badge）

    左側（cases）自動納入被補件以 referenced_invoice_number 引用的原始憑證，
    即使原始憑證不是 WAITING_RETURN 狀態。
    右側補件帶有 suggested_match，前端可一鍵確認配對。
    """
    # Step 1：取所有 WAITING_RETURN 原始憑證
    wr_invoices: list[Expense] = list(db.scalars(
        select(Expense).where(
            Expense.status == ExpenseStatus.WAITING_RETURN,
            Expense.is_active == True,
        ).order_by(Expense.created_at.desc())
    ).all())

    # Step 2：取所有尚未配對的退貨補件（三種情境，parent_id IS NULL）
    supplements: list[Expense] = list(db.scalars(
        select(Expense).where(
            Expense.relation_type.in_(["VOID_REPLACE", "CREDIT_NOTE", "RETURN_SUPPLEMENT"]),
            Expense.parent_id.is_(None),
            Expense.is_active == True,
        ).order_by(Expense.created_at.desc())
    ).all())

    # Step 2b：取所有已以 parent_id 明確配對的補件（含 COMPLETED）
    # COMPLETED 補件若原始憑證仍為 WAITING_RETURN，仍需顯示於左側供確認；
    # 若原始憑證已離開 WAITING_RETURN（如 PENDING），則在 Step 5b 中過濾掉。
    all_paired_supplements: list[Expense] = list(db.scalars(
        select(Expense).where(
            Expense.relation_type.in_(["VOID_REPLACE", "CREDIT_NOTE", "RETURN_SUPPLEMENT"]),
            Expense.parent_id.isnot(None),
            Expense.is_active == True,
        ).order_by(Expense.created_at.desc())
    ).all())

    # Step 3：以 invoice_number 建立可查找的 index
    invoice_by_number: dict[str, Expense] = {
        inv.invoice_number: inv
        for inv in wr_invoices
        if inv.invoice_number
    }
    invoice_by_id: dict[uuid.UUID, Expense] = {inv.id: inv for inv in wr_invoices}

    # Step 4：VOID_REPLACE 補件有 referenced_invoice_number 時，自動拉入原始憑證（不限 WAITING_RETURN）
    for sup in supplements:
        if sup.referenced_invoice_number and sup.referenced_invoice_number not in invoice_by_number:
            original = db.scalar(
                select(Expense).where(
                    Expense.invoice_number == sup.referenced_invoice_number,
                    Expense.is_active == True,
                ).order_by(Expense.created_at.desc()).limit(1)
            )
            if original and original.id not in invoice_by_id:
                invoice_by_number[original.invoice_number] = original
                invoice_by_id[original.id] = original

    all_left_invoices = list(invoice_by_id.values())
    matched_invoice_ids: set[uuid.UUID] = set()
    # cases_dict：以 invoice.id 為 key，支援同一張原始憑證對應多筆補件
    cases_dict: dict[str, dict] = {}
    orphan_supplements = []

    # Step 5：補件配對原始憑證（parent_id IS NULL，以 referenced_invoice_number 匹配）
    for sup in supplements:
        matched_invoice: Expense | None = None
        if sup.referenced_invoice_number:
            matched_invoice = invoice_by_number.get(sup.referenced_invoice_number)
        if matched_invoice:
            key = str(matched_invoice.id)
            if key not in cases_dict:
                cases_dict[key] = {
                    "invoice": ExpenseWithImages.model_validate(matched_invoice).model_dump(),
                    "supplements": [],
                }
                matched_invoice_ids.add(matched_invoice.id)
            cases_dict[key]["supplements"].append(
                ExpenseWithImages.model_validate(sup).model_dump()
            )
        else:
            # COMPLETED 補件已完成配對流程，不再顯示於孤立補件區
            if sup.status != ExpenseStatus.COMPLETED:
                sup_data = ExpenseWithImages.model_validate(sup).model_dump()
                # 若補件有 referenced_invoice_number 但原始憑證尚在左側，標記建議配對
                if sup.referenced_invoice_number:
                    orig = invoice_by_number.get(sup.referenced_invoice_number)
                    sup_data["suggested_match"] = (
                        {"expense_id": str(orig.id), "serial_number": orig.serial_number}
                        if orig else None
                    )
                else:
                    sup_data["suggested_match"] = None
                orphan_supplements.append(sup_data)

    # Step 5b：以 parent_id 明確配對的補件（pair_expense API 設定）
    # 若原始憑證不是 WAITING_RETURN（手動加入情境），動態載入並加入左側
    for sup in all_paired_supplements:
        matched_invoice = invoice_by_id.get(sup.parent_id)
        if not matched_invoice and sup.parent_id:
            parent = db.get(Expense, sup.parent_id)
            if parent and parent.is_active:
                matched_invoice = parent
                invoice_by_id[parent.id] = parent
        if matched_invoice:
            # 原始憑證已不是 WAITING_RETURN（已被 finalizeCase 移出）→ 不再顯示
            if matched_invoice.status != ExpenseStatus.WAITING_RETURN:
                continue
            key = str(matched_invoice.id)
            if key not in cases_dict:
                cases_dict[key] = {
                    "invoice": ExpenseWithImages.model_validate(matched_invoice).model_dump(),
                    "supplements": [],
                }
                matched_invoice_ids.add(matched_invoice.id)
            cases_dict[key]["supplements"].append(
                ExpenseWithImages.model_validate(sup).model_dump()
            )

    # Step 6：左側原始憑證若尚無對應補件，單獨列出（supplements=[]）
    for inv in all_left_invoices:
        if inv.id not in matched_invoice_ids:
            key = str(inv.id)
            if key not in cases_dict:
                cases_dict[key] = {
                    "invoice": ExpenseWithImages.model_validate(inv).model_dump(),
                    "supplements": [],
                }

    cases = list(cases_dict.values())

    wr_count = sum(1 for inv in invoice_by_id.values() if inv.status == ExpenseStatus.WAITING_RETURN)

    return {
        "status": "success",
        "data": {
            "cases": cases,
            "orphan_supplements": orphan_supplements,
            "total": wr_count,
        },
        "message": "ok",
    }


# ── POST /expenses/{id}/pair（配對退貨補件與原始費用）──────────────
# ⚠️ 必須在 /{expense_id} 之前定義
class PairRequest(BaseModel):
    original_expense_id: uuid.UUID


@router.post("/expenses/{expense_id}/pair", response_model=dict)
def pair_expense(
    expense_id: uuid.UUID,
    body: PairRequest,
    db: Session = Depends(get_db),
) -> dict:
    """配對退貨補件（補件 → parent_id 指向原始費用）。"""
    try:
        expense = expense_service.pair_expenses(db, expense_id, body.original_expense_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "status": "success",
        "data": ExpenseRead.model_validate(expense).model_dump(),
        "message": "配對成功",
    }


# ── GET /expenses/{id}/related（查詢關聯報帳）────────────────────
# ⚠️ 必須在 /{expense_id} 之前定義，否則 "related" 會被解析為 UUID
@router.get("/expenses/{expense_id}/related", response_model=dict)
def get_related_expenses(expense_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    """查詢以此報帳為 parent 的所有關聯記錄（換單、折讓、補差額）。"""
    children = list(db.scalars(
        select(Expense).where(Expense.parent_id == expense_id)
    ).all())
    return {
        "status": "success",
        "data": [ExpenseRead.model_validate(c).model_dump() for c in children],
        "message": "ok",
    }


# ── GET /expenses/{id}/batch（批次組查詢）────────────────────────
@router.get("/expenses/{expense_id}/batch", response_model=dict)
def get_expense_batch(
    expense_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict:
    """回傳與指定 expense 同一批次（相同 group_id）的所有 Expense，含 images 子清單。"""
    expenses = expense_service.get_batch_expenses(db, expense_id)
    return {
        "status": "success",
        "data": {"expenses": [ExpenseWithImages.model_validate(e).model_dump() for e in expenses]},
        "message": "ok",
    }


# ── GET /expenses/{id}（單筆查詢）─────────────────────────────────
@router.get("/expenses/{expense_id}", response_model=dict)
def get_expense(expense_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    expense = expense_service.get_expense(db, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    return {
        "status": "success",
        "data": ExpenseRead.model_validate(expense).model_dump(),
        "message": "ok",
    }


# ── PATCH /expenses/reorder（拖曳排序持久化）─────────────────────
# ⚠️ 必須定義在 PATCH /expenses/{expense_id} 之前，避免 "reorder" 被當成 UUID 路徑參數
class ReorderRequest(BaseModel):
    ordered_ids: list[str]


@router.patch("/expenses/reorder", response_model=dict)
def reorder_expenses(
    body: ReorderRequest,
    db: Session = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    """
    依照前端傳入的 ID 清單順序，將 display_order 寫入 DB。
    前端完整傳入排列後的所有 ID，後端依序 0, 1, 2... 儲存。
    """
    expense_service.reorder_expenses(db, body.ordered_ids)
    return {"status": "success", "data": None, "message": "排序已儲存"}


# ── PATCH /expenses/{id}（部分更新欄位）───────────────────────────
@router.patch("/expenses/{expense_id}", response_model=dict)
def update_expense(
    expense_id: uuid.UUID,
    body: ExpenseUpdate,
    db: Session = Depends(get_db),
) -> dict:
    """Dashboard 審核表單儲存：部分更新 Expense 欄位（含可選的 status 變更）。"""
    updates = body.model_dump(exclude_unset=True)
    expense = expense_service.update_expense(db, expense_id, updates)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    return {
        "status": "success",
        "data": ExpenseRead.model_validate(expense).model_dump(),
        "message": "Expense updated",
    }


# ── DELETE /expenses/{id}（刪除）──────────────────────────────────
@router.delete("/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    """刪除單筆費用紀錄。"""
    # Bug 2：刪除前確認無已配對子補件，避免補件變孤兒
    child_supplements = list(db.scalars(
        select(Expense).where(Expense.parent_id == expense_id)
    ).all())
    if child_supplements:
        serials = "、".join(s.serial_number for s in child_supplements)
        raise HTTPException(
            status_code=400,
            detail=f"此單據有已配對補件（{serials}），請先解除配對再刪除",
        )
    deleted = expense_service.delete_expense(db, expense_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Expense not found")


# ── PATCH /expenses/{id}/resolve-duplicate（裁決重複憑證）────────
class ResolveDuplicateRequest(BaseModel):
    action: Literal["dismiss", "delete"]


@router.patch("/expenses/{expense_id}/resolve-duplicate", response_model=dict)
def resolve_duplicate(
    expense_id: uuid.UUID,
    body: ResolveDuplicateRequest,
    db: Session = Depends(get_db),
) -> dict:
    """處理疑似重複憑證：dismiss（確認合法，清除警示）或 delete（刪除此筆）。"""
    from sqlalchemy import select as sa_select
    from models.expense import Expense as ExpenseModel

    expense = db.scalar(sa_select(ExpenseModel).where(ExpenseModel.id == expense_id))
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    if expense.possible_duplicate_of is None:
        raise HTTPException(status_code=400, detail="此費用單無重複憑證標記")

    if body.action == "dismiss":
        expense.possible_duplicate_of = None
        db.commit()
        return {"status": "success", "data": None, "message": "已確認為合法單據，警示已清除"}

    # action == "delete"
    deleted = expense_service.delete_expense(db, expense_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Expense not found")
    return {"status": "success", "data": None, "message": "重複費用單已刪除"}


# ── PATCH /expenses/{id}/reject（退回單據 + LINE 推播）──────────
class RejectRequest(BaseModel):
    reason: str = ""


@router.patch("/expenses/{expense_id}/reject", response_model=dict)
def reject_expense(
    expense_id: uuid.UUID,
    body: RejectRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    退回指定報帳單：更新 DB 狀態為 REJECTED，寫入退回原因，
    並依 ENABLE_LINE_PUSH_REJECT 開關決定是否發送 LINE 推播通知。
    """
    expense = expense_service.reject_expense(db, str(expense_id), body.reason)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    # LINE 推播（功能開關控制，異常不影響 API 回應）
    if settings.enable_line_push_reject and expense.user_id:
        user = db.get(User, expense.user_id)
        if user and user.line_user_id:
            line_service.push_reject_notification(
                line_user_id=user.line_user_id,
                upload_date=str(expense.upload_date.strftime("%Y-%m-%d %H:%M")) if expense.upload_date else None,
                invoice_number=expense.invoice_number,
                total_amount=str(expense.total_amount) if expense.total_amount is not None else None,
                voucher_categories=expense.voucher_categories,
            )

    return {"status": "success", "data": None, "message": "單據已退回"}


# ── POST /expenses/{id}/images（追加補件圖片）────────────────────
@router.post("/expenses/{expense_id}/images", response_model=dict)
async def upload_expense_image(
    expense_id: uuid.UUID,
    file: UploadFile = File(...),
    image_type: Literal["expense", "item"] = Form(...),
    db: Session = Depends(get_db),
) -> dict:
    """
    追加補件圖片至對應陣列末尾：
    - image_type='expense' → 追加至 image_url[]
    - image_type='item'    → 追加至 item_image_url[]
    """
    expense = expense_service.get_expense(db, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="只允許上傳圖片檔案")

    ext = Path(file.filename or "image.jpg").suffix or ".jpg"
    filename = f"{uuid.uuid4()}{ext}"
    dest = UPLOADS_DIR / filename

    try:
        content = await file.read()
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"檔案超過大小限制（上限 {settings.max_upload_bytes // (1024 * 1024)} MB）",
            )
        dest.write_bytes(content)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"圖片儲存失敗：{e}", exc_info=True)
        raise HTTPException(status_code=500, detail="圖片儲存失敗，請稍後再試")

    updated = expense_service.append_expense_image(
        db, expense_id, f"uploads/{filename}", image_type
    )
    return {
        "status": "success",
        "data": ExpenseRead.model_validate(updated).model_dump(),
        "message": f"{image_type} image appended",
    }


# ── POST /expenses/{id}/images/replace（替換指定索引圖片）──────────
@router.post("/expenses/{expense_id}/images/replace", response_model=dict)
async def replace_expense_image(
    expense_id: uuid.UUID,
    file: UploadFile = File(...),
    image_type: Literal["expense", "item"] = Form(...),
    index: int = Form(...),
    db: Session = Depends(get_db),
) -> dict:
    """替換費用中指定索引的圖片（index 為陣列位置，從 0 開始）。"""
    expense = expense_service.get_expense(db, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="只允許上傳圖片檔案")

    ext = Path(file.filename or "image.jpg").suffix or ".jpg"
    filename = f"{uuid.uuid4()}{ext}"
    dest = UPLOADS_DIR / filename

    try:
        content = await file.read()
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"檔案超過大小限制（上限 {settings.max_upload_bytes // (1024 * 1024)} MB）",
            )
        dest.write_bytes(content)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"圖片儲存失敗：{e}", exc_info=True)
        raise HTTPException(status_code=500, detail="圖片儲存失敗，請稍後再試")

    updated = expense_service.replace_expense_image(
        db, expense_id, f"uploads/{filename}", image_type, index
    )
    if not updated:
        raise HTTPException(status_code=400, detail="索引越界或費用不存在")

    return {
        "status": "success",
        "data": ExpenseRead.model_validate(updated).model_dump(),
        "message": f"{image_type} image replaced at index {index}",
    }


# ── PATCH /expenses/{id}/images/{image_id}（修正圖片分類）────────
@router.patch("/expenses/{expense_id}/images/{image_id}", response_model=dict)
def update_expense_image_classification(
    expense_id: uuid.UUID,
    image_id: uuid.UUID,
    body: ExpenseImageUpdate,
    db: Session = Depends(get_db),
) -> dict:
    """修正 ExpenseImage 的分類欄位（is_voucher / voucher_category / expense_category 等）。"""
    image = expense_service.update_expense_image(
        db, expense_id, image_id, body.model_dump(exclude_unset=True)
    )
    if not image:
        raise HTTPException(status_code=404, detail="Image not found or does not belong to this expense")
    return {
        "status": "success",
        "data": ExpenseImageRead.model_validate(image).model_dump(),
        "message": "分類已更新",
    }


# ── POST /expenses/{id}/images/{image_id}/move（跨交易搬移圖片）──
@router.post("/expenses/{expense_id}/images/{image_id}/move", response_model=dict)
def move_expense_image(
    expense_id: uuid.UUID,
    image_id: uuid.UUID,
    body: MoveImageRequest,
    db: Session = Depends(get_db),
) -> dict:
    """將 ExpenseImage 從一筆 Expense 搬移至同批次的另一筆。"""
    if body.target_expense_id == expense_id:
        raise HTTPException(status_code=400, detail="來源與目標 Expense 相同")
    image = expense_service.move_expense_image(db, expense_id, image_id, body.target_expense_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found or expense not found")
    return {
        "status": "success",
        "data": ExpenseImageRead.model_validate(image).model_dump(),
        "message": "圖片已搬移",
    }


# ── GET /expenses/{id}/images（查詢圖片清單）─────────────────────
@router.get("/expenses/{expense_id}/images", response_model=dict)
def get_expense_images(
    expense_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict:
    """查詢指定費用的所有圖片，按 sequence_order ASC 排序。"""
    expense = expense_service.get_expense(db, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    images = expense_service.get_expense_images(db, expense_id)
    return {
        "status": "success",
        "data": {
            "expense_id": str(expense_id),
            "images": [ExpenseImageRead.model_validate(img).model_dump() for img in images],
        },
        "message": "成功",
    }


# ── POST /expenses/{id}/reocr（重新辨識）─────────────────────────
@router.post("/expenses/{expense_id}/reocr", response_model=dict)
async def reocr_expense(
    expense_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict:
    """
    重新對費用影像執行 OCR，並將辨識結果更新至 DB 中的對應欄位。
    使用與 LINE Webhook 相同的 classify_and_extract_with_retry 流程。
    """
    expense = expense_service.get_expense(db, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    # 取第一張費用影像路徑（格式：uploads/xxx.jpg）
    image_urls: list = expense.image_url or []
    if not image_urls:
        raise HTTPException(status_code=400, detail="此費用無可辨識的影像")

    image_path = image_urls[0]

    # 複用 ocr_service（與 LINE 端完全相同的 OCR 流程）
    ocr: VoucherOCRResult = await classify_and_extract_with_retry(image_path)

    if not ocr.success:
        logger.error("reocr_expense 辨識失敗 expense_id=%s: %s", expense_id, ocr.error)
        raise HTTPException(status_code=422, detail=f"OCR 辨識失敗：{ocr.error}")

    # 只更新有值的欄位，避免覆蓋原有人工填寫內容
    updates: dict = {}
    if ocr.expense_date:
        updates["expense_date"] = ocr.expense_date
    if ocr.invoice_number:
        updates["invoice_number"] = ocr.invoice_number
    if ocr.total_amount is not None:
        updates["total_amount"] = Decimal(str(ocr.total_amount))
    if ocr.net_amount is not None:
        updates["net_amount"] = Decimal(str(ocr.net_amount))
    if ocr.tax_amount is not None:
        updates["tax_amount"] = Decimal(str(ocr.tax_amount))
    if ocr.seller_tax_id:
        updates["seller_tax_id"] = ocr.seller_tax_id
    if ocr.seller_name:
        updates["seller_name"] = ocr.seller_name
    if ocr.item_description:
        updates["item_description"] = ocr.item_description

    updated_expense = expense_service.update_expense(db, expense_id, updates)

    return {
        "status": "success",
        "data": ExpenseRead.model_validate(updated_expense).model_dump(),
        "message": "重新辨識完成",
    }
