"""Catalogue rules: applying an import, checking a card before publication, approving it."""
from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.audit.models import log
from apps.geo.models import City, Country
from apps.portals.models import Site

from .models import Event, EventRevision, EventType, Occurrence, SitePublication

IMPORT_FIELDS = ("title", "original_language", "organizer_name", "organizer_site", "source_url",
                 "registration_url", "price_text")
NOT_YET_LIVE = ("draft", "pending", "withdrawn")


class PublishError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


# ── import ─────────────────────────────────────────────────────────────────

def _country(code: str) -> Country | None:
    return Country.objects.filter(pk=code).first() if code else None


def _sites_for(event: Event) -> list[Site]:
    sites = Site.objects.filter(is_active=True)
    if event.country_id:
        matched = list(sites.filter(countries=event.country_id))
        if matched:
            return matched
    # unknown or foreign country: the default storefront's moderators decide (it carries a flag)
    return list(sites.filter(is_default=True)) if not event.country_id else []


def _ensure_publications(event: Event) -> None:
    for site in _sites_for(event):
        SitePublication.objects.get_or_create(site=site, event=event)


def _set_occurrences(event: Event, occs: list[dict]) -> None:
    """Import-owned sessions (with a source_key) follow the source; sessions added by hand stay."""
    keep = set()
    for o in occs:
        tz = (event.country.timezone if event.country_id and event.country.timezone else "Europe/Kyiv")
        Occurrence.objects.update_or_create(
            event=event, source_key=o["source_key"],
            defaults={"start_date": o["start_date"], "end_date": o["end_date"], "precision": o["precision"],
                      "timezone": tz, "city": City.objects.filter(pk=o.get("city_id")).first()})
        keep.add(o["source_key"])
    event.occurrences.exclude(source_key="").exclude(source_key__in=keep).delete()


def _occ_snapshot(event: Event) -> list[dict]:
    return [{"source_key": o.source_key, "start_date": o.start_date.isoformat(), "end_date": o.end_date.isoformat(),
             "precision": o.precision, "city_id": o.city_id}
            for o in event.occurrences.exclude(source_key="").order_by("source_key")]


def _occ_comparable(occs: list[dict]) -> list[dict]:
    return sorted(({k: o.get(k) for k in ("source_key", "start_date", "end_date", "precision", "city_id")}
                   for o in occs), key=lambda o: o["source_key"])


def apply_intake(item, n: dict) -> None:
    from apps.intake.models import IntakeItem

    event = item.event
    if event is None and n["normalized_url"]:
        twin = (IntakeItem.objects.filter(source=item.source, normalized_url=n["normalized_url"], event__isnull=False)
                .exclude(pk=item.pk).first())
        if twin:
            event = item.event = twin.event

    gone = n["removed"] or n["status"] == "not_event"
    if gone:
        if event is None:
            return
        _source_gone(event, item, n)
        return

    f = n["event"]
    if event is None:
        event = Event.objects.create(
            state="pending", country=_country(f["country_code"]), review_flags=n["flags"],
            geo_signals=f["geo_signals"], **{k: f[k] for k in IMPORT_FIELDS},
            event_type=EventType.objects.filter(code=f.get("event_type_code") or "", is_active=True).first())
        item.event = event
        _set_occurrences(event, n["occurrences"])
        _ensure_publications(event)
        log("event.imported", event, actor_label=item.source.code, item=str(item))
        return

    event = Event.objects.select_for_update().get(pk=event.pk)
    if event.state == "rejected":
        return                                 # the moderator already said no; a re-import changes nothing

    if event.state in NOT_YET_LIVE:
        for k in IMPORT_FIELDS:
            if k not in event.manual_fields:
                setattr(event, k, f[k])
        if "country" not in event.manual_fields:
            event.country = _country(f["country_code"])
        event.geo_signals = {**event.geo_signals, **f["geo_signals"]}
        event.review_flags = n["flags"]
        event.state = "pending"
        event.save()
        if "occurrences" not in event.manual_fields:
            _set_occurrences(event, n["occurrences"])
        _ensure_publications(event)
        return

    # approved: never overwrite — propose the difference to the moderator
    changes = {k: f[k] for k in IMPORT_FIELDS if k not in event.manual_fields and getattr(event, k) != f[k]}
    if "occurrences" not in event.manual_fields and \
            _occ_comparable(n["occurrences"]) != _occ_comparable(_occ_snapshot(event)):
        changes["occurrences"] = n["occurrences"]
    if not changes:
        return
    event.revisions.filter(origin="import", status="proposed").update(status="superseded",
                                                                      decided_at=timezone.now())
    EventRevision.objects.create(event=event, base_revision=event.revision, origin="import", changes=changes,
                                 priority="occurrences" in changes, source_item=item)


def _source_gone(event: Event, item, n: dict) -> None:
    event = Event.objects.select_for_update().get(pk=event.pk)
    if event.state in NOT_YET_LIVE:
        event.state = "withdrawn"
        event.review_flags = sorted(set(event.review_flags) | {"removed_in_source"})
        event.save(update_fields=["state", "review_flags", "updated_at"])
        log("event.withdrawn_by_source", event, actor_label=item.source.code, reason=n["reason"])
    elif event.state == "approved":
        EventRevision.objects.get_or_create(
            event=event, origin="import", status="proposed", changes={"_removed_in_source": True},
            defaults={"base_revision": event.revision, "priority": True, "source_item": item})


# ── publication ────────────────────────────────────────────────────────────

def publication_problems(event: Event, site: Site) -> list[str]:
    p = []
    if not event.title.strip():
        p.append("немає назви")
    if not (event.source_url or event.registration_url):
        p.append("немає посилання на джерело або реєстрацію")
    if not event.format:
        p.append("не вказано формат")
    if not event.event_type_id:
        p.append("не вказано тип")
    occs = list(event.occurrences.all())
    if not occs:
        p.append("немає жодного сеансу з датою")
    if event.format in ("offline", "hybrid") and any(o.city_id is None for o in occs):
        p.append("для офлайн / гібрид потрібне місто в кожному сеансі")
    codes = site.country_codes()
    if codes and event.country_id not in codes and not (event.format == "online" and site.show_online):
        p.append("подія не належить до географії сайту")
    return p


def approve(event: Event, site: Site, user, *, reason: str = "") -> SitePublication:
    """Publish on one site. The publication and the «new event» announcement are one transaction."""
    from apps.subscriptions.models import Announcement

    with transaction.atomic():
        event = Event.objects.select_for_update().get(pk=event.pk)
        problems = publication_problems(event, site)
        if problems:
            raise PublishError(problems)
        pub, _ = SitePublication.objects.select_for_update().get_or_create(site=site, event=event)
        now = timezone.now()
        first = pub.first_published_at is None
        pub.status, pub.published_at, pub.blocked, pub.reason = "published", now, False, reason
        if first:
            pub.first_published_at = now
        pub.save()
        if event.state != "approved":
            event.state = "approved"
            event.review_flags = []
            event.save(update_fields=["state", "review_flags", "updated_at"])
        if first:
            initial = event.intake_items.filter(initial_load=True).exists()
            future = event.occurrences.filter(end_date__gte=date.today()).exists()
            Announcement.objects.get_or_create(site=site, event=event,
                                               defaults={"suppressed": initial or not future})
        log("publication.approve", pub, actor=user, reason=reason, site=site.code, event=event.pk)
        return pub


def reject(event: Event, site: Site, user, *, reason: str) -> SitePublication:
    with transaction.atomic():
        pub, _ = SitePublication.objects.select_for_update().get_or_create(site=site, event=event)
        pub.status, pub.reason = "rejected", reason
        pub.save()
        if not event.publications.exclude(status="rejected").exists():
            Event.objects.filter(pk=event.pk).update(state="rejected")
        log("publication.reject", pub, actor=user, reason=reason, site=site.code, event=event.pk)
        return pub


def unpublish(event: Event, site: Site, user, *, reason: str) -> SitePublication:
    """Taken down by a moderator: stays down even when the source sends it again."""
    with transaction.atomic():
        pub = SitePublication.objects.select_for_update().get(site=site, event=event)
        pub.status, pub.reason, pub.blocked = "unpublished", reason, True
        pub.save()
        log("publication.unpublish", pub, actor=user, reason=reason, site=site.code, event=event.pk)
        return pub


def save_moderator_edit(event: Event, data: dict, user, *, expected_revision: int) -> Event:
    """A moderator's change: checks the revision number and marks the fields as manual."""
    with transaction.atomic():
        current = Event.objects.select_for_update().get(pk=event.pk)
        if current.revision != expected_revision:
            raise PublishError([f"картку вже змінив хтось інший (версія {current.revision})"])
        for k, v in data.items():
            setattr(current, k, v)
        current.manual_fields = sorted(set(current.manual_fields) | set(data))
        current.revision += 1
        current.save()
        log("event.edit", current, actor=user, fields=sorted(data))
        return current
