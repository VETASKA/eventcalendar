"""«Запропонувати подію» → the same normalized record as an import.

Step 1 (just received): status «queued», no card yet; a background task fetches and reads the page.
Step 2 (page read): the parsed data plus the visitor's hints (date, city, category) make the card for moderation.
Not an event → «not_event», no card. The site did not answer after all retries → a card from the hints only.
"""
from __future__ import annotations

from datetime import date
from urllib.parse import urlsplit

from apps.core.text import norm_url
from apps.geo.services import resolve_city


def normalize(p: dict) -> dict:
    url = (p.get("url") or "").strip()
    key = norm_url(url)
    fetch = p.get("fetch") or {}
    parsed = p.get("parsed") or {}
    if not parsed and not fetch:
        return {"status": "queued", "reason": "чекає на завантаження сторінки", "removed": False, "flags": [],
                "normalized_url": key, "event": {}, "occurrences": []}

    if fetch.get("permanent"):
        return {"status": "not_event", "reason": f"сторінка недоступна: {fetch.get('error', '')}"[:500],
                "removed": False, "flags": [], "normalized_url": key, "event": {}, "occurrences": []}
    kind = parsed.get("kind") or ("maybe" if fetch.get("gave_up") else "no")
    if kind == "no":
        return {"status": "not_event", "reason": "на сторінці не знайдено події (дати / розмітки)", "removed": False,
                "flags": [], "normalized_url": key, "event": {}, "occurrences": []}

    host = (urlsplit(url).hostname or url).removeprefix("www.")
    country = (parsed.get("country") or p.get("country") or "").upper()[:2]
    flags = ["from_visitor"]
    if fetch.get("gave_up"):
        flags.append("fetch_failed")
    title = parsed.get("title") or ""
    if not title:
        title = host
        flags.append("check_title")
    fmt = parsed.get("format") or ""
    if not fmt:
        flags.append("no_format")
    if not p.get("type"):
        flags.append("no_type")

    city_raw = (parsed.get("city") or p.get("city") or "").strip()
    city, problem = resolve_city(country, city_raw) if city_raw else (None, "")
    if problem:
        flags.append(problem)
    occs = []
    start = parsed.get("start_date") or p.get("date") or ""
    try:
        d = date.fromisoformat(start)
        end = date.fromisoformat(parsed.get("end_date") or start)
        occs.append({"source_key": "main", "start_date": d.isoformat(), "end_date": max(end, d).isoformat(),
                     "precision": "datetime" if parsed.get("starts_at") else "date",
                     "starts_at": parsed.get("starts_at") or None, "ends_at": parsed.get("ends_at") or None,
                     "venue": parsed.get("venue", ""), "address": parsed.get("address", ""),
                     "status": parsed.get("status") or "scheduled",
                     "city_id": city.pk if city else None, "city_raw": city_raw})
    except ValueError:
        flags.append("no_date")
    if parsed.get("more_sessions"):
        flags.append("more_sessions")
    reason = "запропоновано відвідувачем" + (f"; розпізнано: {parsed.get('via')}" if parsed.get("via") else "")
    return {
        "status": "event_detected" if kind == "event" else "needs_review", "reason": reason, "removed": False,
        "flags": flags, "normalized_url": key,
        "event": {"title": title[:300], "original_language": parsed.get("lang") if parsed.get("lang") in
                  ("uk", "en", "pl", "ru") else "", "country_code": country,
                  "organizer_name": parsed.get("organizer", ""), "organizer_site": parsed.get("organizer_url", ""),
                  "source_url": url[:1000], "registration_url": parsed.get("ticket_url", ""),
                  "price_text": parsed.get("price", ""), "geo_signals": {}, "event_type_code": p.get("type") or "",
                  "format": fmt},
        "occurrences": occs,
        "hint_description": parsed.get("description", ""),
    }
