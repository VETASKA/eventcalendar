#!/usr/bin/env bash
# EventCalendar — first-time setup on the Harvey server (Ubuntu 22.04 / 24.04).
#
#   sudo git clone git@github.com:VETASKA/eventcalendar.git /opt/eventcalendar
#   sudo bash /opt/eventcalendar/deploy/install.sh
#
# Asks for: the site domain and a login for the moderation admin.
# Sets up: Docker, the app (PostgreSQL, Redis, web, worker, beat) in Docker Compose,
# the domain in the existing Caddy (a separate file, so Harvey's installer never wipes it),
# a token for Harvey written into /opt/harvey/.env, a nightly database backup. Safe to run again.
set -euo pipefail

APP=/opt/eventcalendar
HARVEY=/opt/harvey
CONF=/etc/eventcalendar/install.env

say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   ✓ %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31m!! %s\033[0m\n' "$*"; exit 1; }

[ "$(id -u)" = 0 ] || fail "Запустите от root: sudo bash $0"
[ -f "$APP/docker-compose.yml" ] || fail "Не найден код в $APP (сначала git clone)."
cd "$APP"

# ── Questions ────────────────────────────────────────────────────────────
mkdir -p /etc/eventcalendar && chmod 700 /etc/eventcalendar
[ -f "$CONF" ] && . "$CONF"
if [ -z "${DOMAIN:-}" ]; then
  read -rp "Домен сайта [eventcalendar.com.ua]: " DOMAIN; DOMAIN=${DOMAIN:-eventcalendar.com.ua}
fi
DOMAIN=$(echo "$DOMAIN" | sed -E 's#^https?://##; s#/.*$##' | tr 'A-Z' 'a-z')
echo "DOMAIN=$DOMAIN" > "$CONF"

# ── Docker ───────────────────────────────────────────────────────────────
say "Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh >/dev/null
fi
docker compose version >/dev/null 2>&1 || fail "Нет docker compose (плагин). Установите docker-compose-plugin."
ok "$(docker --version)"

# ── .env with generated secrets (kept if it already exists) ──────────────
say "Настройки"
if [ ! -f .env ]; then
  SK=$(openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-60)
  PW=$(openssl rand -hex 24)
  sed -e "s#^DJANGO_SECRET_KEY=.*#DJANGO_SECRET_KEY=$SK#" \
      -e "s#^POSTGRES_PASSWORD=.*#POSTGRES_PASSWORD=$PW#" \
      -e "s#^DATABASE_URL=.*#DATABASE_URL=postgres://eventcalendar:$PW@db:5432/eventcalendar#" \
      -e "s#^DJANGO_ALLOWED_HOSTS=.*#DJANGO_ALLOWED_HOSTS=$DOMAIN,www.$DOMAIN,127.0.0.1,localhost#" \
      -e "s#^DJANGO_CSRF_TRUSTED_ORIGINS=.*#DJANGO_CSRF_TRUSTED_ORIGINS=https://$DOMAIN,https://www.$DOMAIN#" \
      .env.example > .env
  chmod 600 .env
  ok ".env создан (секреты сгенерированы)"
else
  ok ".env уже есть — не трогаю"
fi
PORT=$(grep -E '^WEB_PORT=' .env | cut -d= -f2); PORT=${PORT:-8100}

# ── Start ────────────────────────────────────────────────────────────────
say "Запуск (первый раз собирается пару минут)"
docker compose up -d --build
for i in $(seq 1 60); do
  curl -fs "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && break
  sleep 2
done
curl -fs "http://127.0.0.1:$PORT/healthz" >/dev/null || fail "Сайт не ответил. Логи: docker compose -f $APP/docker-compose.yml logs web"
ok "работает на 127.0.0.1:$PORT"

MANAGE="docker compose exec -T web python manage.py"
$MANAGE seed_reference --domain "$DOMAIN" --domain "www.$DOMAIN" >/dev/null
ok "справочники и сайт $DOMAIN"

if ! $MANAGE shell -c "from django.contrib.auth import get_user_model as g; exit(0 if g().objects.filter(is_superuser=True).exists() else 1)"; then
  say "Администратор модерации"
  docker compose exec web python manage.py createsuperuser
fi

# ── Caddy: own file + one import line in the Caddyfile ───────────────────
say "Caddy (HTTPS для $DOMAIN)"
command -v caddy >/dev/null || fail "Caddy не найден (его ставит установщик Харви)."
mkdir -p /etc/caddy/conf.d
cat > /etc/caddy/conf.d/eventcalendar.caddy <<EOF
$DOMAIN, www.$DOMAIN {
	encode gzip
	@www host www.$DOMAIN
	redir @www https://$DOMAIN{uri} permanent
	reverse_proxy 127.0.0.1:$PORT
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "strict-origin-when-cross-origin"
		-Server
	}
}
EOF
CF=/etc/caddy/Caddyfile
if ! grep -q '^import /etc/caddy/conf.d/\*.caddy' "$CF"; then
  cp "$CF" "$CF.bak-$(date +%Y%m%d%H%M%S)"
  printf '\nimport /etc/caddy/conf.d/*.caddy\n' >> "$CF"
fi
caddy validate --config "$CF" >/dev/null 2>&1 || fail "Ошибка в настройке Caddy (caddy validate --config $CF)"
systemctl reload caddy
ok "https://$DOMAIN (сертификат выпустится сам, когда DNS укажет на этот сервер)"

# ── Harvey: token for pushing events ─────────────────────────────────────
say "Связь с Харви"
if [ -f "$HARVEY/.env" ] && ! grep -q '^CALENDAR_TOKEN=' "$HARVEY/.env"; then
  TOKEN=$($MANAGE create_source harvey --name "Харві" | tail -1)
  case "$TOKEN" in ec_*) ;; *) fail "Не удалось выдать токен: $TOKEN";; esac
  printf '\n# EventCalendar: Harvey sends events here\nCALENDAR_URL=http://127.0.0.1:%s\nCALENDAR_TOKEN=%s\n' "$PORT" "$TOKEN" >> "$HARVEY/.env"
  systemctl restart harvey-panel 2>/dev/null || true
  ok "токен записан в $HARVEY/.env, панель Харви перезапущена"
  echo "   Первичная выгрузка всех событий:  sudo -u harvey $HARVEY/.venv/bin/harvey calendar push --all"
elif [ -f "$HARVEY/.env" ]; then
  ok "токен уже есть в $HARVEY/.env"
else
  echo "   Харви не найден в $HARVEY. Токен:  docker compose -f $APP/docker-compose.yml exec web python manage.py create_source harvey"
fi

# ── Nightly backup ───────────────────────────────────────────────────────
say "Резервные копии"
install -m 755 "$APP/deploy/backup.sh" /usr/local/bin/eventcalendar-backup
echo "17 3 * * * root /usr/local/bin/eventcalendar-backup >/var/log/eventcalendar-backup.log 2>&1" > /etc/cron.d/eventcalendar-backup
ok "каждую ночь в /var/backups/eventcalendar (храним 14 дней). Копию вне сервера нужно настроить отдельно."

say "Готово: https://$DOMAIN/admin/"
