# EventCalendar

Public event catalogue (first storefront: **eventcalendar.com.ua**). One database, several sites on top of it.
Events come from Harvey (`VETASKA/findclients-rte`), visitors and organizers; every first publication is moderated.

Full spec: [docs/technical-spec.md](docs/technical-spec.md) · Harvey contract: [docs/intake-api.md](docs/intake-api.md)

## Status

| Stage (spec §9) | State |
| --- | --- |
| 1. Skeleton and data | **done**: models, migrations, KATOTTG importer, intake API from Harvey, moderation queue in admin |
| 2. Public catalogue (calendar, filters, uk/en/pl) | next |
| 3. Submission form + parser queue | — |
| 4. Organizer cabinet | tables only |
| 5. Telegram / email | tables only |
| 6. VPS / second domain | deploy scripts ready, second-site check pending |

## Stack

Python 3.12, Django 5.2 LTS, PostgreSQL 16, Celery + Redis, gunicorn + WhiteNoise, Docker Compose.
Runs on the Harvey server behind its Caddy (domain file in `/etc/caddy/conf.d/`).

```
apps/portals        Site + domains (request.site by Host)
apps/geo            Country / Region / City / CityAlias, KATOTTG import
apps/catalog        Event, Occurrence, Topic, EventType, SitePublication, EventRevision; moderation admin
apps/intake         EventSource, IntakeItem, POST /api/v1/intake/events, Harvey adapter
apps/organizers     Organization, Membership, Claim, EventGrant (stage 4)
apps/subscriptions  Subscription, Reminder, Announcement, Delivery (stage 5)
apps/audit          AuditLog
```

## Local run

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
export DJANGO_DEBUG=1 DATABASE_URL=postgres://user:pass@localhost:5432/eventcalendar
python manage.py migrate && python manage.py seed_reference && python manage.py createsuperuser
python manage.py runserver            # http://localhost:8000/admin/
python -m pytest                      # needs the same PostgreSQL
```

## Server (same VPS as Harvey)

```bash
sudo git clone https://github.com/VETASKA/eventcalendar.git /opt/eventcalendar
sudo bash /opt/eventcalendar/deploy/install.sh     # Docker, .env with secrets, Caddy, Harvey token, backups
sudo bash /opt/eventcalendar/deploy/update.sh      # later updates
```

The installer writes `CALENDAR_URL` / `CALENDAR_TOKEN` into `/opt/harvey/.env`. Then, once:

```bash
cd /opt/harvey && sudo -u harvey .venv/bin/harvey calendar push --all   # first full upload, no announcements
sudo -u harvey .venv/bin/harvey calendar status
```

Moderation: `https://eventcalendar.com.ua/admin/catalog/event/` — filter by «що перевірити», source, country,
Ukraine signals; fill in format and type; «Схвалити вибрані» publishes valid ones and lists the rest with reasons.

## Cities

`seed_reference` adds the main Ukrainian cities (with Harvey's spellings as aliases) so the import works right away.
For the full list download the КАТОТТГ XLSX from the Ministry
([mininfra.gov.ua](https://mininfra.gov.ua/diialnist/rozvytok-mistsevoho-samovriaduvannia/kodyfikator-administratyvno-terytorialnykh-odynyts-ta-terytorii-terytorialnykh-hromad)) and run

```bash
docker compose exec web python manage.py import_katottg /app/kodyfikator.xlsx --version 2026-xx-xx
```

Re-import keeps internal IDs; places missing from a new snapshot are deactivated, not deleted.

## Backups

`/usr/local/bin/eventcalendar-backup` runs nightly (cron) → `/var/backups/eventcalendar`, 14 days.
An off-server copy is not set up yet (see the commented `rclone` line in `deploy/backup.sh`).
