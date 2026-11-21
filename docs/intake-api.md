# Intake API — how Harvey (and later other sources) send events

`POST /api/v1/intake/events` · schema version **1**

Harvey (repo `VETASKA/findclients-rte`, file `harvey/calendar_push.py`) pushes every new or changed event here.
Both run on the same server, so Harvey calls `http://127.0.0.1:8100` directly.

## Auth

`Authorization: Bearer ec_…` — one token per source, issued by
`python manage.py create_source harvey` (shown once, only its sha256 is stored; `--rotate` replaces it).

## Request

```json
{
  "schema": 1,
  "initial_load": false,
  "items": [
    {
      "external_id": "123",
      "url": "https://forum.com.ua/",
      "domain": "forum.com.ua",
      "name": "Форум підприємців",
      "kind": "event",
      "kind_why": "є: що за подія, дата, реєстрація",
      "removed": false,
      "country": "UA",
      "city": "Киев",
      "date": "2027-03-14",
      "date_text": "14 березня 2027",
      "price_text": "500 грн",
      "ticket_provider": "regtoevent",
      "registration_url": "https://…",
      "organizer": {"name": "Агенція", "website": "https://agency.ua"},
      "signals": {"ua_phone": true, "tld": "ua"},
      "updated_at": "2026-11-21 10:00:00"
    }
  ]
}
```

* At most `INTAKE_MAX_BATCH` (200) items per request.
* `external_id` is required and stable (Harvey's `events.id`). Everything else may be empty.
* `kind`: `event` → `event_detected`, `maybe` → `needs_review`, `not_event` / `junk` → `not_event`.
* `removed: true` (or `kind` turning into junk) after an event was sent: the event left the source.
  A draft is withdrawn; a published card gets a priority proposal for the moderator — never auto-removed.
* `initial_load: true` marks the first full upload: those events are published without a «new event» announcement.
* `city` is matched against `CityAlias` (Harvey's Russian names are seeded as aliases). Unknown or ambiguous → moderator.
* No contact data is sent: phones only become the `ua_phone` signal.

## Response

```json
{"schema": 1, "results": [
  {"external_id": "123", "result": "created", "status": "event_detected", "event_id": 41}
]}
```

`result`: `created` | `updated` | `unchanged` | `error` (with `error`). One bad item never fails the batch.
`unchanged` = same payload as last time (only `updated_at` / `sent_at` / `scanned_at` differ).

Status codes: `200`, `400` (bad JSON / schema), `401` (token), `405`, `413` (batch too big).

## Guarantees

* Redelivery and parallel delivery of the same item never create a second card: one `IntakeItem`
  per `(source, external_id)`, row-locked while processed (test: `test_parallel_delivery_creates_one_card`).
* Same normalised URL from the same source links to the existing card.
* Before the first approval the import updates the draft, except fields a moderator changed by hand
  (`Event.manual_fields`). After approval the import only proposes an `EventRevision`.
* A rejected card or a publication taken down by a moderator stays so on re-import.

## Harvey side

* SQLite triggers on `events`, `organizers`, `organizer_contacts` put the event id into `calendar_outbox`.
* The panel process (`harvey-panel`) sends the queue every minute; failures back off 1, 2, 4 … 360 min.
* Nothing is sent until `harvey calendar push --all` (the first full upload) has run.
* `harvey calendar status` shows the URL, counts and the last error.
