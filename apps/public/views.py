"""Public storefront: the calendar page and the events API behind it (stage 2 adds filters and cards)."""
from datetime import date, timedelta

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.catalog.models import Occurrence

MAX_RANGE_DAYS = 62          # one month view plus the leading / trailing weeks


def _day(v: str | None) -> date | None:
    try:
        return date.fromisoformat((v or "")[:10])
    except ValueError:
        return None


@require_GET
def calendar_page(request):
    return render(request, "public/calendar.html", {"site": request.site})


@require_GET
def events_api(request):
    """GET /api/v1/events?from=YYYY-MM-DD&to=YYYY-MM-DD — sessions of published events, range [from, to)."""
    start, end = _day(request.GET.get("from")), _day(request.GET.get("to"))
    if not start or not end or end <= start:
        return JsonResponse({"error": "from / to are required, YYYY-MM-DD, to > from"}, status=400)
    if (end - start).days > MAX_RANGE_DAYS:
        return JsonResponse({"error": f"range is limited to {MAX_RANGE_DAYS} days"}, status=400)
    occs = (Occurrence.objects
            .filter(event__publications__site=request.site, event__publications__status="published",
                    start_date__lt=end, end_date__gte=start)
            .exclude(status="postponed")
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
            "url": e.registration_url or e.source_url,
            "city": o.city.label("uk") if o.city_id else "",
            "format": e.format,
            "type": e.event_type.names.get("uk", "")
            if e.event_type_id else "",
            "time_unknown": o.precision == "date",
            "status": o.status,
        })
    return JsonResponse({"events": items})
