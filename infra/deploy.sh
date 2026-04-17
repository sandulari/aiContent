#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Shadow Pages Production Deploy ==="
echo ""

# ── Check .env exists ────────────────────────────────────────
if [ ! -f "../.env" ]; then
    echo "ERROR: ../.env not found."
    echo "  Copy .env.production.template to ../.env and fill in values."
    exit 1
fi

# ── Check required variables ─────────────────────────────────
MISSING=0
for var in JWT_SECRET DB_PASSWORD MINIO_SECRET_KEY MINIO_ACCESS_KEY REDIS_PASSWORD; do
    val=$(grep "^${var}=" ../.env | cut -d= -f2- || true)
    if [ -z "$val" ] || [ "$val" = "change-me" ]; then
        echo "ERROR: $var is not set in .env"
        MISSING=1
    fi
done

if [ "$MISSING" -eq 1 ]; then
    echo ""
    echo "Fix the above variables before deploying."
    exit 1
fi

# ── Generate Flower htpasswd ─────────────────────────────────
FLOWER_PW=$(grep "^FLOWER_PASSWORD=" ../.env | cut -d= -f2- || true)
if [ -n "$FLOWER_PW" ]; then
    mkdir -p nginx
    docker run --rm httpd:alpine htpasswd -bn admin "$FLOWER_PW" > nginx/.htpasswd
    echo "[ok] Generated Flower htpasswd auth"
else
    echo "[warn] FLOWER_PASSWORD not set — Flower will have no auth via nginx"
fi

# ── Create backup directory ──────────────────────────────────
mkdir -p backups

# ── Build all images ─────────────────────────────────────────
echo ""
echo "Building images..."
docker compose -f docker-compose.prod.yml build

# ── Deploy ───────────────────────────────────────────────────
echo ""
echo "Deploying..."
docker compose -f docker-compose.prod.yml up -d

# ── Wait and verify ──────────────────────────────────────────
echo ""
echo "Waiting for services to start..."
sleep 10

echo ""
echo "=== Service Status ==="
docker compose -f docker-compose.prod.yml ps
echo ""

# ── Quick health check ───────────────────────────────────────
NGINX_OK=$(docker compose -f docker-compose.prod.yml exec -T nginx curl -sf http://localhost:80/health 2>/dev/null && echo "ok" || echo "fail")
echo "nginx health: $NGINX_OK"

echo ""
echo "=== Deploy complete ==="
