#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

BACKUP_DIR="$SCRIPT_DIR/backups"
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="vre_${TIMESTAMP}.sql.gz"

echo "Starting database backup..."

docker compose -f docker-compose.prod.yml exec -T postgres \
    pg_dump -U "${DB_USER:-vre_prod}" "${POSTGRES_DB:-vre}" \
    | gzip > "$BACKUP_DIR/$FILENAME"

SIZE=$(ls -lh "$BACKUP_DIR/$FILENAME" | awk '{print $5}')
echo "Backup saved: $BACKUP_DIR/$FILENAME ($SIZE)"

# Keep last 30 backups, remove older ones
REMOVED=$(ls -t "$BACKUP_DIR"/vre_*.sql.gz 2>/dev/null | tail -n +31 | wc -l | tr -d ' ')
ls -t "$BACKUP_DIR"/vre_*.sql.gz 2>/dev/null | tail -n +31 | xargs rm -f 2>/dev/null || true

if [ "$REMOVED" -gt 0 ]; then
    echo "Cleaned up $REMOVED old backup(s)"
fi

echo "Done."
