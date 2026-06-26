"""費用科目單一來源（Single Source of Truth）。

所有其他模組需要的科目清單、Key/Label 映射、OCR prompt 內容，
皆從此模組衍生，不得在其他檔案中另行維護複本。
"""

import logging
from typing import Final

logger = logging.getLogger(__name__)

# ── 唯一的科目定義清單（順序即前端下拉順序）────────────────────────────────
EXPENSE_CATEGORIES: Final[list[dict[str, str]]] = [
    {"key": "LABOR_GENERAL",               "label": "勞-勞務費"},
    {"key": "MEAL_GENERAL",                "label": "勞-餐飲費"},
    {"key": "MEAL_OVERTIME",               "label": "勞-誤餐費"},
    {"key": "DRINKING_WATER",              "label": "勞-飲用水"},
    {"key": "VENUE_RENTAL",                "label": "勞-場地租金"},
    {"key": "OFFICE_RENTAL",               "label": "勞-辦公室租金"},
    {"key": "OFFICE_EQUIPMENT_RENTAL",     "label": "勞-辦公室用品租金"},
    {"key": "VEHICLE_RENTAL",              "label": "勞-車輛租金"},
    {"key": "ACCOMMODATION_GENERAL",       "label": "勞-住宿費"},
    {"key": "UTILITY_WATER_ELEC",          "label": "勞-水電瓦斯費"},
    {"key": "UTILITY_TELECOM",             "label": "勞-電信/網路費"},
    {"key": "STATIONERY",                  "label": "勞-文具用品"},
    {"key": "POSTAGE",                     "label": "勞-郵電費"},
    {"key": "TRANS_RAIL",                  "label": "勞-交通費-高鐵、台鐵、客運、遊覽車"},
    {"key": "TRANS_TAXI",                  "label": "勞-交通費-計程車資"},
    {"key": "TRANS_TOLL",                  "label": "勞-交通費-過路費"},
    {"key": "TRANS_FINE",                  "label": "勞-交通費-罰單"},
    {"key": "TRANS_PARKING",               "label": "勞-交通費-停車費"},
    {"key": "TRANS_FUEL",                  "label": "勞-交通費-油資"},
    {"key": "HR_INSURANCE",                "label": "勞-保險費"},
    {"key": "PRODUCTION_SUPPLIES_GENERAL", "label": "勞-現場拍攝用品購買"},
    {"key": "MISC_GENERAL",                "label": "勞-雜費"},
    {"key": "ART_SCRIPT",                  "label": "勞-劇本費"},
    {"key": "ENTERTAINMENT_GENERAL",       "label": "勞-交際費"},
    {"key": "PERF_ACTOR",                  "label": "勞-演出費"},
    {"key": "PERF_EXTRA",                  "label": "勞-臨演演出費"},
    {"key": "ART_SCENE_MATERIAL",          "label": "勞-置景材料耗材費"},
    {"key": "ART_SET_MATERIAL",            "label": "勞-陳設材料耗材費"},
    {"key": "ART_PROP_BUY",                "label": "勞-美術道具費"},
    {"key": "ART_PROP_RENTAL",             "label": "勞-美術道具租金"},
    {"key": "COSTUME_MAKEUP",              "label": "勞-造型化妝費"},
    {"key": "COSTUME_SFX_MAKEUP",          "label": "勞-特殊化妝費"},
    {"key": "COSTUME_BUY",                 "label": "勞-服裝費"},
    {"key": "COSTUME_RENTAL",              "label": "勞-服裝租金"},
    {"key": "EQUIP_GRIP",                  "label": "勞-場務器材費"},
    {"key": "EQUIP_GRIP_LOSS",             "label": "勞-場務遺失及損壞"},
    {"key": "EQUIP_LIGHTING",              "label": "勞-燈光費"},
    {"key": "EQUIP_LIGHTING_LOSS",         "label": "勞-燈光遺失及損壞"},
    {"key": "EQUIP_CAMERA",                "label": "勞-攝影費"},
    {"key": "EQUIP_CAMERA_LOSS",           "label": "勞-攝影遺失及損壞"},
    {"key": "EQUIP_SOUND",                 "label": "勞-收音器材費"},
    {"key": "EQUIP_SOUND_LOSS",            "label": "勞-收音遺失及損壞"},
    {"key": "EQUIP_DRONE",                 "label": "勞-航拍器材費"},
    {"key": "EQUIP_DRONE_LOSS",            "label": "勞-航拍遺失及損壞"},
    {"key": "POST_EDITING",                "label": "勞-剪接製作費"},
    {"key": "POST_ARCHIVE",                "label": "勞-檔管物品購置"},
    {"key": "POST_VFX",                    "label": "勞-特效素材費"},
    {"key": "HR_WELFARE_GENERAL",          "label": "勞-職工福利"},
    {"key": "UNSET",                       "label": "勞-未設定"},
]

# ── 衍生索引（從 EXPENSE_CATEGORIES 自動產生，不得手動維護）─────────────────
KEY_TO_LABEL: Final[dict[str, str]] = {c["key"]: c["label"] for c in EXPENSE_CATEGORIES}
LABEL_TO_KEY: Final[dict[str, str]] = {c["label"]: c["key"] for c in EXPENSE_CATEGORIES}
VALID_KEYS:   Final[frozenset[str]] = frozenset(KEY_TO_LABEL)

DEFAULT_KEY: Final[str] = "UNSET"

# ── 舊格式相容映射（Label 改名 / 無前綴 / 英文 parent key → 現行 key）────────
# 只有 normalize_to_key() 需要讀這份表，業務邏輯不得直接引用
_LEGACY_TO_KEY: Final[dict[str, str]] = {
    # 舊中文（無「勞-」前綴）
    "勞務費": "LABOR_GENERAL",
    "餐飲費": "MEAL_GENERAL",       "誤餐費": "MEAL_OVERTIME",
    "飲用水": "DRINKING_WATER",
    "場地租金": "VENUE_RENTAL",     "辦公室租金": "OFFICE_RENTAL",
    "辦公室用品租金": "OFFICE_EQUIPMENT_RENTAL", "車輛租金": "VEHICLE_RENTAL",
    "住宿費": "ACCOMMODATION_GENERAL",
    "水電瓦斯費": "UTILITY_WATER_ELEC", "水電費": "UTILITY_WATER_ELEC",
    "電信/網路費": "UTILITY_TELECOM",
    "文具用品": "STATIONERY",       "郵電費": "POSTAGE",
    "高鐵/台鐵/客運/遊覽車": "TRANS_RAIL",
    "計程車資": "TRANS_TAXI",       "過路費": "TRANS_TOLL",
    "罰單": "TRANS_FINE",           "停車費": "TRANS_PARKING",
    "油資": "TRANS_FUEL",           "保險費": "HR_INSURANCE",
    "現場拍攝用品購買": "PRODUCTION_SUPPLIES_GENERAL",
    "雜費": "MISC_GENERAL",         "劇本費": "ART_SCRIPT",
    "交際費": "ENTERTAINMENT_GENERAL",
    "演出費": "PERF_ACTOR",         "臨演演出費": "PERF_EXTRA",
    "置景材料耗材費": "ART_SCENE_MATERIAL", "陳設材料耗材費": "ART_SET_MATERIAL",
    "美術道具費": "ART_PROP_BUY",   "美術道具租金": "ART_PROP_RENTAL",
    "造型化妝費": "COSTUME_MAKEUP", "特殊化妝費": "COSTUME_SFX_MAKEUP",
    "服裝費": "COSTUME_BUY",        "服裝租金": "COSTUME_RENTAL",
    "場務器材費": "EQUIP_GRIP",     "場務遺失及損壞": "EQUIP_GRIP_LOSS",
    "燈光費": "EQUIP_LIGHTING",     "燈光遺失及損壞": "EQUIP_LIGHTING_LOSS",
    "攝影費": "EQUIP_CAMERA",       "攝影遺失及損壞": "EQUIP_CAMERA_LOSS",
    "收音器材費": "EQUIP_SOUND",    "收音遺失及損壞": "EQUIP_SOUND_LOSS",
    "航拍器材費": "EQUIP_DRONE",    "航拍遺失及損壞": "EQUIP_DRONE_LOSS",
    "剪接製作費": "POST_EDITING",   "檔管物品購置": "POST_ARCHIVE",
    "特效素材費": "POST_VFX",       "職工福利": "HR_WELFARE_GENERAL",
    # 舊英文 parent key
    "MEAL": "MEAL_GENERAL",         "RENTAL": "VENUE_RENTAL",
    "TRANSPORTATION": "PRODUCTION_SUPPLIES_GENERAL",
    "UTILITY": "UTILITY_WATER_ELEC","ACCOMMODATION": "ACCOMMODATION_GENERAL",
    "OFFICE_SUPPLY": "STATIONERY",  "PRODUCTION_SUPPLIES": "PRODUCTION_SUPPLIES_GENERAL",
    "MISC": "MISC_GENERAL",         "LABOR": "LABOR_GENERAL",
    "PERFORMANCE": "PERF_ACTOR",    "ENTERTAINMENT": "ENTERTAINMENT_GENERAL",
    "ART": "ART_PROP_BUY",          "COSTUME": "COSTUME_BUY",
    "EQUIPMENT": "EQUIP_GRIP",      "POST_PROD": "POST_EDITING",
    "HR_WELFARE": "HR_WELFARE_GENERAL",
    "INSURANCE": "HR_INSURANCE",    "GENERAL": "PRODUCTION_SUPPLIES_GENERAL",
    "OTHER": "MISC_GENERAL",
    # 未設定相容
    "未設定": "UNSET",              "勞-未設定": "UNSET",
}


def normalize_to_key(raw: str | None) -> str | None:
    """任意格式輸入（現行 key / 現行 label / 舊 label / 舊英文 key）→ 現行 key。

    OCR 輸出、前端表單送出、歷史資料匯入，都應在寫入 DB 前先過此函式。
    """
    if raw is None:
        return None
    if raw in VALID_KEYS:          # 已是現行 key
        return raw
    if raw in LABEL_TO_KEY:        # 現行 label → key
        return LABEL_TO_KEY[raw]
    if raw in _LEGACY_TO_KEY:      # 舊格式相容
        return _LEGACY_TO_KEY[raw]
    logger.warning("未知的 expense_category 值：%r，退回預設值 %s", raw, DEFAULT_KEY)
    return DEFAULT_KEY


def key_to_label(key: str | None) -> str | None:
    """key → 顯示用中文 label；未知 key 原樣回傳（不拋例外）。"""
    if key is None:
        return None
    return KEY_TO_LABEL.get(key, key)


def build_ocr_prompt_list() -> str:
    """生成 OCR prompt 所需的科目清單字串（由 EXPENSE_CATEGORIES 自動產生）。"""
    return " / ".join(c["label"] for c in EXPENSE_CATEGORIES)
