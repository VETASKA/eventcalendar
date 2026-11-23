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
        defaults = {"start_date": o["start_date"], "end_date": o["end_date"], "precision": o["precision"],
                    "timezone": tz, "city": City.objects.filter(pk=o.get("city_id")).first()}
        for k in ("starts_at", "ends_at", "venue", "address", "status"):
            if k in o:
                defaults[k] = o[k] or ({"venue": "", "address": "", "status": "scheduled"}.get(k))
        Occurrence.objects.update_or_create(event=event, source_key=o["source_key"], defaults=defaults)
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

    if n["status"] == "queued":
        return                                 # waiting for the page to be fetched: nothing to show yet

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
            event_type=EventType.objects.filter(code=f.get("event_type_code") or "", is_active=True).first(),
            format=f.get("format") or "")
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
        filled = {"no_format": bool(current.format), "no_type": bool(current.event_type_id),
                  "check_title": "title" in data}
        current.review_flags = [f for f in current.review_flags if not filled.get(f)]
        current.revision += 1
        current.save()
        log("event.edit", current, actor=user, fields=sorted(data))
        return current


# ── proposed changes (import / organizer) ─────────────────────────────────────

EDITABLE = {"title", "summary", "format", "registration_url", "price_text", "organizer_name", "organizer_site",
            "source_url", "original_language"}


def _apply_organizer_sessions(event: Event, sessions: list[dict]) -> None:
    """Organizer format: [{id|None, start_date, end_date, starts_at, ends_at, precision, status, city_id, venue,
    deleted}]. Only this event's sessions can be touched."""
    for s in sessions:
        o = event.occurrences.filter(pk=s.get("id")).first() if s.get("id") else None
        if s.get("deleted"):
            if o:
                o.delete()
            continue
        o = o or Occurrence(event=event)
        o.start_date, o.end_date = s["start_date"], s.get("end_date") or s["start_date"]
        o.starts_at, o.ends_at = s.get("starts_at") or None, s.get("ends_at") or None
        o.precision, o.status = s.get("precision") or "date", s.get("status") or "scheduled"
        o.city = City.objects.filter(pk=s.get("city_id")).first() if s.get("city_id") else None
        o.venue = s.get("venue", "")
        o.save()


def apply_revision(rev: EventRevision, user, *, force: bool = False) -> Event:
    """Apply a proposed change. Refuses when the card changed after the proposal was made, unless forced."""
    with transaction.atomic():
        rev = EventRevision.objects.select_for_update().get(pk=rev.pk)
        if rev.status != "proposed":
            raise PublishError(["изменение уже рассмотрено"])
        event = Event.objects.select_for_update().get(pk=rev.event_id)
        if rev.base_revision != event.revision and not force:
            raise PublishError([f"карточка изменилась после предложения (версия {rev.base_revision} → "
                                f"{event.revision}); проверьте и примените ещё раз"])
        ch = rev.changes
        touched = set()
        for k, v in ch.items():
            if k in EDITABLE:
                setattr(event, k, v)
                touched.add(k)
        if "event_type" in ch:
            event.event_type = EventType.objects.filter(code=ch["event_type"]).first()
            touched.add("event_type")
        if "occurrences" in ch:
            if rev.origin == "import":
                _set_occurrences(event, ch["occurrences"])
            else:
                _apply_organizer_sessions(event, ch["occurrences"])
            touched.add("occurrences")
        if ch.get("_removed_in_source"):
            for pub in event.publications.filter(status="published"):
                pub.status, pub.reason, pub.blocked = "unpublished", "удалено в источнике", True
                pub.save()
            event.state = "withdrawn"
        if rev.origin != "import":
            # an organizer's or moderator's version is protected from later imports
            event.manual_fields = sorted(set(event.manual_fields) | touched)
        event.revision += 1
        event.save()
        rev.status, rev.decided_at = "approved", timezone.now()
        rev.save(update_fields=["status", "decided_at"])
        log("revision.apply", event, actor=user, revision=rev.pk, origin=rev.origin, fields=sorted(touched))
    _notify_revision(rev, approved=True)
    return event


def reject_revision(rev: EventRevision, user, reason: str = "") -> None:
    with transaction.atomic():
        rev = EventRevision.objects.select_for_update().get(pk=rev.pk)
        if rev.status != "proposed":
            return
        rev.status, rev.decided_at = "rejected", timezone.now()
        rev.save(update_fields=["status", "decided_at"])
        log("revision.reject", rev.event, actor=user, reason=reason, revision=rev.pk)
    _notify_revision(rev, approved=False, reason=reason)


def _notify_revision(rev: EventRevision, *, approved: bool, reason: str = "") -> None:
    if rev.origin != "organizer" or not rev.author or not rev.author.email:
        return
    from apps.core.i18n import lurl
    from apps.core.mail import send, site_url
    from apps.organizers.models import Profile
    pub = rev.event.publications.select_related("site").first()
    lang = Profile.of(rev.author).lang
    send(rev.author.email, "revision_decided", {"event": rev.event, "approved": approved, "reason": reason,
                                               "cabinet": site_url(pub.site if pub else None, lurl("/cabinet/", lang))},
         lang=lang)
