#!/usr/bin/env bash
# AcctAssist 客戶部署安裝腳本（Mac / Linux）
# 使用方式：chmod +x setup.sh && ./setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo ""
echo "========================================"
echo "   AcctAssist 客戶部署安裝程式"
echo "========================================"
echo ""

# ── Step 1: 確認 Docker 已啟動 ────────────────────────────────────
echo "[1/6] 確認 Docker..."
if ! docker info > /dev/null 2>&1; then
    echo ""
    echo "      [ERROR] Docker 未啟動或未安裝"
    echo "      請先安裝並啟動 Docker Desktop："
    echo "        Mac:   https://www.docker.com/products/docker-desktop/"
    echo "        Linux: curl -fsSL https://get.docker.com | sh"
    echo ""
    exit 1
fi
echo "      [OK] Docker 運行中"

# ── Step 2: 確認前端已建置 ────────────────────────────────────────
echo "[2/6] 確認前端檔案..."
if [ ! -f "$PROJECT_ROOT/frontend/dist/index.html" ]; then
    echo "      [WARN] 找不到 frontend/dist/index.html"
    echo "      Dashboard 介面可能無法使用。"
    echo "      （LINE Bot 功能仍正常）"
else
    echo "      [OK] 前端檔案存在"
fi

# ── Step 3: 建立 .env ─────────────────────────────────────────────
echo "[3/6] 設定環境變數..."
ENV_FILE="$SCRIPT_DIR/.env"
TEMPLATE_FILE="$SCRIPT_DIR/.env.template"

if [ ! -f "$ENV_FILE" ]; then
    cp "$TEMPLATE_FILE" "$ENV_FILE"
    echo "      已建立 .env 設定檔"
else
    echo "      .env 已存在，略過複製"
fi

# ── Step 4: 自動產生 JWT_SECRET ───────────────────────────────────
echo "[4/6] 產生 JWT 金鑰..."
if grep -q "WILL_BE_GENERATED_BY_SETUP_SCRIPT" "$ENV_FILE"; then
    JWT_SECRET=$(openssl rand -hex 32)
    # macOS 和 Linux 的 sed -i 語法不同
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/WILL_BE_GENERATED_BY_SETUP_SCRIPT/$JWT_SECRET/" "$ENV_FILE"
    else
        sed -i "s/WILL_BE_GENERATED_BY_SETUP_SCRIPT/$JWT_SECRET/" "$ENV_FILE"
    fi
    echo "      [OK] JWT_SECRET 已自動產生"
else
    echo "      JWT_SECRET 已設定，略過"
fi

# ── Step 5: 引導填寫 API 金鑰 ────────────────────────────────────
echo ""
echo "[5/6] 填寫 API 金鑰"
echo ""
echo "      請在編輯器中填寫以下欄位："
echo "        LINE_CHANNEL_SECRET       ← LINE Bot 頻道密鑰"
echo "        LINE_CHANNEL_ACCESS_TOKEN ← LINE Bot 存取權杖"
echo "        GEMINI_API_KEY            ← Google Gemini API 金鑰"
echo "        POSTGRES_PASSWORD         ← 資料庫密碼（同步修改 DATABASE_URL）"
echo ""
echo "      即將開啟 .env 檔案..."
sleep 2

# 開啟編輯器（優先順序：EDITOR env var → nano → vi）
if [[ "$OSTYPE" == "darwin"* ]]; then
    open -e "$ENV_FILE" && echo "請在 TextEdit 編輯後關閉，再按 Enter 繼續。"
elif command -v nano &> /dev/null; then
    nano "$ENV_FILE"
elif command -v vi &> /dev/null; then
    vi "$ENV_FILE"
else
    echo "請手動編輯 $ENV_FILE，完成後按 Enter 繼續。"
fi

read -r -p "      填寫完成後，按 Enter 繼續..."

# 確認關鍵欄位
MISSING=()
if grep -qE '^LINE_CHANNEL_SECRET=\s*$' "$ENV_FILE"; then MISSING+=("LINE_CHANNEL_SECRET"); fi
if grep -qE '^LINE_CHANNEL_ACCESS_TOKEN=\s*$' "$ENV_FILE"; then MISSING+=("LINE_CHANNEL_ACCESS_TOKEN"); fi
if grep -qE '^GEMINI_API_KEY=\s*$' "$ENV_FILE"; then MISSING+=("GEMINI_API_KEY"); fi

if [ ${#MISSING[@]} -gt 0 ]; then
    echo ""
    echo "      [WARN] 以下欄位尚未填寫："
    for f in "${MISSING[@]}"; do echo "        - $f"; done
    echo ""
    read -r -p "      確定要繼續嗎？(y/N) " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        echo "請填寫後重新執行腳本。"
        exit 0
    fi
fi

# ── Step 6: 啟動 Docker Compose ──────────────────────────────────
echo ""
echo "[6/6] 啟動 AcctAssist 服務..."
echo "      （首次啟動需要建置 Docker image，約需 5-10 分鐘）"
echo ""

cd "$SCRIPT_DIR"
docker compose up -d --build

# ── 等待服務就緒 ─────────────────────────────────────────────────
echo ""
echo "等待服務啟動中..."

MAX_ATTEMPTS=24  # 最多等 120 秒
SUCCESS=false

for i in $(seq 1 $MAX_ATTEMPTS); do
    sleep 5
    STATUS=$(curl -sf http://localhost/health \
        | python3 -c 'import sys,json; print(json.load(sys.stdin)["status"])' 2>/dev/null \
        || echo "error")
    if [ "$STATUS" = "success" ]; then
        SUCCESS=true
        break
    fi
    printf "  等待中... (%d/%d)\r" "$i" "$MAX_ATTEMPTS"
done

echo ""

if $SUCCESS; then
    echo ""
    echo "========================================"
    echo "   AcctAssist 啟動成功！"
    echo "========================================"
    echo ""
    echo "下一步：啟動 Cloudflare Tunnel"
    echo ""
    echo "  執行：./start-tunnel.sh"
    echo ""
    echo "  Tunnel 啟動後，你會看到 https://RANDOM.trycloudflare.com 網址。"
    echo "  將此網址設定到 LINE Developers Console："
    echo "    Webhook URL: https://RANDOM.trycloudflare.com/webhook"
    echo "    LIFF URL:    https://RANDOM.trycloudflare.com/liff-app"
    echo ""
else
    echo ""
    echo "[ERROR] 服務未能在 120 秒內啟動。"
    echo "請執行以下指令查看錯誤訊息："
    echo "  docker compose logs backend --tail 30"
    echo ""
    docker compose logs backend --tail 30
    exit 1
fi
