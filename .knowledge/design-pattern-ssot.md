# 集中定義設計模式（SSOT Pattern）

> 適用場景：任何「一份清單被多個地方使用」的情境。  
> 例如：下拉選單、狀態清單、費用科目、角色權限、語系翻譯、錯誤代碼。

---

## 一、核心概念（自己複習用）

### 問題的根源

當你有一份清單（例如費用科目），然後：

- 前端下拉選單寫了一份
- 後端 API 回傳又寫了一份
- CSV 匯出又寫了一份
- OCR prompt 又寫了一份

**只要改名字，你要改四個地方。改漏一個就出錯，而且沒有任何機制告訴你漏了。**

這就是違反 **DRY（Don't Repeat Yourself）** 原則的具體症狀。

---

### 解法的三個步驟

```
步驟一：建立單一來源
    一個檔案定義所有資料，其他地方只能 import，不能複製。

步驟二：DB 存穩定的 key，不存會變的 label
    key = 程式用的英文代號（永遠不改）  →  存進 DB
    label = 使用者看的中文名稱（可以改）→  顯示時才翻譯

步驟三：兩個轉換函式包住所有進出
    寫入前：normalize(任意格式) → key
    讀取時：key → label
```

---

### 這樣設計的好處

| 情境 | 以前 | 現在 |
|------|------|------|
| 新增一個科目 | 改 4 個檔案 | 改 1 行 |
| 改一個科目的顯示名稱 | 改 4 個檔案 + 跑 DB migration | 改 1 行，DB 完全不動 |
| OCR 回傳奇怪的字串 | 直接存進 DB，之後很難修 | normalize() 自動修正，存的永遠是合法 key |
| 加一個新的輸出管道（如 LINE 推播） | 又要複製一份清單 | import 同一個模組就好 |

---

## 二、給 Claude Code 看的 Prompt（直接複製使用）

### 通用版（任何清單類設計）

```
請用 Single Source of Truth（SSOT）方式設計這個功能。

規則：
1. 在 core/ 或 config/ 底下建立一個「單一來源」模組，集中定義所有選項清單。
2. 這個模組要自動產生以下衍生資料（不要手動維護）：
   - key → label 的查找字典
   - label → key 的反查字典
   - 合法 key 的集合（用來驗證）
   - 預設 key（無法辨識時的 fallback）
3. 所有其他地方（API 回傳、前端下拉、OCR prompt、CSV 匯出）只能從這個模組 import，不得複製貼上相同資料。
4. DB 存穩定的英文 key，不存人類看的 label。
5. 寫入 DB 前，一律過 normalize(input) → key 的轉換函式。
6. 讀取 DB 後，一律過 key_to_label(key) → label 的翻譯函式，在 API response 的 schema 層處理。
7. 新增或修改選項，只改單一來源模組那一個檔案，其他地方自動跟上。
```

### 針對「有多個地方顯示同一份下拉選單」的情境

```
這個功能的下拉選單選項會在以下地方出現：
- 前端 UI 下拉
- API 回傳欄位
- [其他你列出的地方]

請用 SSOT 設計：
1. 建一個 Python 模組（或 JS/TS 的 constants 檔）集中定義所有選項。
2. 每個選項有兩個欄位：key（存 DB 用）和 label（顯示用）。
3. 從這個模組自動衍生 KEY_TO_LABEL、LABEL_TO_KEY 兩個字典。
4. API endpoint 直接把這個模組的清單回傳給前端。
5. 前端下拉的 value 用 key，顯示文字用 label。
6. 不要在 API handler、CSV、prompt 任何地方重複寫一次選項清單。
```

### 針對「改一個地方，其他要自動跟上」的情境

```
這個系統有一個清單會影響多個地方，我要求：
- 只維護一份定義，其他全部自動衍生
- 使用者介面顯示的文字（label）和程式內部用的代號（key）要分開
- label 改動時，DB 的歷史資料不需要跑 migration
- 有人傳入不合法的值時，要 log warning 並給預設值，不要讓程式崩潰

請按照上面的規則，設計單一來源模組，並告訴我哪些地方要 import 它。
```

---

## 三、跟主管或同事講解用的口稿

### 30 秒版（電梯簡報）

> 「我們以前的做法是，同一份選項清單在程式碼裡複製了好幾份，每次改一個名字就要改四個地方，改漏一個就出錯。
>
> 我現在的設計是：這份清單只在一個地方定義，其他地方全部 import 它。改一行，全部自動跟上。」

---

### 3 分鐘版（技術說明）

> 「這個設計解決的是**資料不同步**的問題。
>
> 以費用科目為例，以前同一份科目清單分散在四個地方：前端下拉、API 回傳、CSV 匯出、OCR prompt。一旦要改名稱，要記得改四個地方，改漏任何一個，前端顯示的跟 CSV 輸出的就不一樣。
>
> 我的做法是在 `core/expense_categories.py` 建立唯一的定義，其他三個地方全部 import 它，不再各自維護。
>
> 另外，資料庫存的是**英文 key**（例如 `TRANS_TAXI`），不存中文名稱（例如「勞-交通費-計程車資」）。這樣改中文名稱的時候，資料庫完全不需要動，歷史資料不受影響。使用者看到的中文，是在 API 回傳前才即時翻譯的。
>
> 這個設計模式叫做 Single Source of Truth，是業界處理這類問題的標準做法。」

---

### 回答「為什麼要這樣，直接寫不是比較快？」

> 「直接寫第一次確實比較快，但維護成本是指數級的。
>
> 以這個專案為例，我們之前改費用科目的格式，要改 4 個檔案，還要跑 SQL migration 修正歷史資料，前後花了幾個小時，而且還是出現了不同步的問題。
>
> 用 SSOT 設計之後，同樣的修改只要改一行程式碼，其他全部自動跟上，花不到一分鐘。」

---

## 四、判斷「什麼時候該用這個設計」的標準

符合以下任一條件，就應該用 SSOT 設計：

```
✓ 同一份清單（選項、狀態、角色、科目）會在超過兩個地方用到
✓ 這份清單未來可能會新增或修改
✓ 清單的「顯示名稱」和「程式代號」是不同的東西
✓ 這份清單會同時出現在前端 UI 和後端邏輯中
✓ 這份清單會輸出到 CSV、報表、或其他系統
```

不需要的情況：

```
✗ 這份清單只在一個地方用，而且未來幾乎不會改
✗ 只有 2 個選項（例如 true/false、啟用/停用）
```

---

## 五、標準的檔案結構範本

```
core/
└── your_categories.py        ← 唯一來源，其他地方只能 import 這裡

    內容：
    - CATEGORIES = [{"key": "...", "label": "..."}, ...]
    - KEY_TO_LABEL = {自動衍生}
    - LABEL_TO_KEY = {自動衍生}
    - VALID_KEYS = {自動衍生}
    - DEFAULT_KEY = "..."
    - normalize(raw) → key    ← 寫入 DB 前用
    - key_to_label(key) → label  ← 讀取 DB 後用
    - build_prompt_list() → str  ← 需要清單字串時用

schemas/
└── your_model.py
    → model_validator 呼叫 key_to_label()，API 回傳 label

services/
└── your_service.py
    → 寫入 DB 前呼叫 normalize()

routers/
└── config.py
    → GET /config/xxx 直接回傳 CATEGORIES 給前端

DB:
    your_table.category_column  → 存 key（VARCHAR，不存 label）
```

---

## 六、這個設計模式的正式名稱

| 名稱 | 意思 |
|------|------|
| **Single Source of Truth (SSOT)** | 一份資料只有一個權威定義 |
| **DRY（Don't Repeat Yourself）** | 每個知識只在一個地方存在 |
| **Normalization** | 寫入前統一格式，讀取時才翻譯 |
| **Separation of Concerns** | key（機器用）和 label（人類用）嚴格分離 |
| **Configuration as Code** | 用程式碼定義設定，而非 JSON 或 DB |

> 給 Claude Code 下 Prompt 時，直接說「請用 **SSOT + DRY** 設計」，
> 然後列出哪些地方會用到這份資料，Claude 就會知道你要什麼。
