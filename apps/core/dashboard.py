"""Numbers for the admin start page."""
from datetime import date

from django.db.models import Count, Q
from django.urls import reverse


def dashboard_callback(request, context):
    from apps.catalog.models import Event, EventRevision, SitePublication
    from apps.feedback.models import ErrorReport
    from apps.intake.models import EventSource
    from apps.organizers.models import Claim

    ev = reverse("admin:catalog_event_changelist")
    pending = Event.objects.filter(state="pending")
    counts = pending.aggregate(
        total=Count("id"),
        no_city=Count("id", filter=Q(review_flags__contains=["city_unknown"]) | Q(review_flags__contains=["city_ambiguous"])),
        no_date=Count("id", filter=Q(review_flags__contains=["no_date"])),
        abroad=Count("id", filter=Q(publications__isnull=True)),
    )
    upcoming = SitePublication.objects.filter(status="published",
                                              event__occurrences__end_date__gte=date.today()).values("event").distinct()
    context.update({
        "kpis": [
            {"title": "Ждут модерации", "value": counts["total"], "href": f"{ev}?state__exact=pending",
             "icon": "pending_actions"},
            {"title": "Опубликовано, впереди", "value": upcoming.count(), "href": f"{ev}?state__exact=approved",
             "icon": "event_available"},
            {"title": "Предложенные изменения", "value": EventRevision.objects.filter(status="proposed").count(),
             "href": reverse("admin:catalog_eventrevision_changelist") + "?status__exact=proposed", "icon": "difference"},
            {"title": "Сообщения об ошибках", "value": ErrorReport.objects.filter(status="new").count(),
             "href": reverse("admin:feedback_errorreport_changelist") + "?status__exact=new", "icon": "report"},
            {"title": "Заявки «Это моё событие»", "value": Claim.objects.filter(status__in=["open", "verified"]).count(),
             "href": reverse("admin:organizers_claim_changelist") + "?status__exact=open", "icon": "verified_user"},
            {"title": "Не на украинском сайте (другие страны)", "value": counts["abroad"],
             "href": f"{ev}?state__exact=pending&site=none", "icon": "public"},
        ],
        "checks": [
            {"title": "Город не распознан", "value": counts["no_city"], "href": f"{ev}?state__exact=pending&flag=city_unknown"},
            {"title": "Нет даты", "value": counts["no_date"], "href": f"{ev}?state__exact=pending&flag=no_date"},
            {"title": "Без формата и типа", "value": pending.filter(Q(format="") | Q(event_type__isnull=True)).count(),
             "href": f"{ev}?state__exact=pending&flag=no_type"},
        ],
        "sources": [{"name": s.name, "last": s.last_seen_at, "items": s.items.count()} for s in EventSource.objects.all()],
    })
    return context
