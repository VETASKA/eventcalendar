#!/usr/bin/env bash
# Pull the latest code and restart.   sudo bash /opt/eventcalendar/deploy/update.sh
set -euo pipefail
APP=/opt/eventcalendar
[ "$(id -u)" = 0 ] || { echo "Запустите: sudo bash $0"; exit 1; }
git config --global --add safe.directory "$APP" 2>/dev/null || true
git -C "$APP" pull --ff-only
cd "$APP"
docker compose up -d --build        # the «migrate» service applies migrations before «web» starts
docker compose exec -T web python manage.py seed_reference >/dev/null
echo "   ✓ обновлено до $(git -C "$APP" log -1 --format='%h %s')"
