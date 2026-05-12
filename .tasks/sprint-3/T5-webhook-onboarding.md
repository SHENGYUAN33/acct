# Webhook Onboarding 改寫（roster_binding 模式）

| 欄位 | 值 |
|------|-----|
| ID | T5 |
| 專案 | AcctAssist |
| Sprint | Sprint 3 |
| 指派給 | backend-architect |
| 優先級 | P0 |
| 狀態 | done |
| 依賴 | T1,T2,T4 |
| 預估 | 2h |
| 建立時間 | 2026-04-29T04:03:03.613Z |

---

## 任務描述

修改 `routers/webhook.py` 中的 Onboarding 區塊（現行 Line 217–246），在 `ENABLE_ROSTER_BINDING=True` 時使用名冊預綁定流程。

### 修改範圍

**只修改 `webhook.py` Line 217–246 的 Onboarding 區塊。**
其餘所有邏輯（批次 OCR、PostbackEvent、查詢進度等）不動。

### 新 Onboarding 邏輯（偽代碼）

```python
# === Onboarding 偵測（任何 MessageEvent 進入前先檢查）===
user = expense_service.get_or_create_user(db, line_user_id)

# --- 路徑 1：名冊預綁定模式 ---
if settings.enable_roster_binding:

    # 已完成綁定（real_name + department 都有值）→ 直接進入後續流程
    if user.real_name and user.department:
        pass  # 繼續往下走

    else:
        state = line_service.get_user_state(db, line_user_id)
        step = state.get("step", "") if state else ""

        # 使用者正在輸入員工編號
        if step == "BINDING_EMPLOYEE_ID" and isinstance(event.message, TextMessageContent):
            employee_id_input = event.message.text.strip()

            roster_entry = roster_service.bind_line_user(db, employee_id_input, line_user_id)

            if roster_entry:
                # 綁定成功：寫入 User
                expense_service.update_user_real_name(db, line_user_id, roster_entry.name)
                expense_service.update_user_department(db, line_user_id, roster_entry.department)
                line_service.delete_user_state(db, line_user_id)
                line_service.reply_text(
                    reply_token,
                    f"✅ 設定完成，{roster_entry.name}（{roster_entry.department}）您好！\n"
                    f"之後直接上傳發票照片即可報帳 📷",
                )
            else:
                # 找不到編號：允許重試
                line_service.reply_text(
                    reply_token,
                    f"⚠️ 找不到員工編號「{employee_id_input}」，請確認後重新輸入。\n"
                    f"（若有問題請聯繫製片組）",
                )
            continue

        else:
            # 第一次進入：引導輸入員工編號
            line_service.set_user_state(db, line_user_id, "BINDING_EMPLOYEE_ID")
            line_service.reply_text(
                reply_token,
                "👋 歡迎使用劇組報帳系統！\n\n"
                "初次使用請輸入您的【員工編號】完成設定\n"
                "（請向製片組確認您的編號）",
            )
            continue

# --- 路徑 2：原有 Onboarding 流程（enable_roster_binding=False 時）---
elif user.department is None:
    # ... 保留現有邏輯完全不動 ...
```

### 需要新增的 import

```python
from services import roster_service  # 新增
```

### 不得修改

- `_process_batch()` 函式
- `PostbackEvent` 處理區塊
- 查詢進度邏輯（`EXP-` 格式）
- 補件流程（`REUPLOADING_` state）
- `ImageMessageContent` 處理區塊

## 驗收標準

- [ ] `ENABLE_ROSTER_BINDING=true` 時，首次使用者收到「請輸入員工編號」提示
- [ ] 輸入正確員工編號後，`users.real_name` 與 `users.department` 被正確填入
- [ ] 輸入錯誤員工編號後，收到明確錯誤訊息，且可重試（state 仍為 BINDING_EMPLOYEE_ID）
- [ ] 已綁定使用者傳訊息時，直接進入報帳流程（不再問編號）
- [ ] `ENABLE_ROSTER_BINDING=false` 時，現有 Onboarding 流程完全不受影響
- [ ] 批次 OCR、補件、查詢進度等功能正常運作

---

## 事件紀錄

### 2026-04-29T04:03:03.613Z — 建立任務（assigned）
由 L1 透過 /task-delegation 建立
