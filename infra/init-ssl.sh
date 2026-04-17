#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Shadow Pages — SSL initialization via Let's Encrypt
# ─────────────────────────────────────────────────────────────
# Usage: ./init-ssl.sh yourdomain.com [email@domain.com]
#
# Prerequisites:
#   - certbot installed (apt install certbot / brew install certbot)
#   - Port 80 available (stop nginx first if running)
#   - Run as root or with sudo
# ─────────────────────────────────────────────────────────────
set -euo pipefail

DOMAIN="${1:?Usage: ./init-ssl.sh yourdomain.com [email@domain.com]}"
EMAIL="${2:-admin@$DOMAIN}"
COMPOSE_FILE="${3:-/Users/larialexandru/Desktop/aiContent/infra/docker-compose.yml}"

echo "==> SSL init for $DOMAIN (contact: $EMAIL)"

# ── Obtain certificate if missing ───────────────────────────
if [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
    echo "==> Obtaining SSL certificate for $DOMAIN..."

    # Stop nginx temporarily so certbot can bind to port 80
    if docker compose -f "$COMPOSE_FILE" ps nginx --status running -q 2>/dev/null; then
        echo "    Stopping nginx for standalone verification..."
        docker compose -f "$COMPOSE_FILE" stop nginx
        RESTART_NGINX=1
    fi

    certbot certonly \
        --standalone \
        -d "$DOMAIN" \
        --email "$EMAIL" \
        --agree-tos \
        --non-interactive \
        --no-eff-email

    if [ "${RESTART_NGINX:-0}" = "1" ]; then
        echo "    Restarting nginx..."
        docker compose -f "$COMPOSE_FILE" start nginx
    fi

    echo "==> Certificate obtained successfully."
else
    echo "==> Certificate already exists for $DOMAIN. Skipping."
fi

# ── Verify certificate ──────────────────────────────────────
echo "==> Certificate details:"
openssl x509 -in "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" -noout -subject -dates 2>/dev/null || true

# ── Set up auto-renewal cron ────────────────────────────────
CRON_CMD="0 3 * * * certbot renew --quiet --deploy-hook 'docker compose -f $COMPOSE_FILE restart nginx'"

if crontab -l 2>/dev/null | grep -qF "certbot renew"; then
    echo "==> Renewal cron already exists. Skipping."
else
    (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
    echo "==> Added daily renewal cron (runs at 03:00)."
fi

echo "==> SSL ready for $DOMAIN"
