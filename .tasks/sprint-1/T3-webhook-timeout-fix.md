# Webhook 超時修正

| 欄位 | 值 |
|------|-----|
| ID | T3 |
| 專案 | AcctAssist |
| Sprint | Sprint 1 |
| 指派給 | backend-dev |
| 優先級 | P0 |
| 狀態 | assigned |
| 依賴 | — |
| 預估 | 0.5d |
| 建立時間 | 2026-04-10T03:09:26.113Z |

---

## 任務描述

改用 FastAPI `BackgroundTasks` 處理圖片事件，新增 `push_message` 推送功能，解決 Postmortem #003 LINE Webhook 超時問題。

**修改檔案**：
- `routers/webhook.py`：加入 BackgroundTasks，圖片事件改為後台處理
- `services/line_service.py`：新增 `push_message` / `push_reject_notification` 方法
- `core/config.py`：新增 `LINE_CHANNEL_ACCESS_TOKEN` 設定項
- `.env.example`：新增 `LINE_CHANNEL_ACCESS_TOKEN` key

**技術方案**：
```python
@router.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # 驗證 + 解析（< 20ms）
    background_tasks.add_task(process_image_event, event, db_session)
    return Response(status_code=200)  # 立即回應
```

⚠️ `push_message` 需包 try-except，失敗 log 但不中斷流程

## 驗收標準

- [ ] Webhook 收到圖片後 < 500ms 回應 200
- [ ] OCR 完成後透過 `push_message` 推送辨識摘要給使用者
- [ ] `LINE_CHANNEL_ACCESS_TOKEN` 已加入 `core/config.py` 與 `.env.example`
- [ ] `push_message` 失敗時 log error 但不影響主流程
- [ ] 不破壞原有 TextMessage / QuickReply 流程

---

## 事件紀錄

### 2026-04-10T03:09:26.113Z — 建立任務（assigned）
由 L1 透過 /task-delegation 建立
