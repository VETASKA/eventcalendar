"""Public storefront: the calendar page and the events API behind it (stage 2 adds filters and cards)."""
from datetime import date, timedelta

from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.catalog.models import EventType, Occurrence

MAX_RANGE_DAYS = 62          # one month view plus the leading / trailing weeks


def _day(v: str | None) -> date | None:
    try:
        return date.fromisoformat((v or "")[:10])
    except ValueError:
        return None


def _published(site):
    return Q(event__publications__site=site, event__publications__status="published")


def _filters(request) -> tuple[str, list[str]]:
    q = (request.GET.get("q") or "").strip()[:100]
    types = [t for t in request.GET.getlist("type") if t][:20]
    return q, types


def _apply(qs, q: str, types: list[str], prefix: str = "event__"):
    if q:
        qs = qs.filter(Q(**{f"{prefix}title__icontains": q}) | Q(**{f"{prefix}translations__title__icontains": q}))
    if types:
        qs = qs.filter(**{f"{prefix}event_type__code__in": types})
    return qs


def type_facets(site) -> list[dict]:
    """Categories that have at least one published event that has not ended yet (the filter shows only these)."""
    rows = (EventType.objects.filter(is_active=True,
                                     event__publications__site=site, event__publications__status="published",
                                     event__occurrences__end_date__gte=date.today())
            .annotate(n=Count("event", distinct=True)).order_by("position", "code"))
    return [{"code": t.code, "name": t.names.get("uk") or t.code, "n": t.n} for t in rows]


@require_GET
def calendar_page(request):
    q, types = _filters(request)
    from .forms import SuggestForm
    return render(request, "public/calendar.html", {"site": request.site, "q": q, "types": types,
                                                    "facets": type_facets(request.site), "suggest": SuggestForm()})


@require_GET
def search_api(request):
    """GET /api/v1/search?q=&type= — up to 10 upcoming published events matching the filter (any month)."""
    q, types = _filters(request)
    if not q and not types:
        return JsonResponse({"results": [], "total": 0})
    occs = _apply(Occurrence.objects.filter(_published(request.site), end_date__gte=date.today())
                  .exclude(status="postponed"), q, types)
    ids, results = set(), []
    for o in occs.select_related("event", "city").order_by("start_date", "starts_at", "id")[:200]:
        if o.event_id in ids:
            continue
        ids.add(o.event_id)
        if len(results) < 10:
            results.append({"title": o.event.title, "url": f"/events/{o.event_id}-{o.event.slug}/",
                            "date": _uk_date(o.start_date), "start": o.start_date.isoformat(),
                            "city": o.city.name if o.city_id else ""})
    return JsonResponse({"results": results, "total": len(ids)})


@require_GET
def events_api(request):
    """GET /api/v1/events?from=YYYY-MM-DD&to=YYYY-MM-DD — sessions of published events, range [from, to)."""
    start, end = _day(request.GET.get("from")), _day(request.GET.get("to"))
    if not start or not end or end <= start:
        return JsonResponse({"error": "from / to are required, YYYY-MM-DD, to > from"}, status=400)
    if (end - start).days > MAX_RANGE_DAYS:
        return JsonResponse({"error": f"range is limited to {MAX_RANGE_DAYS} days"}, status=400)
    q, types = _filters(request)
    occs = (_apply(Occurrence.objects.filter(_published(request.site), start_date__lt=end, end_date__gte=start),
                   q, types)
            .exclude(status="postponed")
            .distinct()
            .select_related("event", "event__event_type", "city")
            .order_by("start_date", "starts_at", "id")[:1000])
    items = []
    for o in occs:
        e = o.event
        timed = o.precision == "datetime" and o.starts_at
        items.append({
            "id": o.pk,
            "event_id": e.pk,
            "title": e.title,
            "start": o.starts_at.isoformat() if timed else o.start_date.isoformat(),
            "end": (o.ends_at.isoformat() if timed and o.ends_at
                    else None if timed else (o.end_date + timedelta(days=1)).isoformat()),
            "allDay": not timed,
            "url": f"/events/{e.pk}-{e.slug}/",
            "city": o.city.label("uk") if o.city_id else "",
            "format": e.format,
            "type": e.event_type.names.get("uk", "")
            if e.event_type_id else "",
            "time_unknown": o.precision == "date",
            "status": o.status,
        })
    return JsonResponse({"events": items})


# ── event page ───────────────────────────────────────────────────────────────
import json  # noqa: E402

from django.http import Http404  # noqa: E402
from django.shortcuts import redirect  # noqa: E402

from apps.catalog.models import Event  # noqa: E402

from .forms import ErrorReportForm  # noqa: E402

UK_MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня", "вересня", "жовтня",
             "листопада", "грудня"]
UK_WEEKDAYS = ["понеділок", "вівторок", "середа", "четвер", "пʼятниця", "субота", "неділя"]
FORMAT_UK = {"offline": "Офлайн", "online": "Онлайн", "hybrid": "Гібрид"}
STATUS_UK = {"cancelled": "Скасовано", "postponed": "Перенесено, нова дата уточнюється", "rescheduled": "Перенесено"}


def _uk_date(d) -> str:
    return f"{d.day} {UK_MONTHS[d.month - 1]} {d.year}"


def _when(o) -> dict:
    from django.utils import timezone as tz
    import zoneinfo
    days = _uk_date(o.start_date) if o.start_date == o.end_date else \
        f"{_uk_date(o.start_date)} — {_uk_date(o.end_date)}"
    weekday = UK_WEEKDAYS[o.start_date.weekday()] if o.start_date == o.end_date else ""
    if o.precision == "datetime" and o.starts_at:
        zone = zoneinfo.ZoneInfo(o.timezone or "Europe/Kyiv")
        t = tz.localtime(o.starts_at, zone).strftime("%H:%M")
        if o.ends_at:
            t += "–" + tz.localtime(o.ends_at, zone).strftime("%H:%M")
    elif o.precision == "all_day":
        t = "Весь день"
    else:
        t = "Час уточнюється"
    return {"days": days, "weekday": weekday, "time": t, "status": STATUS_UK.get(o.status, ""), "o": o}


def _jsonld(request, e, occs, tickets) -> str:
    o = occs[0] if occs else None
    if not o:
        return ""
    data = {"@context": "https://schema.org", "@type": "Event", "name": e.title,
            "url": request.build_absolute_uri(),
            "startDate": o.starts_at.isoformat() if o.precision == "datetime" and o.starts_at else o.start_date.isoformat(),
            "endDate": (o.ends_at.isoformat() if o.precision == "datetime" and o.ends_at else o.end_date.isoformat()),
            "eventStatus": {"cancelled": "https://schema.org/EventCancelled",
                            "postponed": "https://schema.org/EventPostponed",
                            "rescheduled": "https://schema.org/EventRescheduled"}.get(o.status,
                                                                                      "https://schema.org/EventScheduled"),
            "eventAttendanceMode": {"online": "https://schema.org/OnlineEventAttendanceMode",
                                    "hybrid": "https://schema.org/MixedEventAttendanceMode"}.get(
                e.format, "https://schema.org/OfflineEventAttendanceMode")}
    if e.summary:
        data["description"] = e.summary
    if e.format == "online":
        data["location"] = {"@type": "VirtualLocation", "url": (tickets[0]["url"] if tickets else e.source_url)}
    elif o.city_id:
        data["location"] = {"@type": "Place", "name": o.venue or o.city.name,
                            "address": {"@type": "PostalAddress", "addressLocality": o.city.name,
                                        "addressCountry": o.city.country_id,
                                        **({"streetAddress": o.address} if o.address else {})}}
    if e.organizer_name:
        data["organizer"] = {"@type": "Organization", "name": e.organizer_name,
                             **({"url": e.organizer_site} if e.organizer_site else {})}
    if tickets:
        data["offers"] = [{"@type": "Offer", "url": t["url"]} for t in tickets]
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


@require_GET
def event_page(request, pk: int, slug: str = ""):
    e = (Event.objects.select_related("event_type", "country")
         .filter(pk=pk, publications__site=request.site, publications__status="published").first())
    if e is None:
        raise Http404
    if slug != e.slug:
        return redirect(f"/events/{e.pk}-{e.slug}/", permanent=True)
    occs = list(e.occurrences.select_related("city").order_by("start_date", "starts_at"))
    tickets = [{"label": t.label, "url": t.url, "price": t.price_text}
               for t in e.ticket_links.filter(is_active=True)]
    if not tickets and e.registration_url:
        tickets = [{"label": "Реєстрація та квитки", "url": e.registration_url, "price": ""}]
    if e.tickets_mode == "primary":
        tickets = tickets[:1]
    tr = e.translations.filter(lang="uk").first()
    return render(request, "public/event.html", {
        "e": e, "title": tr.title if tr else e.title, "summary": tr.summary if tr else e.summary,
        "sessions": [_when(o) for o in occs], "tickets": tickets,
        "format": FORMAT_UK.get(e.format, ""), "type": e.event_type.names.get("uk", "") if e.event_type_id else "",
        "topics": [t.names.get("uk", t.code) for t in e.topics.all()],
        "city": next((o.city.name for o in occs if o.city_id), ""),
        "venue": next((o.venue for o in occs if o.venue), ""),
        "jsonld": _jsonld(request, e, occs, tickets),
        "foreign_lang": e.original_language not in ("", "uk") and not tr,
        "report_form": ErrorReportForm(),
    })
