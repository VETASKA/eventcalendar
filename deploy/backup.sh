#!/usr/bin/env bash
# Nightly PostgreSQL dump. Copies older than 14 days are removed.
# Restore: gunzip -c FILE.sql.gz | docker compose -f /opt/eventcalendar/docker-compose.yml exec -T db psql -U eventcalendar eventcalendar
set -euo pipefail
APP=/opt/eventcalendar
DIR=/var/backups/eventcalendar
mkdir -p "$DIR" && chmod 700 "$DIR"
F="$DIR/eventcalendar-$(date +%Y%m%d-%H%M).sql.gz"
docker compose -f "$APP/docker-compose.yml" exec -T db pg_dump -U eventcalendar --clean --if-exists eventcalendar | gzip > "$F"
[ -s "$F" ] || { echo "backup is empty"; rm -f "$F"; exit 1; }
find "$DIR" -name 'eventcalendar-*.sql.gz' -mtime +14 -delete
# Off-server copy (spec §8): uncomment and set a remote, e.g. rclone to object storage
# rclone copy "$F" remote:eventcalendar-backups/
echo "ok $F"
