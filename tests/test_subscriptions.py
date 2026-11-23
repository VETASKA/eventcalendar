"""Stage 5: subscriptions, weekly digest, reminders, changes, unsubscribe; Telegram ready for the bot token."""
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.catalog import services
from apps.catalog.models import Event, EventType
from apps.geo.models import City
from apps.portals.models import Site
from apps.subscriptions import tasks, telegram
from apps.subscriptions.models import Announcement, Delivery, Reminder, Subscription
from tests.conftest import harvey_item

KYIV = ZoneInfo("Europe/Kyiv")


@pytest.fixture(autouse=True)
def _clear():
    cache.clear()


def publish(user, eid, typ="standup", **kw):
    from apps.intake.models import EventSource
    from apps.intake.services import receive
    receive(EventSource.objects.get(code="harvey"), harvey_item(eid, **kw))
    ev = Event.objects.get(intake_items__external_id=str(eid))
    ev.format, ev.event_type = "offline", EventType.objects.get(code=typ)
    ev.save()
    services.approve(ev, Site.objects.get(code="ua"), user)
    return ev


def confirm_from(mail):
    return re.search(r"/(?:\w\w/)?subscribe/confirm/\S+/", mail.body).group(0)


@pytest.fixture
def site(harvey_token):
    return Site.objects.get(code="ua")


def test_email_subscription_needs_confirmation(client, site, mailoutbox):
    client.post("/subscribe/", {"channel": "email", "email": "Fan@Ex.ua", "type": ["standup"]})
    sub = Subscription.objects.get()
    assert sub.status == "pending" and sub.address == "fan@ex.ua"
    assert len(mailoutbox) == 1 and "Підтвердіть підписку" in mailoutbox[0].subject
    client.get(confirm_from(mailoutbox[0]))
    sub.refresh_from_db()
    assert sub.status == "active" and sub.filters == {"type": ["standup"]} and sub.consent_at


def test_digest_follows_filters_and_language(client, site, admin_user, mailoutbox, django_capture_on_commit_callbacks):
    kyiv, lviv = City.objects.get(name="Київ"), City.objects.get(name="Львів")
    fan = Subscription.objects.create(site=site, channel="email", address="fan@ex.ua", status="active", lang="en",
                                      filters={"type": ["standup"]}, consent_at=timezone.now() - timedelta(days=1))
    kyivan = Subscription.objects.create(site=site, channel="email", address="k@ex.ua", status="active", lang="uk",
                                         filters={"city": [kyiv.pk]}, consent_at=timezone.now() - timedelta(days=1))
    publish(admin_user, 1, typ="standup", name="Стендап у Львові", city="Львов", date="2099-03-01")
    publish(admin_user, 2, typ="concert", name="Концерт у Києві", date="2099-03-02")
    tasks.send_digests()
    by = {m.to[0]: m for m in mailoutbox}
    assert "Стендап у Львові" in by["fan@ex.ua"].body and "Концерт" not in by["fan@ex.ua"].body
    assert "New events in the calendar" in by["fan@ex.ua"].subject and "/en/events/" in by["fan@ex.ua"].body
    assert "Концерт у Києві" in by["k@ex.ua"].body and "Стендап" not in by["k@ex.ua"].body
    assert "/unsubscribe/" in by["k@ex.ua"].body and by["k@ex.ua"].extra_headers["List-Unsubscribe-Post"]
    # the same week again: nothing new, nothing sent twice
    n = len(mailoutbox)
    tasks.send_digests()
    assert len(mailoutbox) == n
    assert lviv


def test_first_upload_is_never_in_a_digest(client, site, admin_user, mailoutbox):
    Subscription.objects.create(site=site, channel="email", address="a@ex.ua", status="active",
                                consent_at=timezone.now() - timedelta(days=1))
    from apps.intake.models import EventSource
    from apps.intake.services import receive
    receive(EventSource.objects.get(code="harvey"), harvey_item(5, date="2099-03-01"), initial_load=True)
    ev = Event.objects.get()
    ev.format, ev.event_type = "offline", EventType.objects.get(code="forum")
    ev.save()
    services.approve(ev, site, admin_user)
    assert Announcement.objects.get().suppressed
    tasks.send_digests()
    assert not mailoutbox


def test_reminder_a_day_before_the_chosen_session(client, site, admin_user, mailoutbox):
    ev = publish(admin_user, 1, date="2099-03-14")
    o = ev.occurrences.get()
    o.precision, o.starts_at = "datetime", datetime(2099, 3, 14, 19, 0, tzinfo=KYIV)
    o.save()
    client.post("/remind/", {"occurrence": o.pk, "email": "me@ex.ua"})
    r = Reminder.objects.get()
    assert r.send_at == datetime(2099, 3, 13, 19, 0, tzinfo=KYIV) and r.status == "scheduled"
    client.get(confirm_from(mailoutbox[0]))
    assert Subscription.objects.get().status == "active"
    # not yet due
    assert tasks.send_due_reminders() == 0
    Reminder.objects.update(send_at=timezone.now() - timedelta(minutes=1))
    assert tasks.send_due_reminders() == 1
    assert "Завтра" in mailoutbox[-1].subject and "19:00" in mailoutbox[-1].body
    assert tasks.send_due_reminders() == 0                                   # never twice


def test_unsubscribe_before_sending_wins(client, site, admin_user, mailoutbox):
    ev = publish(admin_user, 1, date="2099-03-14")
    sub = Subscription.objects.create(site=site, channel="email", address="me@ex.ua", status="active")
    r = Reminder.objects.create(subscription=sub, occurrence=ev.occurrences.get(),
                                send_at=timezone.now() - timedelta(minutes=1))
    from apps.subscriptions.tokens import unsubscribe_token
    url = f"/unsubscribe/{unsubscribe_token(sub)}/"
    assert "Відписатися від розсилки" in client.get(url).content.decode()
    assert Subscription.objects.get().status == "active"           # a GET (link preview) changes nothing
    client.post(url, {"List-Unsubscribe": "One-Click"})              # the mail client's one-click
    assert Subscription.objects.get().status == "stopped"
    assert tasks.send_due_reminders() == 0 and not mailoutbox
    r.refresh_from_db()
    assert r.status == "cancelled"


def test_moved_date_moves_the_reminder_and_tells_the_person(client, site, admin_user, mailoutbox,
                                                            django_capture_on_commit_callbacks):
    ev = publish(admin_user, 1, date="2099-03-14")
    o = ev.occurrences.get()
    sub = Subscription.objects.create(site=site, channel="email", address="me@ex.ua", status="active")
    r = Reminder.objects.create(subscription=sub, occurrence=o, send_at=datetime(2099, 3, 13, 10, 0, tzinfo=KYIV))
    with django_capture_on_commit_callbacks(execute=True):
        o.start_date = o.end_date = datetime(2099, 4, 2).date()
        o.status = "rescheduled"
        o.save()
    r.refresh_from_db()
    assert r.send_at == datetime(2099, 4, 1, 10, 0, tzinfo=KYIV) and r.status == "scheduled"
    assert "Змінено дату" in mailoutbox[-1].subject and "2 квітня 2099" in mailoutbox[-1].body
    with django_capture_on_commit_callbacks(execute=True):
        o.status = "cancelled"
        o.save()
    r.refresh_from_db()
    assert r.status == "cancelled" and "Скасовано" in mailoutbox[-1].subject


def test_too_late_for_a_reminder(client, site, admin_user):
    ev = publish(admin_user, 1, date=(timezone.localdate() + timedelta(days=0)).isoformat())
    client.post("/remind/", {"occurrence": ev.occurrences.get().pk, "email": "me@ex.ua"})
    assert not Reminder.objects.exists()


def test_subscriptions_are_per_site(client, site, admin_user, mailoutbox):
    from apps.geo.models import Country
    pl_site = Site.objects.create(code="pl", name="EventCalendar Polska")
    pl_site.countries.add(Country.objects.get(code="PL"))
    Subscription.objects.create(site=pl_site, channel="email", address="pl@ex.pl", status="active",
                                consent_at=timezone.now() - timedelta(days=1))
    publish(admin_user, 1, date="2099-03-01")                                # a Ukrainian event
    tasks.send_digests()
    assert not [m for m in mailoutbox if m.to == ["pl@ex.pl"]]


def test_telegram_off_without_token(client, site):
    html = client.get("/").content.decode()
    assert 'data-ch="telegram"' not in html
    client.post("/subscribe/", {"channel": "telegram", "city": []})
    assert not Subscription.objects.exists()
    assert client.post("/telegram/webhook/x/", data="{}", content_type="application/json").status_code == 403


def test_telegram_subscription_for_kyiv(client, site, settings, monkeypatch, admin_user):
    settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_BOT_NAME, settings.TELEGRAM_WEBHOOK_SECRET = "1:AA", "ec_bot", "s3cret"
    sent = []
    monkeypatch.setattr(telegram, "send_message", lambda chat, text: sent.append((chat, text)) or "1")
    kyiv = City.objects.get(name="Київ")
    assert 'data-ch="telegram"' in client.get("/").content.decode()
    r = client.post("/subscribe/", {"channel": "telegram", "city": [str(kyiv.pk)]})
    sub = Subscription.objects.get()
    assert r["Location"] == f"https://t.me/ec_bot?start={sub.link_token}" and sub.status == "pending"
    upd = {"message": {"chat": {"id": 777}, "text": f"/start {sub.link_token}"}}
    bad = client.post("/telegram/webhook/s3cret/", data=json.dumps(upd), content_type="application/json")
    assert bad.status_code == 403                                           # header secret missing
    client.post("/telegram/webhook/s3cret/", data=json.dumps(upd), content_type="application/json",
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="s3cret")
    sub.refresh_from_db()
    assert sub.status == "active" and sub.address == "777" and sub.filters == {"city": [kyiv.pk]}
    Subscription.objects.filter(pk=sub.pk).update(consent_at=timezone.now() - timedelta(days=1))
    publish(admin_user, 1, name="Подія в Києві", date="2099-03-01")
    tasks.send_digests()
    assert any(chat == "777" and "Подія в Києві" in text for chat, text in sent)
    client.post("/telegram/webhook/s3cret/", data=json.dumps({"message": {"chat": {"id": 777}, "text": "/stop"}}),
                content_type="application/json", HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="s3cret")
    sub.refresh_from_db()
    assert sub.status == "stopped"


def test_delivery_journal_is_idempotent(site):
    from apps.subscriptions.delivery import deliver
    sub = Subscription.objects.create(site=site, channel="email", address="x@ex.ua", status="active")
    a = deliver(sub, "digest", "k1", "digest", {"rows": [], "more": 0, "home": "/"})
    b = deliver(sub, "digest", "k1", "digest", {"rows": [], "more": 0, "home": "/"})
    assert a.pk == b.pk and Delivery.objects.count() == 1 and b.attempts == 1
