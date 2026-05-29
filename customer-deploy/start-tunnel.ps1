# AcctAssist — 啟動 Cloudflare Tunnel（Windows）
# 使用方式：在 customer-deploy\ 資料夾內執行此腳本
#
# 說明：
#   Cloudflare Quick Tunnel 提供免費的 HTTPS 隧道，無需帳號。
#   LINE Messaging API 需要 HTTPS Webhook，此腳本解決此需求。
#
# ⚠️ 注意：每次重新啟動，Tunnel URL 會改變，需要在 LINE Console 更新 Webhook URL。

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   AcctAssist — Cloudflare Tunnel" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# ── 確認 AcctAssist 服務正在運行 ──────────────────────────────────
Write-Host ""
Write-Host "確認 AcctAssist 服務狀態..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://localhost/health" -TimeoutSec 5 -ErrorAction Stop
    if ($response.status -eq "success") {
        Write-Host "[OK] AcctAssist 服務正常運行" -ForegroundColor Green
    } else {
        throw "Status: $($response.status)"
    }
} catch {
    Write-Host "[ERROR] AcctAssist 服務未啟動或無法連線" -ForegroundColor Red
    Write-Host "請先執行 setup.ps1 啟動服務。"
    Read-Host "Press Enter to exit"
    exit 1
}

# ── 下載 cloudflared（如果尚未下載）───────────────────────────────
$cloudflaredPath = Join-Path $scriptDir "cloudflared.exe"

if (-not (Test-Path $cloudflaredPath)) {
    Write-Host ""
    Write-Host "下載 Cloudflare Tunnel 程式..." -ForegroundColor Yellow
    $downloadUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    try {
        Invoke-WebRequest -Uri $downloadUrl -OutFile $cloudflaredPath -UseBasicParsing
        Write-Host "[OK] 下載完成" -ForegroundColor Green
    } catch {
        Write-Host "[ERROR] 下載失敗，請手動下載：" -ForegroundColor Red
        Write-Host "  $downloadUrl"
        Write-Host "  儲存為 cloudflared.exe 在 customer-deploy\ 資料夾內"
        Read-Host "Press Enter to exit"
        exit 1
    }
}

# ── 啟動 Tunnel ───────────────────────────────────────────────────
Write-Host ""
Write-Host "========================================================"
Write-Host "啟動 Cloudflare Quick Tunnel..."
Write-Host ""
Write-Host "Tunnel URL 即將顯示（格式：https://RANDOM.trycloudflare.com）"
Write-Host ""
Write-Host "請將 URL 設定到 LINE Developers Console："
Write-Host "  Webhook URL : https://XXXXX.trycloudflare.com/webhook"
Write-Host "  LIFF URL    : https://XXXXX.trycloudflare.com/liff-app"
Write-Host ""
Write-Host "⚠️  每次重啟 Tunnel，URL 會改變，需重新設定 LINE Console。"
Write-Host "========================================================"
Write-Host ""
Write-Host "按 Ctrl+C 停止 Tunnel。"
Write-Host ""

& $cloudflaredPath tunnel --url http://localhost:80
