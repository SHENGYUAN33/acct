"""
AcctAssist — Gemini OCR 獨立測試腳本

使用方式：
    python test_ocr.py --image test_invoice.jpg
    python test_ocr.py --image path/to/receipt.png

前置條件：
    1. 複製 .env.example 為 .env，並填入 GEMINI_API_KEY
    2. pip install -r requirements.txt
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# 修正 Windows ProactorEventLoop 結束時的 SSL 清理錯誤
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 修正 Windows 終端機 cp950 無法顯示 Unicode 字元
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 載入 .env（必須在 import ocr_service 之前，因為 ocr_service 在 import 時就初始化 Gemini client）
from dotenv import load_dotenv

load_dotenv()

# 設定 logging，讓 ocr_service 的錯誤訊息可以顯示
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
)

from services.ocr_service import extract_invoice_data  # noqa: E402


async def run(image_path: Path) -> None:
    if not image_path.exists():
        print(f"[ERROR] 找不到圖片：{image_path}")
        print("請確認圖片路徑正確，或將測試圖片命名為 test_invoice.jpg 放在專案根目錄。")
        sys.exit(1)

    print(f"\n{'='*50}")
    print(f"  圖片路徑：{image_path}")
    print(f"{'='*50}\n")
    print("正在呼叫 Gemini API 解析中…\n")

    result = await extract_invoice_data(image_path)

    # ---- 結構化結果 ----
    extracted = {
        "submitter": result.submitter,
        "item": result.item,
        "invoice_number": result.invoice_number,
        "amount": result.amount,
    }

    print("【解析結果】")
    print(json.dumps(extracted, ensure_ascii=False, indent=2))
    print()

    if result.success:
        print("✅  OCR 成功")
    else:
        print(f"❌  OCR 失敗 — {result.error}")

    print("\n【Gemini 原始回應】")
    print(result.raw_response if result.raw_response else "(無回應)")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="AcctAssist OCR 測試腳本")
    parser.add_argument(
        "--image",
        type=Path,
        default=Path("test_invoice.jpg"),
        help="發票圖片路徑（預設：test_invoice.jpg）",
    )
    args = parser.parse_args()
    asyncio.run(run(args.image))


if __name__ == "__main__":
    main()
