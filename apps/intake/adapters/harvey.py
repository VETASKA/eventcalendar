"""Harvey (findclients-rte) → normalized intake record.

Harvey keeps one row per event site (domain): name, city (Russian canonical name), one date,
price text, ticket provider, country and `kind` = event | maybe | not_event | junk.
It does not know format, type or topics — the moderator fills those in.
"""
from __future__ import annotations

import re
from datetime import date

from apps.core.text import norm_url
from apps.geo.services import resolve_city

KIND_STATUS = {"event": "event_detected", "maybe": "needs_review", "not_event": "not_event", "junk": "not_event"}

_UK = re.compile(r"[іїєґ]", re.I)
_PL = re.compile(r"[ąęłśżźćń]", re.I)
_RU = re.compile(r"[ыэъё]", re.I)
_CYR = re.compile(r"[а-я]", re.I)
_LAT = re.compile(r"[a-z]", re.I)


def guess_language(text: str) -> str:
    t = text or ""
    if _UK.search(t):
        return "uk"
    if _PL.search(t):
        return "pl"
    if _RU.search(t):
        return "ru"
    if _CYR.search(t):
        return ""          # Cyrillic without tell-tale letters: uk or ru, let the moderator decide
    return "en" if _LAT.search(t) else ""


def _date(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _url(v: str) -> str:
    v = (v or "").strip()
    if v and "://" not in v:
        v = "https://" + v
    return v[:1000]


def normalize(p: dict) -> dict:
    flags: list[str] = []
    kind = (p.get("kind") or "").strip() or "maybe"
    status = KIND_STATUS.get(kind, "needs_review")
    reason = p.get("kind_why") or ""
    removed = bool(p.get("removed"))
    if removed:
        status, reason = "not_event", "removed_in_source"

    url = _url(p.get("url") or p.get("domain") or "")
    title = (p.get("name") or "").strip()[:300]
    if not title:
        flags.append("no_title")
    country = (p.get("country") or "").strip().upper()[:2]
    if not country:
        flags.append("country_unknown")

    org = p.get("organizer") or {}
    signals = dict(p.get("signals") or {})
    lang = (p.get("language") or "").strip().lower()[:5] or guess_language(title)
    if lang == "uk":
        signals["lang_uk"] = True
    if country == "UA":
        signals["country_ua"] = True

    city_raw = (p.get("city") or "").strip()
    city, city_problem = resolve_city(country, city_raw) if city_raw else (None, "")
    if city_problem:
        flags.append(city_problem)

    occurrences = []
    d = _date(p.get("date"))
    if d:
        occurrences.append({
            "source_key": "main",
            "start_date": d.isoformat(),
            "end_date": (_date(p.get("end_date")) or d).isoformat(),
            "precision": "date",          # Harvey has the day only: «Час уточнюється»
            "city_id": city.pk if city else None,
            "city_raw": city_raw,
        })
    else:
        flags.append("no_date")
    if p.get("date_text") and not d:
        reason = (reason + "; " if reason else "") + f"дата в джерелі: {p['date_text']}"
    flags += ["no_format", "no_type"]      # Harvey never knows these

    return {
        "status": status,
        "reason": reason,
        "removed": removed,
        "flags": flags,
        "normalized_url": norm_url(url),
        "event": {
            "title": title or (p.get("domain") or url),
            "original_language": lang if lang in ("uk", "en", "pl", "ru") else "",
            "country_code": country,
            "organizer_name": (org.get("name") or "")[:300],
            "organizer_site": _url(org.get("website") or ""),
            "source_url": url,
            "registration_url": _url(p.get("registration_url") or ""),
            "price_text": (p.get("price_text") or "")[:120],
            "geo_signals": signals,
        },
        "occurrences": occurrences,
    }
