# AcctAssist 客戶部署安裝腳本（Windows）
# 使用方式：在 customer-deploy\ 資料夾內，右鍵 → 以 PowerShell 執行
#           或：powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   AcctAssist 客戶部署安裝程式" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: 確認 Docker Desktop 已啟動 ─────────────────────────────
Write-Host "[1/6] 確認 Docker Desktop..." -ForegroundColor Yellow
try {
    $null = docker info 2>&1
    Write-Host "      [OK] Docker Desktop 運行中" -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "      [ERROR] Docker Desktop 未啟動或未安裝" -ForegroundColor Red
    Write-Host "      請先安裝並啟動 Docker Desktop：https://www.docker.com/products/docker-desktop/"
    Write-Host "      啟動後重新執行此腳本。"
    Read-Host "Press Enter to exit"
    exit 1
}

# ── Step 2: 確認前端已建置 ─────────────────────────────────────────
Write-Host "[2/6] 確認前端檔案..." -ForegroundColor Yellow
$distIndex = Join-Path $projectRoot "frontend\dist\index.html"
if (-not (Test-Path $distIndex)) {
    Write-Host ""
    Write-Host "      [WARN] 找不到 frontend\dist\index.html" -ForegroundColor Yellow
    Write-Host "      Dashboard 介面可能無法使用。"
    Write-Host "      （LINE Bot 功能仍正常，可稍後執行 npm run build 修復）"
    Write-Host ""
} else {
    Write-Host "      [OK] 前端檔案存在" -ForegroundColor Green
}

# ── Step 3: 建立 .env（如果不存在）────────────────────────────────
Write-Host "[3/6] 設定環境變數..." -ForegroundColor Yellow
$envFile = Join-Path $scriptDir ".env"
$templateFile = Join-Path $scriptDir ".env.template"

if (-not (Test-Path $envFile)) {
    Copy-Item $templateFile $envFile
    Write-Host "      已建立 .env 設定檔" -ForegroundColor Green
} else {
    Write-Host "      .env 已存在，略過複製" -ForegroundColor Green
}

# ── Step 4: 自動產生 JWT_SECRET ────────────────────────────────────
Write-Host "[4/6] 產生 JWT 金鑰..." -ForegroundColor Yellow
$envContent = Get-Content $envFile -Raw

if ($envContent -match "WILL_BE_GENERATED_BY_SETUP_SCRIPT") {
    $bytes = [byte[]]::new(32)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    $jwtSecret = ($bytes | ForEach-Object { '{0:x2}' -f $_ }) -join ''
    $envContent = $envContent -replace "WILL_BE_GENERATED_BY_SETUP_SCRIPT", $jwtSecret
    [System.IO.File]::WriteAllText($envFile, $envContent, [System.Text.Encoding]::UTF8)
    Write-Host "      [OK] JWT_SECRET 已自動產生" -ForegroundColor Green
} else {
    Write-Host "      JWT_SECRET 已設定，略過" -ForegroundColor Green
}

# ── Step 5: 引導填寫 API 金鑰 ──────────────────────────────────────
Write-Host ""
Write-Host "[5/6] 填寫 API 金鑰" -ForegroundColor Yellow
Write-Host ""
Write-Host "      請在開啟的記事本中填寫以下欄位：" -ForegroundColor White
Write-Host "        LINE_CHANNEL_SECRET      ← LINE Bot 頻道密鑰" -ForegroundColor White
Write-Host "        LINE_CHANNEL_ACCESS_TOKEN ← LINE Bot 存取權杖" -ForegroundColor White
Write-Host "        GEMINI_API_KEY           ← Google Gemini API 金鑰" -ForegroundColor White
Write-Host "        POSTGRES_PASSWORD        ← 資料庫密碼（同步修改 DATABASE_URL）" -ForegroundColor White
Write-Host ""
Write-Host "      填寫完成後，儲存並關閉記事本，再按 Enter 繼續。" -ForegroundColor Yellow
Write-Host ""

Start-Process notepad.exe -ArgumentList $envFile -Wait

# 確認關鍵欄位已填寫
$envContent = Get-Content $envFile -Raw
$missingFields = @()
if ($envContent -match "LINE_CHANNEL_SECRET=\s*$") { $missingFields += "LINE_CHANNEL_SECRET" }
if ($envContent -match "LINE_CHANNEL_ACCESS_TOKEN=\s*$") { $missingFields += "LINE_CHANNEL_ACCESS_TOKEN" }
if ($envContent -match "GEMINI_API_KEY=\s*$") { $missingFields += "GEMINI_API_KEY" }

if ($missingFields.Count -gt 0) {
    Write-Host ""
    Write-Host "      [WARN] 以下欄位尚未填寫：" -ForegroundColor Yellow
    $missingFields | ForEach-Object { Write-Host "        - $_" -ForegroundColor Yellow }
    $confirm = Read-Host "      確定要繼續嗎？（填入後系統才能正常運作）(y/N)"
    if ($confirm -ne 'y' -and $confirm -ne 'Y') {
        Write-Host "請填寫後重新執行腳本。"
        exit 0
    }
}

# ── Step 6: 啟動 Docker Compose ────────────────────────────────────
Write-Host ""
Write-Host "[6/6] 啟動 AcctAssist 服務..." -ForegroundColor Yellow
Write-Host "      （首次啟動需要建置 Docker image，約需 5-10 分鐘）"
Write-Host ""

Set-Location $scriptDir
docker compose up -d --build

# ── 等待服務就緒 ──────────────────────────────────────────────────
Write-Host ""
Write-Host "等待服務啟動中..." -ForegroundColor Yellow

$maxAttempts = 24  # 最多等 120 秒
$success = $false

for ($i = 1; $i -le $maxAttempts; $i++) {
    Start-Sleep -Seconds 5
    try {
        $response = Invoke-RestMethod -Uri "http://localhost/health" -TimeoutSec 3 -ErrorAction Stop
        if ($response.status -eq "success") {
            $success = $true
            break
        }
    } catch { }
    Write-Host "  等待中... ($i/$maxAttempts)" -NoNewline
    Write-Host "`r" -NoNewline
}

Write-Host ""

if ($success) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "   AcctAssist 啟動成功！" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "下一步：啟動 Cloudflare Tunnel" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  執行：.\start-tunnel.ps1"
    Write-Host ""
    Write-Host "  Tunnel 啟動後，你會看到一個 https://RANDOM.trycloudflare.com 網址。"
    Write-Host "  將此網址設定到 LINE Developers Console："
    Write-Host "    Webhook URL: https://RANDOM.trycloudflare.com/webhook"
    Write-Host "    LIFF URL:    https://RANDOM.trycloudflare.com/liff-app"
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "[ERROR] 服務未能在 120 秒內啟動。" -ForegroundColor Red
    Write-Host "請執行以下指令查看錯誤訊息："
    Write-Host "  docker compose logs backend --tail 30"
    Write-Host ""
    docker compose logs backend --tail 30
}

Read-Host "按 Enter 結束"
