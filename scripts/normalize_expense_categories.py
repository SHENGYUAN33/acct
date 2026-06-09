"""一次性資料修正腳本：將舊格式費用科目統一加上「勞-」前綴。

執行方式：
    cd ocr
    python scripts/normalize_expense_categories.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import SessionLocal
from models.expense import Expense
from models.expense_image import ExpenseImage

# ── 舊值 → 新值對照表 ────────────────────────────────────────────
OLD_TO_NEW: dict[str, str] = {
    # 已有前綴（不異動）
    "勞-勞務費": "勞-勞務費",
    "勞-餐飲費": "勞-餐飲費",
    "勞-誤餐費": "勞-誤餐費",
    "勞-飲用水": "勞-飲用水",
    "勞-場地租金": "勞-場地租金",
    "勞-辦公室租金": "勞-辦公室租金",
    "勞-辦公室用品租金": "勞-辦公室用品租金",
    "勞-車輛租金": "勞-車輛租金",
    "勞-住宿費": "勞-住宿費",
    "勞-水電瓦斯費": "勞-水電瓦斯費",
    "勞-電信/網路費": "勞-電信/網路費",
    "勞-文具用品": "勞-文具用品",
    "勞-郵電費": "勞-郵電費",
    "勞-交通費-高鐵、台鐵、客運、遊覽車": "勞-交通費-高鐵、台鐵、客運、遊覽車",
    "勞-交通費-計程車資": "勞-交通費-計程車資",
    "勞-交通費-過路費": "勞-交通費-過路費",
    "勞-交通費-罰單": "勞-交通費-罰單",
    "勞-交通費-停車費": "勞-交通費-停車費",
    "勞-交通費-油資": "勞-交通費-油資",
    "勞-保險費": "勞-保險費",
    "勞-現場拍攝用品購買": "勞-現場拍攝用品購買",
    "勞-雜費": "勞-雜費",
    "勞-劇本費": "勞-劇本費",
    "勞-交際費": "勞-交際費",
    "勞-演出費": "勞-演出費",
    "勞-臨演演出費": "勞-臨演演出費",
    "勞-置景材料耗材費": "勞-置景材料耗材費",
    "勞-陳設材料耗材費": "勞-陳設材料耗材費",
    "勞-美術道具費": "勞-美術道具費",
    "勞-美術道具租金": "勞-美術道具租金",
    "勞-造型化妝費": "勞-造型化妝費",
    "勞-特殊化妝費": "勞-特殊化妝費",
    "勞-服裝費": "勞-服裝費",
    "勞-服裝租金": "勞-服裝租金",
    "勞-場務器材費": "勞-場務器材費",
    "勞-場務遺失及損壞": "勞-場務遺失及損壞",
    "勞-燈光費": "勞-燈光費",
    "勞-燈光遺失及損壞": "勞-燈光遺失及損壞",
    "勞-攝影費": "勞-攝影費",
    "勞-攝影遺失及損壞": "勞-攝影遺失及損壞",
    "勞-收音器材費": "勞-收音器材費",
    "勞-收音遺失及損壞": "勞-收音遺失及損壞",
    "勞-航拍器材費": "勞-航拍器材費",
    "勞-航拍遺失及損壞": "勞-航拍遺失及損壞",
    "勞-剪接製作費": "勞-剪接製作費",
    "勞-檔管物品購置": "勞-檔管物品購置",
    "勞-特效素材費": "勞-特效素材費",
    "勞-職工福利": "勞-職工福利",
    # 舊中文名稱（無前綴）→ 新名稱
    "勞務費": "勞-勞務費",
    "餐飲費": "勞-餐飲費",
    "誤餐費": "勞-誤餐費",
    "飲用水": "勞-飲用水",
    "場地租金": "勞-場地租金",
    "辦公室租金": "勞-辦公室租金",
    "辦公室用品租金": "勞-辦公室用品租金",
    "車輛租金": "勞-車輛租金",
    "住宿費": "勞-住宿費",
    "水電瓦斯費": "勞-水電瓦斯費",
    "水電費": "勞-水電瓦斯費",
    "電信/網路費": "勞-電信/網路費",
    "文具用品": "勞-文具用品",
    "郵電費": "勞-郵電費",
    "高鐵/台鐵/客運/遊覽車": "勞-交通費-高鐵、台鐵、客運、遊覽車",
    "計程車資": "勞-交通費-計程車資",
    "過路費": "勞-交通費-過路費",
    "罰單": "勞-交通費-罰單",
    "停車費": "勞-交通費-停車費",
    "油資": "勞-交通費-油資",
    "保險費": "勞-保險費",
    "現場拍攝用品購買": "勞-現場拍攝用品購買",
    "雜費": "勞-雜費",
    "劇本費": "勞-劇本費",
    "交際費": "勞-交際費",
    "演出費": "勞-演出費",
    "臨演演出費": "勞-臨演演出費",
    "置景材料耗材費": "勞-置景材料耗材費",
    "陳設材料耗材費": "勞-陳設材料耗材費",
    "美術道具費": "勞-美術道具費",
    "美術道具租金": "勞-美術道具租金",
    "造型化妝費": "勞-造型化妝費",
    "特殊化妝費": "勞-特殊化妝費",
    "服裝費": "勞-服裝費",
    "服裝租金": "勞-服裝租金",
    "場務器材費": "勞-場務器材費",
    "場務遺失及損壞": "勞-場務遺失及損壞",
    "燈光費": "勞-燈光費",
    "燈光遺失及損壞": "勞-燈光遺失及損壞",
    "攝影費": "勞-攝影費",
    "攝影遺失及損壞": "勞-攝影遺失及損壞",
    "收音器材費": "勞-收音器材費",
    "收音遺失及損壞": "勞-收音遺失及損壞",
    "航拍器材費": "勞-航拍器材費",
    "航拍遺失及損壞": "勞-航拍遺失及損壞",
    "剪接製作費": "勞-剪接製作費",
    "檔管物品購置": "勞-檔管物品購置",
    "特效素材費": "勞-特效素材費",
    "職工福利": "勞-職工福利",
    # 舊英文 parent key → 對應科目
    "MEAL": "勞-餐飲費",
    "RENTAL": "勞-場地租金",
    "TRANSPORTATION": "勞-現場拍攝用品購買",
    "UTILITY": "勞-水電瓦斯費",
    "ACCOMMODATION": "勞-住宿費",
    "OFFICE_SUPPLY": "勞-文具用品",
    "PRODUCTION_SUPPLIES": "勞-現場拍攝用品購買",
    "MISC": "勞-雜費",
    "LABOR": "勞-勞務費",
    "PERFORMANCE": "勞-演出費",
    "ENTERTAINMENT": "勞-交際費",
    "ART": "勞-美術道具費",
    "COSTUME": "勞-服裝費",
    "EQUIPMENT": "勞-場務器材費",
    "POST_PROD": "勞-剪接製作費",
    "HR_WELFARE": "勞-職工福利",
    "INSURANCE": "勞-保險費",
    "POSTAGE": "勞-郵電費",
    "STATIONERY": "勞-文具用品",
    "ENTERTAINMENT_GENERAL": "勞-交際費",
    "GENERAL": "勞-現場拍攝用品購買",
    "OTHER": "勞-雜費",
}


def normalize(value: str | None) -> str | None:
    if value is None:
        return None
    return OLD_TO_NEW.get(value, value)


def main() -> None:
    db = SessionLocal()
    try:
        # ── Step 1：修正 expense_images.expense_category ──────────────
        images = db.query(ExpenseImage).filter(ExpenseImage.expense_category.isnot(None)).all()
        img_updated = 0
        for img in images:
            new_val = normalize(img.expense_category)
            if new_val != img.expense_category:
                print(f"  image {img.id}: {img.expense_category!r} → {new_val!r}")
                img.expense_category = new_val
                img_updated += 1

        # ── Step 2：重新彙總 expenses.expense_categories ───────────────
        expenses = db.query(Expense).all()
        exp_updated = 0
        for exp in expenses:
            # 取出該費用的所有子圖片（已在 session 快取中）
            images_of_exp = (
                db.query(ExpenseImage)
                .filter(ExpenseImage.expense_id == exp.id)
                .all()
            )
            unique_cats: list[str] = []
            seen: set[str] = set()
            for img in images_of_exp:
                cat = normalize(img.expense_category)
                if cat and cat not in seen:
                    seen.add(cat)
                    unique_cats.append(cat)

            new_json = json.dumps(unique_cats, ensure_ascii=False) if unique_cats else None
            old_json = exp.expense_categories
            if new_json != old_json:
                exp.expense_categories = new_json
                exp_updated += 1

        db.commit()
        print(f"\n完成：更新 {img_updated} 筆 expense_images，{exp_updated} 筆 expenses")
    except Exception as e:
        db.rollback()
        print(f"錯誤：{e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
