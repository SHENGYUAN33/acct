# UI 設計圖稿

| 欄位 | 值 |
|------|-----|
| ID | T1 |
| 專案 | AcctAssist |
| Sprint | Sprint 2 |
| 指派給 | designer |
| 優先級 | P0 |
| 狀態 | done |
| 依賴 | — |
| 預估 | 2h |
| 建立時間 | 2026-04-11T00:00:00.000Z |

---

## 任務描述

建立 Sprint 2 兩份 HTML 設計圖稿，供 G1 設計審核：

1. **`static/mockup/sprint2/rich_menu_design.html`**
   - LINE Rich Menu 視覺稿，尺寸 2500×843
   - 全寬單格，顯示「✅ 確認送出」
   - 動作類型標注：`Postback data="action=confirm_submit"`

2. **`static/mockup/sprint2/flex_message_design.html`**
   - 批次摘要 Flex Message 設計稿
   - 包含各憑證類型行（🧾發票 / 📋收據 / 👤勞報 / 🚌交通 / ↩️退貨折讓 / 📦品項照片）× 數量 × 金額
   - 底部：合計金額、所屬組別、備註、案件編號

兩份 mockup 需可在瀏覽器直接開啟預覽（不需 build），統一使用繁體中文。

## 驗收標準

- [ ] `static/mockup/sprint2/rich_menu_design.html` 可在瀏覽器直接開啟預覽
- [ ] `static/mockup/sprint2/flex_message_design.html` 可在瀏覽器直接開啟預覽
- [ ] Rich Menu 設計稿符合 LINE 官方尺寸規範（2500×843）
- [ ] Flex Message 設計稿涵蓋：各憑證類型行、合計金額行、組別/備註/案件編號欄位
- [ ] 繁體中文化完成，圖示對照正確（🧾📋👤🚌↩️📦）
- [ ] 設計稿放置於 `static/mockup/sprint2/` 目錄

---

## 事件紀錄

### 2026-04-11T00:00:00.000Z — 建立任務（assigned）
由 L1（project-lead）透過 /task-delegation 建立

### 2026-04-10T18:36:39.000Z — 開始執行（in_progress）
由 L1（project-lead）委派給 designer，第一波並行啟動

### 2026-04-10T18:36:39.000Z — 完成交付（in_review）
建立 `static/mockup/sprint2/rich_menu_design.html` 與 `flex_message_design.html`

### 2026-04-10T18:36:39.000Z — L1 審核通過（done）
審核者：project-lead。設計稿涵蓋所有憑證類型、Rich Menu 比例正確、兩份 HTML 可瀏覽器預覽，符合 G1 審核條件。
建立 `static/mockup/sprint2/rich_menu_design.html`（LINE Rich Menu 2500×843，全寬單格，Postback 標注）與 `static/mockup/sprint2/flex_message_design.html`（Flex Message 氣泡，含 6 種憑證類型行、合計金額、組別、備註、案件編號）；兩份 HTML 均可在瀏覽器直接開啟預覽，繁體中文，圖示正確。
