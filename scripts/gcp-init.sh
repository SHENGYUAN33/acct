#!/usr/bin/env bash
# AcctAssist — GCP Compute Engine VM 一次性初始化腳本
# 在全新的 Ubuntu 22.04 LTS VM 上執行（以 ubuntu 使用者身份）
#
# 使用方式：
#   chmod +x gcp-init.sh
#   sudo ./gcp-init.sh YOUR_DOMAIN YOUR_EMAIL
#
# 前提：
#   1. VM 已建立，100GB 資料磁碟已掛載為 /dev/sdb
#   2. 靜態 IP 已設定，DNS A record 已指向此 IP
#   3. 防火牆已開放 80 / 443

set -euo pipefail

DOMAIN="${1:?Usage: gcp-init.sh DOMAIN EMAIL}"
EMAIL="${2:?Usage: gcp-init.sh DOMAIN EMAIL}"

echo "=== AcctAssist VM 初始化 ==="
echo "Domain: $DOMAIN"
echo "Email:  $EMAIL"
echo ""

# ── 1. 系統更新 ──────────────────────────────────────────────────────
echo "[1/9] 系統更新..."
apt-get update -qq && apt-get upgrade -y -qq

# ── 2. 安裝 Docker ───────────────────────────────────────────────────
echo "[2/9] 安裝 Docker..."
curl -fsSL https://get.docker.com | sh
usermod -aG docker ubuntu
systemctl enable --now docker

# ── 3. 安裝 Nginx + Certbot ──────────────────────────────────────────
echo "[3/9] 安裝 Nginx + Certbot..."
apt-get install -y -qq nginx certbot python3-certbot-nginx

# ── 4. 安裝 gcloud CLI ───────────────────────────────────────────────
echo "[4/9] 安裝 gcloud CLI..."
snap install google-cloud-cli --classic

# ── 5. 格式化並掛載資料磁碟 ─────────────────────────────────────────
echo "[5/9] 設定資料磁碟 /dev/sdb → /data..."
if ! blkid /dev/sdb | grep -q ext4; then
    mkfs.ext4 -F /dev/sdb
fi
mkdir -p /data
mount /dev/sdb /data || true

# fstab 自動掛載（開機後仍掛載）
if ! grep -q '/dev/sdb' /etc/fstab; then
    echo '/dev/sdb /data ext4 defaults 0 2' >> /etc/fstab
fi

# ── 6. 建立目錄結構 ──────────────────────────────────────────────────
echo "[6/9] 建立目錄..."
mkdir -p /data/postgres /data/uploads /var/www/acctassist /opt/acctassist/nginx
chown -R ubuntu:ubuntu /data /var/www/acctassist /opt/acctassist

# ── 7. 設定 Nginx（先用 HTTP only，Certbot 會升級為 HTTPS）─────────
echo "[7/9] 設定 Nginx..."
# 等 CI/CD 把 nginx.conf 複製過來後再執行此步，或手動複製
# 範例：先設定臨時 Nginx 站台以通過 Certbot 驗證
cat > /etc/nginx/sites-available/acctassist << NGINXEOF
server {
    listen 80;
    server_name ${DOMAIN};
    root /var/www/acctassist;
    index index.html;
    location / {
        return 200 'AcctAssist initializing...';
    }
}
NGINXEOF
ln -sf /etc/nginx/sites-available/acctassist /etc/nginx/sites-enabled/acctassist
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

# ── 8. 申請 SSL 憑證 ─────────────────────────────────────────────────
echo "[8/9] 申請 Let's Encrypt SSL..."
certbot --nginx \
    -d "$DOMAIN" \
    --email "$EMAIL" \
    --agree-tos \
    --non-interactive \
    --redirect

# 啟用自動更新
systemctl enable --now certbot.timer
certbot renew --dry-run

# ── 9. 設定 Docker 認證 Artifact Registry ───────────────────────────
echo "[9/9] 設定 Docker 認證 Artifact Registry..."
echo "請執行：gcloud auth configure-docker asia-east1-docker.pkg.dev --quiet"
echo "（需以 ubuntu 使用者重新登入後再執行，因為 docker group 需要重新登入生效）"

echo ""
echo "=== VM 初始化完成 ==="
echo ""
echo "下一步："
echo "  1. 重新登入 VM（讓 docker group 生效）"
echo "  2. 執行：gcloud auth configure-docker asia-east1-docker.pkg.dev --quiet"
echo "  3. 將 .env.production.example 複製為 .env.production，填入真實值"
echo "  4. 執行：gcloud secrets create acctassist-env-production --data-file=.env.production"
echo "  5. 設定 GitHub Secrets（GCP_PROJECT_ID, GCP_SA_KEY, VITE_API_BASE_URL 等）"
echo "  6. Push 到 main branch 觸發 CI/CD"
echo "  7. 在 LINE Developers Console 設定 Webhook URL: https://${DOMAIN}/webhook"
