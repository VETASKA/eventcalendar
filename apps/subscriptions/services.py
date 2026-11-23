"""Rules for subscriptions: what a digest contains, when a reminder goes out, who hears about a change."""
from __future__ import annotations

import zoneinfo
from datetime import date, datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from apps.catalog.models import Event, Occurrence

from .models import Announcement, Reminder, Subscription


def reminder_time(o: Occurrence) -> datetime:
    """24 hours before the start; when only the day is known — 10:00 local time the day before."""
    if o.precision == "datetime" and o.starts_at:
        return o.starts_at - timedelta(hours=24)
    zone = zoneinfo.ZoneInfo(o.timezone or "Europe/Kyiv")
    return datetime.combine(o.start_date - timedelta(days=1), time(10, 0), zone)


def digest_events(sub: Subscription, now: datetime | None = None) -> list[tuple[Event, list[Occurrence]]]:
    """Events first published on this site since the last digest, still ahead, matching the interests."""
    now = now or timezone.now()
    since = sub.last_digest_at or sub.consent_at or sub.created_at
    ann = (Announcement.objects.filter(site=sub.site, suppressed=False, created_at__gt=since, created_at__lte=now)
           .values_list("event_id", flat=True))
    events = (Event.objects.filter(pk__in=ann, publications__site=sub.site, publications__status="published")
              .select_related("event_type").distinct())
    out = []
    for e in events:
        occs = [o for o in e.occurrences.select_related("city").order_by("start_date")
                if o.end_date >= date.today() and o.status != "cancelled"]
        if occs and sub.matches(e, occs):
            out.append((e, occs))
    return sorted(out, key=lambda x: x[1][0].start_date)


def reschedule_for(o: Occurrence) -> list[Reminder]:
    """After a session changed: move waiting reminders, cancel them for a cancelled session. Returns the
    reminders whose holders should hear about the change."""
    waiting = list(Reminder.objects.filter(occurrence=o).filter(Q(status="scheduled") | Q(status="sent"))
                   .select_related("subscription"))
    for r in waiting:
        if o.status == "cancelled":
            if r.status == "scheduled":
                r.status = "cancelled"
                r.save(update_fields=["status"])
        elif r.status == "scheduled":
            r.send_at = reminder_time(o)
            r.save(update_fields=["send_at"])
    return [r for r in waiting if r.subscription.status == "active"]
