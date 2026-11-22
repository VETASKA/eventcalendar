"""Reading an event out of a web page: schema.org Event (JSON-LD) first, then the page title and dates in text.

Result kind: "event" — the page describes an event with a date (structured data);
"maybe" — looks like an event (a title and a date in the text) but needs a moderator;
"no" — nothing that looks like an event.
The source's description is kept only as a hint for the moderator: the public card gets its own short summary.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

EVENT_TYPES = {"Event", "BusinessEvent", "ChildrensEvent", "ComedyEvent", "CourseInstance", "DanceEvent",
               "DeliveryEvent", "EducationEvent", "EventSeries", "ExhibitionEvent", "Festival", "FoodEvent",
               "Hackathon", "LiteraryEvent", "MusicEvent", "PublicationEvent", "SaleEvent", "ScreeningEvent",
               "SocialEvent", "SportsEvent", "TheaterEvent", "VisualArtsEvent"}

MONTHS = {
    # uk (genitive), ru (genitive), en, pl (genitive)
    **{m: i + 1 for i, m in enumerate(["січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня",
                                        "вересня", "жовтня", "листопада", "грудня"])},
    **{m: i + 1 for i, m in enumerate(["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
                                        "сентября", "октября", "ноября", "декабря"])},
    **{m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                        "september", "october", "november", "december"])},
    **{m: i + 1 for i, m in enumerate(["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca",
                                        "sierpnia", "września", "października", "listopada", "grudnia"])},
}
_NUM_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](20\d{2})\b|\b(20\d{2})-(\d{2})-(\d{2})\b")
_WORD_DATE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\s*,?\s*(20\d{2})?",
                        re.I)
_EN_DATE = re.compile(r"\b(" + "|".join(list(MONTHS)[24:36]) + r")\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})", re.I)


def _types(node) -> set[str]:
    t = node.get("@type") if isinstance(node, dict) else None
    items = t if isinstance(t, list) else [t]
    return {str(x).rsplit("/", 1)[-1] for x in items if x}


def _walk(data):
    if isinstance(data, list):
        for x in data:
            yield from _walk(x)
    elif isinstance(data, dict):
        yield data
        for k in ("@graph", "subEvent", "event", "events", "itemListElement", "item", "mainEntity"):
            if k in data:
                yield from _walk(data[k])


def _jsonld_events(soup) -> list[dict]:
    out = []
    for tag in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = (tag.string or tag.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))       # trailing commas, a common slip
            except ValueError:
                continue
        out += [n for n in _walk(data) if _types(n) & EVENT_TYPES]
    return out


def _text(v) -> str:
    if isinstance(v, list):
        v = v[0] if v else ""
    if isinstance(v, dict):
        v = v.get("name") or v.get("@value") or ""
    return re.sub(r"\s+", " ", str(v or "")).strip()


def parse_when(v: str) -> tuple[date | None, datetime | None]:
    """'2027-03-14' → (date, None); '2027-03-14T19:00:00+02:00' → (date, aware datetime)."""
    v = _text(v)
    if not v:
        return None, None
    try:
        if len(v) <= 10:
            return date.fromisoformat(v[:10]), None
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return dt.date(), (dt if dt.tzinfo else None)
    except ValueError:
        return None, None


def _place(loc) -> dict:
    if isinstance(loc, list):
        loc = next((x for x in loc if isinstance(x, dict)), loc[0] if loc else {})
    if isinstance(loc, str):
        return {"venue": loc}
    if not isinstance(loc, dict):
        return {}
    if _types(loc) & {"VirtualLocation"}:
        return {"online": True, "online_url": _text(loc.get("url"))}
    addr = loc.get("address")
    out = {"venue": _text(loc.get("name"))}
    if isinstance(addr, dict):
        out.update(city=_text(addr.get("addressLocality")), address=_text(addr.get("streetAddress")),
                   country=_text(addr.get("addressCountry"))[:2].upper())
    elif addr:
        out["address"] = _text(addr)
    return out


def _price(offers) -> tuple[str, str]:
    """(price text, ticket url)"""
    if isinstance(offers, list):
        offers = next((o for o in offers if isinstance(o, dict)), {})
    if not isinstance(offers, dict):
        return "", ""
    cur = _text(offers.get("priceCurrency"))
    price = _text(offers.get("price") or offers.get("lowPrice"))
    text = ""
    if price:
        text = "безкоштовно" if price in ("0", "0.0", "0.00") else f"{price} {cur}".strip()
    return text[:120], _text(offers.get("url"))


def _from_jsonld(ev: dict) -> dict:
    d, dt = parse_when(ev.get("startDate"))
    ed, edt = parse_when(ev.get("endDate"))
    place = _place(ev.get("location"))
    mode = _text(ev.get("eventAttendanceMode")).rsplit("/", 1)[-1]
    fmt = ("online" if "Online" in mode else "hybrid" if "Mixed" in mode else "offline" if "Offline" in mode
           else "online" if place.get("online") else "offline" if place.get("city") or place.get("venue") else "")
    status = _text(ev.get("eventStatus")).rsplit("/", 1)[-1]
    price, ticket = _price(ev.get("offers"))
    org = ev.get("organizer")
    if isinstance(org, list):
        org = org[0] if org else {}
    return {
        "title": _text(ev.get("name"))[:300], "description": _text(ev.get("description"))[:2000],
        "start_date": d.isoformat() if d else "", "end_date": (ed or d).isoformat() if (ed or d) else "",
        "starts_at": dt.isoformat() if dt else "", "ends_at": edt.isoformat() if edt else "",
        "city": place.get("city", ""), "venue": place.get("venue", "")[:300], "address": place.get("address", "")[:500],
        "country": place.get("country", ""), "format": fmt,
        "status": {"EventCancelled": "cancelled", "EventPostponed": "postponed",
                   "EventRescheduled": "rescheduled"}.get(status, "scheduled"),
        "price": price, "ticket_url": ticket[:1000],
        "organizer": _text(org)[:300] if org else "", "organizer_url": _text(org.get("url"))
        if isinstance(org, dict) else "",
    }


def _date_in_text(text: str, today: date) -> date | None:
    """The first plausible date (from a year ago to three years ahead) in the page text."""
    found: list[date] = []
    for m in _NUM_DATE.finditer(text):
        try:
            found.append(date(int(m[3]), int(m[2]), int(m[1])) if m[3] else date(int(m[4]), int(m[5]), int(m[6])))
        except ValueError:
            pass
    for m in _WORD_DATE.finditer(text):
        try:
            found.append(date(int(m[3] or today.year), MONTHS[m[2].lower()], int(m[1])))
        except (ValueError, KeyError):
            pass
    for m in _EN_DATE.finditer(text):
        try:
            found.append(date(int(m[3]), MONTHS[m[1].lower()], int(m[2])))
        except (ValueError, KeyError):
            pass
    ok = [d for d in found if (today.year - 1) <= d.year <= today.year + 3]
    return ok[0] if ok else None


def parse(html: str, url: str = "", today: date | None = None) -> dict:
    today = today or date.today()
    soup = BeautifulSoup(html or "", "html.parser")
    lang = (soup.html.get("lang") if soup.html else "") or ""
    events = [e for e in _jsonld_events(soup) if e.get("startDate")]
    if events:
        data = _from_jsonld(events[0])
        if data["start_date"]:
            return {"kind": "event", "via": "schema.org", "lang": lang[:2].lower(), "more_sessions": len(events) - 1,
                    **data}

    og = soup.find("meta", attrs={"property": "og:title"})
    title = (og.get("content") if og else "") or (soup.title.get_text() if soup.title else "")
    title = re.sub(r"\s+", " ", title).strip()[:300]
    desc_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" "))[:200_000]
    d = _date_in_text(text, today)
    base = {"title": title, "description": (desc_tag.get("content") if desc_tag else "")[:2000], "lang": lang[:2].lower(),
            "start_date": d.isoformat() if d else "", "end_date": d.isoformat() if d else "", "starts_at": "",
            "ends_at": "", "city": "", "venue": "", "address": "", "country": "", "format": "", "status": "scheduled",
            "price": "", "ticket_url": "", "organizer": "", "organizer_url": "", "more_sessions": 0}
    if title and d:
        return {"kind": "maybe", "via": "text", **base}
    return {"kind": "no", "via": "text", **base}
