"""Public storefront: calendar page, event page, the JSON APIs behind them, sitemap and robots."""
import json
import zoneinfo
from datetime import date, timedelta

from django.db.models import Count, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone as tz
from django.utils.formats import date_format
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET

from apps.catalog.models import Event, EventType, Occurrence
from apps.core.i18n import lang, lurl, name_in
from apps.geo.models import City

from .forms import ErrorReportForm, SuggestForm

MAX_RANGE_DAYS = 62          # one month view plus the leading / trailing weeks
FORMATS = ["offline", "online", "hybrid"]


def format_label(code: str) -> str:
    return {"offline": _("Офлайн"), "online": _("Онлайн"), "hybrid": _("Гібрид")}.get(code, "")


def status_label(code: str) -> str:
    return {"cancelled": _("Скасовано"), "postponed": _("Перенесено, нова дата уточнюється"),
            "rescheduled": _("Перенесено")}.get(code, "")


def _day(v: str | None) -> date | None:
    try:
        return date.fromisoformat((v or "")[:10])
    except ValueError:
        return None


def nice_date(d: date) -> str:
    return date_format(d, "j E Y")


def event_path(e: Event) -> str:
    return lurl(f"/events/{e.pk}-{e.slug}/")


# ── filters ──────────────────────────────────────────────────────────────────

def _published(site):
    return Q(event__publications__site=site, event__publications__status="published")


def _filters(request) -> dict:
    ints = lambda vs: [int(v) for v in vs if v.isdigit()][:30]  # noqa: E731
    return {"q": (request.GET.get("q") or "").strip()[:100],
            "types": [t for t in request.GET.getlist("type") if t][:20],
            "cities": ints(request.GET.getlist("city")),
            "formats": [f for f in request.GET.getlist("format") if f in FORMATS]}


def _apply(qs, f: dict):
    """qs is an Occurrence queryset."""
    if f["q"]:
        qs = qs.filter(Q(event__title__icontains=f["q"]) | Q(event__translations__title__icontains=f["q"]))
    if f["types"]:
        qs = qs.filter(event__event_type__code__in=f["types"])
    if f["cities"]:
        qs = qs.filter(city_id__in=f["cities"])
    if f["formats"]:
        qs = qs.filter(event__format__in=f["formats"])
    return qs


def _upcoming(site):
    return Occurrence.objects.filter(_published(site), end_date__gte=date.today()).exclude(status="cancelled")


def facets(site) -> dict:
    """Only choices that have at least one upcoming published event (empty categories are not offered)."""
    up = _upcoming(site)
    type_n = dict(up.values("event__event_type").annotate(n=Count("event", distinct=True))
                  .values_list("event__event_type", "n"))
    types = [{"code": t.code, "name": name_in(t.names, fallback=t.code), "n": type_n[t.pk]}
             for t in EventType.objects.filter(pk__in=[k for k in type_n if k], is_active=True)
             .order_by("position", "code")]
    city_n = dict(up.values("city").annotate(n=Count("event", distinct=True)).values_list("city", "n"))
    cities = sorted(({"code": str(c.pk), "name": c.label(lang()), "n": city_n[c.pk], "w": c.importance}
                     for c in City.objects.filter(pk__in=[k for k in city_n if k])),
                    key=lambda c: (-c["n"], -c["w"], c["name"]))
    fmt_n = dict(up.values("event__format").annotate(n=Count("event", distinct=True))
                 .values_list("event__format", "n"))
    formats = [{"code": f, "name": format_label(f), "n": fmt_n[f]} for f in FORMATS if fmt_n.get(f)]
    return {"types": types, "cities": cities, "formats": formats}


# ── pages ────────────────────────────────────────────────────────────────────

@require_GET
def calendar_page(request):
    f = _filters(request)
    fc = facets(request.site)
    groups = [
        {"key": "type", "all": _("Усі категорії"), "items": fc["types"], "picked": f["types"]},
        {"key": "city", "all": _("Усі міста"), "items": fc["cities"], "picked": [str(c) for c in f["cities"]]},
        {"key": "format", "all": _("Будь-який формат"), "items": fc["formats"], "picked": f["formats"]},
    ]
    return render(request, "public/calendar.html", {
        "site": request.site, "q": f["q"], "groups": [g for g in groups if g["items"]],
        "filtered": bool(f["q"] or f["types"] or f["cities"] or f["formats"]), "suggest": SuggestForm()})


def _when(o) -> dict:
    days = nice_date(o.start_date) if o.start_date == o.end_date else \
        f"{nice_date(o.start_date)} — {nice_date(o.end_date)}"
    weekday = date_format(o.start_date, "l") if o.start_date == o.end_date else ""
    if o.precision == "datetime" and o.starts_at:
        zone = zoneinfo.ZoneInfo(o.timezone or "Europe/Kyiv")
        t = tz.localtime(o.starts_at, zone).strftime("%H:%M")
        if o.ends_at:
            t += "–" + tz.localtime(o.ends_at, zone).strftime("%H:%M")
    elif o.precision == "all_day":
        t = _("Весь день")
    else:
        t = _("Час уточнюється")
    return {"days": days, "weekday": weekday, "time": t, "status": status_label(o.status), "o": o}


def _jsonld(request, e, occs, tickets) -> str:
    o = occs[0] if occs else None
    if not o:
        return ""
    timed = o.precision == "datetime" and o.starts_at
    data = {"@context": "https://schema.org", "@type": "Event", "name": e.title,
            "url": request.build_absolute_uri(request.path),
            "startDate": o.starts_at.isoformat() if timed else o.start_date.isoformat(),
            "endDate": (o.ends_at.isoformat() if timed and o.ends_at else o.end_date.isoformat()),
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
        return redirect(event_path(e), permanent=True)
    occs = list(e.occurrences.select_related("city").order_by("start_date", "starts_at"))
    reg = _("Реєстрація та квитки")
    tickets = [{"label": t.label, "url": t.url, "price": t.price_text, "generic": False}
               for t in e.ticket_links.filter(is_active=True)]
    if not tickets and e.registration_url:
        tickets = [{"label": reg, "url": e.registration_url, "price": "", "generic": True}]
    if e.tickets_mode == "primary":
        tickets = tickets[:1]
    tr = e.translations.filter(lang=lang()).first()
    code = lang()
    return render(request, "public/event.html", {
        "e": e, "title": tr.title if tr else e.title, "summary": tr.summary if tr else e.summary,
        "sessions": [_when(o) for o in occs], "tickets": tickets,
        "format": format_label(e.format), "online": e.format == "online",
        "type": name_in(e.event_type.names) if e.event_type_id else "",
        "topics": [name_in(t.names, fallback=t.code) for t in e.topics.all()],
        "city": next((o.city.label(code) for o in occs if o.city_id), ""),
        "venue": next((o.venue for o in occs if o.venue), ""),
        "jsonld": _jsonld(request, e, occs, tickets),
        "foreign_lang": e.original_language not in ("", code) and not tr,
        "report_form": ErrorReportForm(),
        "reminders": [{"id": o.pk, "label": _when(o)["days"]} for o in occs
                      if o.end_date >= date.today() and o.status != "cancelled"],
    })


# ── JSON APIs (?lang=uk|en|pl) ───────────────────────────────────────────────

@require_GET
def search_api(request):
    """GET /api/v1/search?q=&type=&city=&format= — up to 10 upcoming published events matching (any month)."""
    f = _filters(request)
    if not (f["q"] or f["types"] or f["cities"] or f["formats"]):
        return JsonResponse({"results": [], "total": 0})
    occs = _apply(Occurrence.objects.filter(_published(request.site), end_date__gte=date.today())
                  .exclude(status="postponed"), f)
    ids, results = set(), []
    for o in occs.select_related("event", "city").order_by("start_date", "starts_at", "id")[:300]:
        if o.event_id in ids:
            continue
        ids.add(o.event_id)
        if len(results) < 10:
            results.append({"title": o.event.title, "url": event_path(o.event), "date": nice_date(o.start_date),
                            "start": o.start_date.isoformat(), "city": o.city.label(lang()) if o.city_id else ""})
    return JsonResponse({"results": results, "total": len(ids)})


@require_GET
def events_api(request):
    """GET /api/v1/events?from=YYYY-MM-DD&to=YYYY-MM-DD&… — sessions of published events, range [from, to)."""
    start, end = _day(request.GET.get("from")), _day(request.GET.get("to"))
    if not start or not end or end <= start:
        return JsonResponse({"error": "from / to are required, YYYY-MM-DD, to > from"}, status=400)
    if (end - start).days > MAX_RANGE_DAYS:
        return JsonResponse({"error": f"range is limited to {MAX_RANGE_DAYS} days"}, status=400)
    code = lang()
    occs = (_apply(Occurrence.objects.filter(_published(request.site), start_date__lt=end, end_date__gte=start),
                   _filters(request))
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
            "url": event_path(e),
            "city": o.city.label(code) if o.city_id else "",
            "format": e.format,
            "type": name_in(e.event_type.names) if e.event_type_id else "",
            "time_unknown": o.precision == "date",
            "status": o.status,
            "date_label": nice_date(o.start_date) if o.start_date == o.end_date
            else f"{nice_date(o.start_date)} — {nice_date(o.end_date)}",
        })
    return JsonResponse({"events": items})


# ── robots / sitemap ─────────────────────────────────────────────────────────

@require_GET
def robots_txt(request):
    base = f"{request.scheme}://{request.get_host()}"
    body = ("User-agent: *\nDisallow: /admin/\nDisallow: /api/\nDisallow: /cabinet/\nDisallow: /en/cabinet/\n"
            "Disallow: /pl/cabinet/\nDisallow: /suggest/\n"
            f"Sitemap: {base}/sitemap.xml\n")
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


@require_GET
def sitemap_xml(request):
    """Only published events of this site, every language version with hreflang alternates."""
    from xml.sax.saxutils import escape

    base = f"{request.scheme}://{request.get_host()}"
    evs = (Event.objects.filter(publications__site=request.site, publications__status="published")
           .order_by("pk").only("pk", "title", "updated_at"))
    langs = ["uk", "en", "pl"]

    def entry(path: str, lastmod=None) -> str:
        alts = "".join(f'<xhtml:link rel="alternate" hreflang="{c}" href="{escape(base + lurl(path, c))}"/>'
                       for c in langs)
        mod = f"<lastmod>{lastmod.date().isoformat()}</lastmod>" if lastmod else ""
        return "".join(f"<url><loc>{escape(base + lurl(path, c))}</loc>{mod}{alts}</url>" for c in langs)

    parts = [entry("/")] + [entry(f"/events/{e.pk}-{e.slug}/", e.updated_at) for e in evs.iterator()]
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">'
           + "".join(parts) + "</urlset>")
    return HttpResponse(xml, content_type="application/xml; charset=utf-8")
