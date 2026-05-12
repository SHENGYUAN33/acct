#!/usr/bin/env python3
"""
一次性腳本：更新 LINE Rich Menu 為 Sprint 2 單按鈕版本。
使用方式：python scripts/setup_rich_menu.py
"""
import asyncio
import sys
from pathlib import Path

# 讓 script 能 import 上層模組
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import settings  # noqa: F401（確認 settings 可正常載入）
from services.line_service import setup_rich_menu


async def main() -> None:
    # setup_rich_menu 為同步函式，直接呼叫即可
    rich_menu_id = setup_rich_menu()
    print(f"✅ Rich Menu 設定完成，rich_menu_id={rich_menu_id}")


if __name__ == "__main__":
    asyncio.run(main())
