"""«Запропонувати подію» from the home page → the same normalized record as an import.

The visitor gives a link and, optionally, a date, city and category. The card waits for moderation;
the title is the site's address until the moderator (or, later, the parser) fills it in.
"""
from __future__ import annotations

from datetime import date
from urllib.parse import urlsplit

from apps.core.text import norm_url
from apps.geo.services import resolve_city


def normalize(p: dict) -> dict:
    url = (p.get("url") or "").strip()
    host = (urlsplit(url).hostname or url).removeprefix("www.")
    country = (p.get("country") or "").upper()[:2]
    flags = ["from_visitor", "no_format", "check_title"]
    city_raw = (p.get("city") or "").strip()
    city, problem = resolve_city(country, city_raw) if city_raw else (None, "")
    if problem:
        flags.append(problem)
    occs = []
    try:
        d = date.fromisoformat(p.get("date") or "")
        occs.append({"source_key": "main", "start_date": d.isoformat(), "end_date": d.isoformat(),
                     "precision": "date", "city_id": city.pk if city else None, "city_raw": city_raw})
    except ValueError:
        flags.append("no_date")
    if not p.get("type"):
        flags.append("no_type")
    note = "запропоновано відвідувачем" + (f", місто: {city_raw}" if city_raw and not city else "")
    return {
        "status": "needs_review", "reason": note, "removed": False, "flags": flags,
        "normalized_url": norm_url(url),
        "event": {"title": host[:300], "original_language": "", "country_code": country, "organizer_name": "",
                  "organizer_site": "", "source_url": url[:1000], "registration_url": "", "price_text": "",
                  "geo_signals": {}, "event_type_code": p.get("type") or ""},
        "occurrences": occs,
    }
