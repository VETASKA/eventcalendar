"""Stage 4: email confirmation, proving control of the event's site, organizer edits through moderation."""
import re
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone

from apps.catalog import services
from apps.catalog.models import Event, EventRevision, EventType
from apps.intake.fetcher import FetchResult
from apps.organizers import verification as V
from apps.organizers.models import Claim, Profile
from apps.organizers.services import approve_claim, user_events
from apps.portals.models import Site
from tests.conftest import harvey_item


@pytest.fixture(autouse=True)
def _clear():
    cache.clear()


def publish(user, eid, **kw):
    from apps.intake.models import EventSource
    from apps.intake.services import receive
    receive(EventSource.objects.get(code="harvey"), harvey_item(eid, **kw))
    ev = Event.objects.get(intake_items__external_id=str(eid))
    ev.format, ev.event_type = "offline", EventType.objects.get(code="forum")
    ev.save()
    services.approve(ev, Site.objects.get(code="ua"), user)
    return ev


@pytest.fixture
def ev(harvey_token, admin_user):
    return publish(admin_user, 1, url="https://www.forum.com.ua/2099", date="2099-03-14")


@pytest.fixture
def organizer(client):
    u = User.objects.create_user(username="org@forum.com.ua", email="org@forum.com.ua", password="long-enough-pass-1",
                                 first_name="Ірина")
    Profile.objects.create(user=u, email_verified=True)
    client.force_login(u)
    return u


def make_claim(client, ev, method):
    client.post(f"/events/{ev.pk}/claim/", {"org_name": "Forum UA", "role": "організатор", "phone": "+380501112233",
                                            "evidence": "", "method": method})
    return Claim.objects.get(event=ev)


# ── email confirmation and password reset ────────────────────────────────────

def test_registration_sends_confirmation_and_link_confirms(client, ev, mailoutbox):
    client.post("/cabinet/register/", {"name": "Петро", "email": "petro@ex.ua", "password": "long-enough-pass-1"})
    p = Profile.objects.get(user__email="petro@ex.ua")
    assert not p.email_verified and len(mailoutbox) == 1 and "Підтвердіть email" in mailoutbox[0].subject
    assert "Підтвердіть email" in client.get("/cabinet/").content.decode()
    link = re.search(r"/cabinet/verify/\S+/", mailoutbox[0].body).group(0)
    client.get(link)
    p.refresh_from_db()
    assert p.email_verified
    assert client.get("/cabinet/verify/garbage/")["Location"] == "/cabinet/"


def test_english_registration_gets_english_mail(client, ev, mailoutbox):
    client.post("/en/cabinet/register/", {"name": "Ann", "email": "ann@ex.com", "password": "long-enough-pass-1"})
    assert mailoutbox[0].subject == "Confirm your email at EventCalendar" and "/en/cabinet/verify/" in mailoutbox[0].body


def test_password_reset(client, ev, mailoutbox):
    User.objects.create_user(username="a@ex.ua", email="a@ex.ua", password="old-password-123")
    client.post("/cabinet/password/reset/", {"email": "a@ex.ua"})
    link = re.search(r"/cabinet/password/[^/\s]+/[^/\s]+/", mailoutbox[0].body).group(0)
    r = client.get(link, follow=True)
    form_url = r.redirect_chain[-1][0]
    client.post(form_url, {"new_password1": "brand-new-pass-456", "new_password2": "brand-new-pass-456"})
    assert User.objects.get(email="a@ex.ua").check_password("brand-new-pass-456")


# ── proving control of the site ─────────────────────────────────────────────

def test_file_with_valid_token_verifies_the_host(client, ev, organizer, monkeypatch):
    claim = make_claim(client, ev, "file")
    assert claim.host == "forum.com.ua"
    token = V.file_token(claim)
    page = client.get(f"/cabinet/claims/{claim.pk}/").content.decode()
    assert token in page and "https://forum.com.ua/eventcalendar-verify.txt" in page
    seen = []

    def fetch(url, **kw):
        seen.append(url)
        return FetchResult(True, url, html=f"other line\n{token}\n", status=200)
    monkeypatch.setattr("apps.intake.fetcher.safe_fetch", fetch)
    client.post(f"/cabinet/claims/{claim.pk}/", {"action": "check_file"})
    claim.refresh_from_db()
    assert seen == ["https://forum.com.ua/eventcalendar-verify.txt"] and claim.status == "verified"
    assert not user_events(organizer).exists()                    # control confirmed, rights still by moderator
    # the token cannot be used again
    ok, why = V.check_file(claim, fetch=fetch)
    assert not ok and why == "used"


def test_file_rejected_when_expired_wrong_or_on_another_host(ev, organizer, client):
    claim = make_claim(client, ev, "file")
    token = V.file_token(claim)
    good = lambda url, **kw: FetchResult(True, url, html=token)                                     # noqa: E731
    other_host = lambda url, **kw: FetchResult(True, "https://evil.example/eventcalendar-verify.txt", html=token)  # noqa: E731
    other_token = lambda url, **kw: FetchResult(True, url, html="ec-0000")                         # noqa: E731
    missing = lambda url, **kw: FetchResult(False, url, status=404, error="HTTP 404")              # noqa: E731
    assert V.check_file(claim, fetch=other_host) == (False, "other_host")
    assert V.check_file(claim, fetch=other_token) == (False, "wrong_token")
    assert V.check_file(claim, fetch=missing) == (False, "not_found")
    Claim.objects.filter(pk=claim.pk).update(created_at=timezone.now() - timedelta(days=8))
    claim.refresh_from_db()
    assert V.check_file(claim, fetch=good) == (False, "expired")
    # another claim's token never matches this one
    other = Claim.objects.create(user=organizer, event=ev, method="file", host="forum.com.ua")
    assert V.file_token(other) != token


def test_corporate_email_one_time_link(client, ev, organizer, mailoutbox):
    claim = make_claim(client, ev, "email")
    r = client.post(f"/cabinet/claims/{claim.pk}/", {"action": "send_email", "email": "me@gmail.com"})
    assert "публічна пошта" in r.content.decode() and not mailoutbox
    r = client.post(f"/cabinet/claims/{claim.pk}/", {"action": "send_email", "email": "me@other.com"})
    assert "forum.com.ua" in r.content.decode() and not mailoutbox
    client.post(f"/cabinet/claims/{claim.pk}/", {"action": "send_email", "email": "pr@forum.com.ua"})
    assert mailoutbox[0].to == ["pr@forum.com.ua"]
    link = re.search(r"/cabinet/claims/confirm/\S+/", mailoutbox[0].body).group(0)
    client.get(link)
    claim.refresh_from_db()
    assert claim.status == "verified" and claim.method == "email"
    # second click does nothing
    Claim.objects.filter(pk=claim.pk).update(status="open")
    client.get(link)
    claim.refresh_from_db()
    assert claim.status == "open"


# ── organizer edits ─────────────────────────────────────────────────────────

def edit_payload(ev, **over):
    o = ev.occurrences.get()
    data = {"title": ev.title, "summary": "", "format": "offline", "event_type": "forum", "registration_url": "",
            "price_text": ev.price_text, "s-TOTAL_FORMS": "2", "s-INITIAL_FORMS": "1", "s-MIN_NUM_FORMS": "0",
            "s-MAX_NUM_FORMS": "20", "s-0-id": str(o.pk), "s-0-start_date": str(o.start_date), "s-0-end_date": "",
            "s-0-start_time": "", "s-0-end_time": "", "s-0-city": str(o.city_id or ""), "s-0-venue": "",
            "s-0-status": "scheduled", "s-1-start_date": "", "s-1-status": "scheduled"}
    data.update(over)
    return data


def test_organizer_edits_go_through_moderation_and_survive_reimport(client, ev, organizer, admin_user, mailoutbox):
    claim = Claim.objects.create(user=organizer, event=ev, method="manual", org_name="Forum UA")
    approve_claim(claim, admin_user)
    assert client.get(f"/cabinet/events/{ev.pk}/edit/").status_code == 200
    client.post(f"/cabinet/events/{ev.pk}/edit/", edit_payload(
        ev, title="Форум 2099: нова назва", price_text="1200 грн", **{"s-0-start_time": "10:00", "s-0-end_time": "18:00",
                                                                     "s-0-venue": "Арсенал"}))
    rev = EventRevision.objects.get(origin="organizer")
    assert rev.status == "proposed" and rev.priority and rev.author == organizer
    ev.refresh_from_db()
    assert ev.title != "Форум 2099: нова назва"                      # nothing public before the moderator
    assert "зміни на перевірці" in client.get("/cabinet/").content.decode()
    services.apply_revision(rev, admin_user)
    ev.refresh_from_db()
    o = ev.occurrences.get()
    assert ev.title == "Форум 2099: нова назва" and ev.price_text == "1200 грн"
    assert o.precision == "datetime" and o.venue == "Арсенал" and o.starts_at.hour == 8      # 10:00 Kyiv in UTC
    assert "Ваші зміни опубліковано" in mailoutbox[-1].subject
    # a new import from Harvey does not overwrite the approved edits
    from apps.intake.models import EventSource
    from apps.intake.services import receive
    receive(EventSource.objects.get(code="harvey"),
            harvey_item(1, url="https://www.forum.com.ua/2099", date="2099-03-14", name="Стара назва з джерела",
                        price_text="999 грн"))
    ev.refresh_from_db()
    assert ev.title == "Форум 2099: нова назва" and ev.price_text == "1200 грн"
    assert not EventRevision.objects.filter(origin="import", status="proposed",
                                            changes__has_key="title").exists()


def test_cancellation_by_organizer_is_urgent(client, ev, organizer, admin_user):
    approve_claim(Claim.objects.create(user=organizer, event=ev, method="manual"), admin_user)
    client.post(f"/cabinet/events/{ev.pk}/edit/", edit_payload(ev, **{"s-0-status": "cancelled"}))
    rev = EventRevision.objects.get(origin="organizer")
    assert rev.priority and rev.changes["occurrences"][0]["status"] == "cancelled"


def test_someone_elses_event_is_not_editable(client, ev, organizer, admin_user):
    other = publish(admin_user, 2, url="https://other.ua/e", date="2099-04-01")
    approve_claim(Claim.objects.create(user=organizer, event=ev, method="manual"), admin_user)
    assert client.get(f"/cabinet/events/{other.pk}/edit/").status_code == 404
    assert client.post(f"/cabinet/events/{other.pk}/edit/", edit_payload(other, title="X")).status_code == 404
    assert not EventRevision.objects.filter(event=other).exists()


def test_stale_revision_is_refused(client, ev, organizer, admin_user):
    approve_claim(Claim.objects.create(user=organizer, event=ev, method="manual"), admin_user)
    client.post(f"/cabinet/events/{ev.pk}/edit/", edit_payload(ev, title="A"))
    rev = EventRevision.objects.get(origin="organizer")
    services.save_moderator_edit(ev, {"summary": "модератор змінив"}, admin_user, expected_revision=ev.revision)
    with pytest.raises(services.PublishError):
        services.apply_revision(rev, admin_user)


def test_admin_revision_screen_and_apply_action(admin_client, client, ev, organizer, admin_user):
    approve_claim(Claim.objects.create(user=organizer, event=ev, method="manual"), admin_user)
    client.post(f"/cabinet/events/{ev.pk}/edit/", edit_payload(ev, title="Нова назва", **{"s-0-status": "cancelled"}))
    rev = EventRevision.objects.get(origin="organizer")
    page = admin_client.get(f"/admin/catalog/eventrevision/{rev.pk}/change/").content.decode()
    assert "Нова назва" in page and "отменено" in page and "было" in page
    assert admin_client.get("/admin/catalog/eventrevision/").status_code == 200
    admin_client.post("/admin/catalog/eventrevision/", {"action": "apply", "_selected_action": [rev.pk]})
    ev.refresh_from_db()
    assert ev.title == "Нова назва" and ev.occurrences.get().status == "cancelled"


def test_edit_form_shows_current_values(client, ev, organizer, admin_user):
    approve_claim(Claim.objects.create(user=organizer, event=ev, method="manual"), admin_user)
    html = client.get(f"/cabinet/events/{ev.pk}/edit/").content.decode()
    assert 'name="s-0-start_date" value="2099-03-14"' in html            # browsers need ISO dates in date inputs
