"""業務常數集中管理。

將原本散落在 routers/expenses.py 頂層的對照表與欄位定義集中於此，
讓 Router 層只負責請求處理，不承擔業務常數的定義職責。

若其他模組（如 LINE 推播、報表產生、前端 API 等）需要這些對照，
統一從此模組 import，不要在各自檔案中重複定義。
"""

# ── 憑證類別 → 中文 ────────────────────────────────────────────────
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

# ── 費用狀態 → 中文 ────────────────────────────────────────────────
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

# ── 費用科目 key → 中文（對應 config/expense_categories.json categories[]）────
EXPENSE_CATEGORY_ZH: dict[str, str] = {
    "LABOR_GENERAL": "勞-勞務費",
    "MEAL_GENERAL": "勞-餐飲費",
    "MEAL_OVERTIME": "勞-誤餐費",
    "DRINKING_WATER": "勞-飲用水",
    "VENUE_RENTAL": "勞-場地租金",
    "OFFICE_RENTAL": "勞-辦公室租金",
    "OFFICE_EQUIPMENT_RENTAL": "勞-辦公室用品租金",
    "VEHICLE_RENTAL": "勞-車輛租金",
    "ACCOMMODATION_GENERAL": "勞-住宿費",
    "UTILITY_WATER_ELEC": "勞-水電瓦斯費",
    "UTILITY_TELECOM": "勞-電信/網路費",
    "STATIONERY": "勞-文具用品",
    "POSTAGE": "勞-郵電費",
    "TRANS_RAIL": "勞-交通費-高鐵、台鐵、客運、遊覽車",
    "TRANS_TAXI": "勞-交通費-計程車資",
    "TRANS_TOLL": "勞-交通費-過路費",
    "TRANS_FINE": "勞-交通費-罰單",
    "TRANS_PARKING": "勞-交通費-停車費",
    "TRANS_FUEL": "勞-交通費-油資",
    "HR_INSURANCE": "勞-保險費",
    "PRODUCTION_SUPPLIES_GENERAL": "勞-現場拍攝用品購買",
    "MISC_GENERAL": "勞-雜費",
    "ART_SCRIPT": "勞-劇本費",
    "ENTERTAINMENT_GENERAL": "勞-交際費",
    "PERF_ACTOR": "勞-演出費",
    "PERF_EXTRA": "勞-臨演演出費",
    "ART_SCENE_MATERIAL": "勞-置景材料耗材費",
    "ART_SET_MATERIAL": "勞-陳設材料耗材費",
    "ART_PROP_BUY": "勞-美術道具費",
    "ART_PROP_RENTAL": "勞-美術道具租金",
    "COSTUME_MAKEUP": "勞-造型化妝費",
    "COSTUME_SFX_MAKEUP": "勞-特殊化妝費",
    "COSTUME_BUY": "勞-服裝費",
    "COSTUME_RENTAL": "勞-服裝租金",
    "EQUIP_GRIP": "勞-場務器材費",
    "EQUIP_GRIP_LOSS": "勞-場務遺失及損壞",
    "EQUIP_LIGHTING": "勞-燈光費",
    "EQUIP_LIGHTING_LOSS": "勞-燈光遺失及損壞",
    "EQUIP_CAMERA": "勞-攝影費",
    "EQUIP_CAMERA_LOSS": "勞-攝影遺失及損壞",
    "EQUIP_SOUND": "勞-收音器材費",
    "EQUIP_SOUND_LOSS": "勞-收音遺失及損壞",
    "EQUIP_DRONE": "勞-航拍器材費",
    "EQUIP_DRONE_LOSS": "勞-航拍遺失及損壞",
    "POST_EDITING": "勞-剪接製作費",
    "POST_ARCHIVE": "勞-檔管物品購置",
    "POST_VFX": "勞-特效素材費",
    "HR_WELFARE_GENERAL": "勞-職工福利",
}

# ── CSV 匯出欄位定義 ────────────────────────────────────────────────
CSV_HEADERS: list[str] = [
    "案件編號", "ID", "上傳者", "上傳者組別", "費用提報者", "費用提報者組別",
    "上傳日期", "費用日期", "發票號碼", "憑證類別", "細項", "含稅金額", "未稅金額", "營業稅額",
    "賣方統編", "賣方公司", "項目說明", "憑證狀態", "退件原因",
    "建立時間", "更新時間",
]

# ── 進項稅額明細表欄位定義 ──────────────────────────────────────────
TAX_REPORT_HEADERS: list[str] = [
    "案件編號", "費用日期", "發票號碼", "憑證類型", "憑證子類型", "稅務類別",
    "賣方統編", "賣方名稱", "稅前金額", "營業稅額", "含稅金額",
    "費用科目", "上傳者", "上傳者組別", "項目說明", "使用者備註",
    "憑證狀態", "備注",
]
