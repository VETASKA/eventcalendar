import threading

import pytest
from django.db import connection

from apps.catalog import services
from apps.catalog.models import Event, EventRevision, EventType, Occurrence, SitePublication
from apps.intake.models import IntakeItem
from apps.portals.models import Site
from apps.subscriptions.models import Announcement
from tests.conftest import harvey_item


def results(r):
    assert r.status_code == 200, r.content
    return r.json()["results"]


def test_auth_and_schema(client, push):
    assert push([harvey_item()], token="wrong").status_code == 401
    r = client.post("/api/v1/intake/events", data={"schema": 99, "items": [{}]}, content_type="application/json")
    assert r.status_code == 401
    assert client.get("/api/v1/intake/events").status_code == 405


def test_new_event_goes_to_moderation_with_city_from_russian_alias(push):
    res = results(push([harvey_item()]))
    assert res[0]["result"] == "created" and res[0]["status"] == "event_detected"
    ev = Event.objects.get()
    assert ev.state == "pending" and ev.country_id == "UA"
    occ = ev.occurrences.get()
    assert occ.city.name == "Київ" and occ.precision == "date" and str(occ.start_date) == "2027-03-14"
    assert set(ev.review_flags) >= {"no_format", "no_type"}
    assert ev.geo_signals["ua_phone"] and ev.geo_signals["lang_uk"]
    assert SitePublication.objects.get(event=ev).status == "pending"


def test_same_batch_twice_keeps_one_card_and_its_sessions(push):
    batch = [harvey_item(1), harvey_item(2, city="Львов")]
    results(push(batch))
    res = results(push(batch))
    assert [r["result"] for r in res] == ["unchanged", "unchanged"]
    assert Event.objects.count() == 2 and Occurrence.objects.count() == 2 and IntakeItem.objects.count() == 2


def test_only_volatile_change_is_unchanged(push):
    results(push([harvey_item()]))
    assert results(push([harvey_item(updated_at="2026-11-22T00:00:00Z")]))[0]["result"] == "unchanged"


def test_not_event_is_stored_without_card(push):
    res = results(push([harvey_item(kind="not_event", kind_why="нет: дата")]))
    assert res[0]["status"] == "not_event" and res[0]["event_id"] is None
    assert IntakeItem.objects.get().reason == "нет: дата"


def test_unknown_city_and_no_date_flagged(push):
    results(push([harvey_item(city="Буковель", date=None)]))
    ev = Event.objects.get()
    assert "city_unknown" in ev.review_flags and "no_date" in ev.review_flags
    assert not ev.occurrences.exists()


def test_maybe_needs_review(push):
    assert results(push([harvey_item(kind="maybe")]))[0]["status"] == "needs_review"


def _make_publishable(ev):
    ev.format = "offline"
    ev.event_type = EventType.objects.get(code="forum")
    ev.save()


def test_reimport_of_draft_updates_but_keeps_manual_fields(push, admin_user):
    results(push([harvey_item()]))
    ev = Event.objects.get()
    services.save_moderator_edit(ev, {"title": "Ручна назва"}, admin_user, expected_revision=1)
    results(push([harvey_item(name="Нова назва з джерела", price_text="700 грн")]))
    ev.refresh_from_db()
    assert ev.title == "Ручна назва" and ev.price_text == "700 грн"


def test_concurrent_edit_is_refused(push, admin_user):
    results(push([harvey_item()]))
    ev = Event.objects.get()
    services.save_moderator_edit(ev, {"title": "A"}, admin_user, expected_revision=1)
    with pytest.raises(services.PublishError):
        services.save_moderator_edit(ev, {"title": "B"}, admin_user, expected_revision=1)


def test_approve_initial_load_suppresses_announcement(push, admin_user):
    results(push([harvey_item()], initial=True))
    ev = Event.objects.get()
    site = Site.objects.get(code="ua")
    with pytest.raises(services.PublishError):
        services.approve(ev, site, admin_user)          # no format / type yet
    _make_publishable(ev)
    pub = services.approve(ev, site, admin_user)
    assert pub.status == "published"
    assert Announcement.objects.get(event=ev).suppressed is True


def test_approve_regular_event_announces(push, admin_user):
    results(push([harvey_item()]))
    ev = Event.objects.get()
    _make_publishable(ev)
    services.approve(ev, Site.objects.get(code="ua"), admin_user)
    assert Announcement.objects.get(event=ev).suppressed is False


def test_reimport_of_published_event_proposes_revision(push, admin_user):
    results(push([harvey_item()]))
    ev = Event.objects.get()
    _make_publishable(ev)
    services.approve(ev, Site.objects.get(code="ua"), admin_user)
    results(push([harvey_item(date="2027-04-01", price_text="900 грн")]))
    ev.refresh_from_db()
    assert str(ev.occurrences.get().start_date) == "2027-03-14" and ev.price_text == "500 грн"
    rev = EventRevision.objects.get(event=ev, status="proposed")
    assert rev.priority and rev.changes["price_text"] == "900 грн" and "occurrences" in rev.changes
    results(push([harvey_item(date="2027-04-02")]))
    assert EventRevision.objects.filter(event=ev, status="proposed").count() == 1


def test_removed_in_source(push, admin_user):
    results(push([harvey_item(1), harvey_item(2)]))
    e1, e2 = Event.objects.order_by("id")
    _make_publishable(e2)
    services.approve(e2, Site.objects.get(code="ua"), admin_user)
    results(push([harvey_item(1, removed=True), harvey_item(2, removed=True)]))
    e1.refresh_from_db(); e2.refresh_from_db()
    assert e1.state == "withdrawn" and e2.state == "approved"
    assert EventRevision.objects.get(event=e2).changes == {"_removed_in_source": True}


def test_unpublished_stays_blocked_on_reimport(push, admin_user):
    results(push([harvey_item()]))
    ev = Event.objects.get()
    _make_publishable(ev)
    site = Site.objects.get(code="ua")
    services.approve(ev, site, admin_user)
    services.unpublish(ev, site, admin_user, reason="дубль")
    results(push([harvey_item(name="Інша назва")]))
    pub = SitePublication.objects.get(event=ev)
    assert pub.status == "unpublished" and pub.blocked


def test_foreign_country_not_on_ua_site(push):
    results(push([harvey_item(country="PL", city="Варшава")]))
    assert not SitePublication.objects.exists()


def test_bad_item_does_not_lose_batch(push):
    res = results(push([{"name": "без id"}, harvey_item(5)]))
    assert res[0]["result"] == "error" and res[1]["result"] == "created"


@pytest.mark.django_db(transaction=True)
def test_parallel_delivery_creates_one_card(client, ref):
    from apps.intake.models import EventSource
    from apps.intake.services import receive
    src = EventSource.objects.create(code="harvey", name="H")
    errors = []

    def go():
        try:
            receive(src, harvey_item(7))
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            connection.close()

    threads = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert IntakeItem.objects.count() == 1 and Event.objects.count() == 1 and Occurrence.objects.count() == 1
