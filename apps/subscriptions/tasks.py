"""Scheduled mail: the weekly digest (Tuesday 11:00 Kyiv), reminders a day ahead, notices about changes."""
import logging

from celery import shared_task
from django.utils import timezone

from apps.catalog.models import Occurrence
from apps.core.i18n import lurl
from apps.core.mail import site_url

from .delivery import deliver
from .models import Announcement, Reminder, Subscription
from .services import digest_events, reschedule_for

logger = logging.getLogger(__name__)


def _event_url(sub, e) -> str:
    return site_url(sub.site, lurl(f"/events/{e.pk}-{e.slug}/", sub.lang))


@shared_task
def send_digests() -> dict:
    now = timezone.now()
    week = now.strftime("%G-W%V")
    sent = skipped = 0
    for sub in Subscription.objects.filter(status="active", digest=True).select_related("site"):
        items = digest_events(sub, now)
        if not items:
            skipped += 1                                   # no empty letters
            continue
        rows = [{"event": e, "occ": occs[0], "url": _event_url(sub, e),
                 "city": occs[0].city.label(sub.lang) if occs[0].city_id else ""} for e, occs in items[:30]]
        d = deliver(sub, "digest", f"digest:{sub.pk}:{week}", "digest", {
            "rows": rows, "more": max(0, len(items) - 30), "home": site_url(sub.site, lurl("/", sub.lang))})
        if d.status == "sent":
            sub.last_digest_at = now
            sub.save(update_fields=["last_digest_at"])
            sent += 1
    Announcement.objects.filter(digested_at__isnull=True, created_at__lte=now).update(digested_at=now)
    logger.info("digest %s: sent %s, nothing new for %s", week, sent, skipped)
    return {"sent": sent, "skipped": skipped}


@shared_task
def send_due_reminders() -> int:
    n = 0
    due = (Reminder.objects.filter(status="scheduled", send_at__lte=timezone.now(), subscription__status="active")
           .select_related("subscription__site", "occurrence__event", "occurrence__city"))
    for r in due:
        o, sub = r.occurrence, r.subscription
        if o.status == "cancelled" or not o.event.publications.filter(site=sub.site, status="published").exists():
            r.status = "cancelled"
            r.save(update_fields=["status"])
            continue
        d = deliver(sub, "reminder", f"reminder:{r.pk}:{r.send_at.isoformat()}", "reminder",
                    {"event": o.event, "occ": o, "url": _event_url(sub, o.event),
                     "city": o.city.label(sub.lang) if o.city_id else ""})
        if d.status == "sent":
            r.status = "sent"
            r.save(update_fields=["status"])
            n += 1
    return n


@shared_task
def notify_change(occurrence_id: int, before: dict) -> int:
    """A session moved or was cancelled: fix waiting reminders, tell the people who asked for one."""
    o = Occurrence.objects.filter(pk=occurrence_id).select_related("event", "city").first()
    if o is None:
        return 0
    n = 0
    for r in reschedule_for(o):
        sub = r.subscription
        key = f"change:{r.pk}:{o.status}:{o.start_date}:{o.starts_at.isoformat() if o.starts_at else ''}"
        d = deliver(sub, "change", key, "change", {"event": o.event, "occ": o, "before": before,
                                                    "url": _event_url(sub, o.event),
                                                    "cancelled": o.status == "cancelled"})
        n += d.status == "sent"
    return n
