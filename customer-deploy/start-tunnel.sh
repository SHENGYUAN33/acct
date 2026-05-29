#!/usr/bin/env bash
# AcctAssist — 啟動 Cloudflare Tunnel（Mac / Linux）
# 使用方式：chmod +x start-tunnel.sh && ./start-tunnel.sh
#
# 說明：
#   Cloudflare Quick Tunnel 提供免費的 HTTPS 隧道，無需帳號。
#   LINE Messaging API 需要 HTTPS Webhook，此腳本解決此需求。
#
# ⚠️ 注意：每次重新啟動，Tunnel URL 會改變，需要在 LINE Console 更新 Webhook URL。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "========================================"
echo "   AcctAssist — Cloudflare Tunnel"
echo "========================================"

# ── 確認 AcctAssist 服務正在運行 ────────────────────────────────
echo ""
echo "確認 AcctAssist 服務狀態..."
STATUS=$(curl -sf http://localhost/health \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["status"])' 2>/dev/null \
    || echo "error")

if [ "$STATUS" != "success" ]; then
    echo "[ERROR] AcctAssist 服務未啟動或無法連線"
    echo "請先執行 ./setup.sh 啟動服務。"
    exit 1
fi
echo "[OK] AcctAssist 服務正常運行"

# ── 偵測作業系統與架構 ─────────────────────────────────────────
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
case "$ARCH" in
    x86_64)  ARCH="amd64" ;;
    aarch64) ARCH="arm64" ;;
    arm64)   ARCH="arm64" ;;
    *)
        echo "[ERROR] 不支援的架構：$ARCH"
        exit 1
        ;;
esac

# cloudflared binary 下載路徑
case "$OS" in
    darwin) DOWNLOAD_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-${ARCH}.tgz" ;;
    linux)  DOWNLOAD_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}" ;;
    *)
        echo "[ERROR] 不支援的作業系統：$OS"
        exit 1
        ;;
esac

CLOUDFLARED="$SCRIPT_DIR/cloudflared"

# ── 下載 cloudflared（如果尚未下載）─────────────────────────────
if [ ! -f "$CLOUDFLARED" ]; then
    echo ""
    echo "下載 Cloudflare Tunnel 程式..."

    if [[ "$OS" == "darwin" ]]; then
        # macOS 下載 tgz 並解壓
        TMP_TGZ=$(mktemp /tmp/cloudflared.XXXXXX.tgz)
        curl -fsSL -o "$TMP_TGZ" "$DOWNLOAD_URL"
        tar -xzf "$TMP_TGZ" -C "$SCRIPT_DIR" cloudflared
        rm -f "$TMP_TGZ"
    else
        # Linux 直接下載 binary
        curl -fsSL -o "$CLOUDFLARED" "$DOWNLOAD_URL"
    fi

    chmod +x "$CLOUDFLARED"
    echo "[OK] 下載完成"
fi

# ── 啟動 Tunnel ──────────────────────────────────────────────────
echo ""
echo "========================================================"
echo "啟動 Cloudflare Quick Tunnel..."
echo ""
echo "Tunnel URL 即將顯示（格式：https://RANDOM.trycloudflare.com）"
echo ""
echo "請將 URL 設定到 LINE Developers Console："
echo "  Webhook URL : https://XXXXX.trycloudflare.com/webhook"
echo "  LIFF URL    : https://XXXXX.trycloudflare.com/liff-app"
echo ""
echo "⚠️  每次重啟 Tunnel，URL 會改變，需重新設定 LINE Console。"
echo "========================================================"
echo ""
echo "按 Ctrl+C 停止 Tunnel。"
echo ""

exec "$CLOUDFLARED" tunnel --url http://localhost:80
