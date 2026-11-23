"""Organizer rights: given only by a moderator's decision on a claim (spec §6)."""
from django.db import transaction
from django.utils import timezone

from apps.audit.models import log

from .models import Claim, EventGrant, Membership, Organization


def user_events(user):
    """Events this user may manage: granted to an organization they belong to, not revoked."""
    from apps.catalog.models import Event
    return Event.objects.filter(grants__organization__members__user=user, grants__revoked_at__isnull=True).distinct()


def approve_claim(claim: Claim, moderator, note: str = "") -> EventGrant:
    with transaction.atomic():
        claim = Claim.objects.select_for_update().select_related("event", "user").get(pk=claim.pk)
        org = claim.organization
        if org is None:
            org = (Organization.objects.filter(members__user=claim.user, name__iexact=claim.org_name).first()
                   or Organization.objects.create(name=claim.org_name or claim.user.get_full_name() or claim.user.email,
                                                  website=claim.event.organizer_site))
            claim.organization = org
        Membership.objects.get_or_create(organization=org, user=claim.user, defaults={"role": "owner"})
        grant = EventGrant.objects.filter(event=claim.event, organization=org, revoked_at__isnull=True).first() \
            or EventGrant.objects.create(event=claim.event, organization=org, granted_by=moderator, claim=claim)
        claim.status, claim.decision_note = "approved", note
        claim.save()
        if claim.event.organization_id is None:
            claim.event.organization = org
            claim.event.save(update_fields=["organization", "updated_at"])
        log("claim.approve", claim, actor=moderator, reason=note, event=claim.event_id, organization=org.pk)
    _notify(claim, approved=True, note=note)
    return grant


def reject_claim(claim: Claim, moderator, note: str) -> None:
    with transaction.atomic():
        claim = Claim.objects.select_for_update().get(pk=claim.pk)
        claim.status, claim.decision_note = "rejected", note
        claim.save()
        log("claim.reject", claim, actor=moderator, reason=note, event=claim.event_id)
    _notify(claim, approved=False, note=note)


def _notify(claim, *, approved: bool, note: str) -> None:
    from apps.core.i18n import lurl
    from apps.core.mail import send, site_url

    from .models import Profile
    if not claim.user.email:
        return
    lang = Profile.of(claim.user).lang
    pub = claim.event.publications.select_related("site").first()
    send(claim.user.email, "claim_decided", {"event": claim.event, "approved": approved, "note": note,
                                             "cabinet": site_url(pub.site if pub else None, lurl("/cabinet/", lang))},
         lang=lang)


def revoke(grant: EventGrant, moderator, reason: str) -> None:
    grant.revoked_at = timezone.now()
    grant.save(update_fields=["revoked_at"])
    log("grant.revoke", grant, actor=moderator, reason=reason, event=grant.event_id)
