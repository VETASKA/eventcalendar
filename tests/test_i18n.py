"""Stage 2: three interface languages, city / format filters, sitemap, multi-day and DST."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.catalog import services
from apps.catalog.models import Event, EventType, Occurrence
from apps.geo.models import City
from apps.portals.models import Site
from tests.conftest import harvey_item


def publish(user, **kw):
    from apps.intake.models import EventSource
    from apps.intake.services import receive
    typ = kw.pop("typ", "standup")
    fmt = kw.pop("fmt", "offline")
    receive(EventSource.objects.get(code="harvey"), harvey_item(**kw))
    ev = Event.objects.get(intake_items__external_id=str(kw["eid"]))
    ev.format, ev.event_type = fmt, EventType.objects.get(code=typ)
    ev.save()
    services.approve(ev, Site.objects.get(code="ua"), user)
    return ev


@pytest.fixture
def evs(harvey_token, admin_user):
    return [publish(admin_user, eid=1, name="Стендап у Києві", date="2099-03-14", typ="standup"),
            publish(admin_user, eid=2, name="Стендап у Львові", date="2099-03-15", city="Львов", typ="standup"),
            publish(admin_user, eid=3, name="Онлайн-лекція", date="2099-03-16", city="", typ="lecture", fmt="online")]


def test_languages_and_switcher_keep_filters(client, evs):
    uk = client.get("/?type=standup").content.decode()
    assert '<html lang="uk">' in uk and "Усі міста" in uk and "Запропонувати подію" in uk
    en = client.get("/en/?type=standup").content.decode()
    assert '<html lang="en">' in en and "All cities" in en and "Suggest an event" in en and "Stand-up" in en
    pl = client.get("/pl/").content.decode()
    assert '<html lang="pl">' in pl and "Wszystkie miasta" in pl and "Zaproponuj wydarzenie" in pl
    # the switcher keeps the filter, hreflang alternates are there
    assert 'href="/en/?type=standup"' in uk and 'href="/pl/?type=standup"' in uk and 'href="/?type=standup"' in en
    assert 'hreflang="pl"' in uk
    # the browser language does not override the URL: no prefix = Ukrainian
    assert '<html lang="uk">' in client.get("/", HTTP_ACCEPT_LANGUAGE="en").content.decode()


def test_event_page_in_three_languages(client, evs):
    e = evs[0]
    uk = client.get(f"/events/{e.pk}-{e.slug}/").content.decode()
    en = client.get(f"/en/events/{e.pk}-{e.slug}/").content.decode()
    pl = client.get(f"/pl/events/{e.pk}-{e.slug}/").content.decode()
    assert "14 березня 2099" in uk and "Час уточнюється".lower() in uk.lower()
    assert "14 March 2099" in en and "Back to calendar" in en and "Kyiv" in en
    assert "14 marca 2099" in pl and "Kijów" in pl and "To moje wydarzenie" in pl
    # the switcher on a card points to the same card
    assert f'href="/en/events/{e.pk}-' in uk and f'href="/pl/events/{e.pk}-' in uk


def test_api_language(client, evs):
    r = client.get("/api/v1/events?from=2099-03-01&to=2099-04-01&lang=en").json()["events"]
    first = r[0]
    assert first["city"] == "Kyiv" and first["type"] == "Stand-up" and first["date_label"] == "14 March 2099"
    assert first["url"].startswith("/en/events/")
    uk = client.get("/api/v1/events?from=2099-03-01&to=2099-04-01").json()["events"][0]
    assert uk["city"] == "Київ" and uk["url"].startswith("/events/")


def test_city_and_format_filters_agree_in_calendar_and_list(client, evs):
    kyiv = City.objects.get(name="Київ")
    html = client.get("/").content.decode()
    assert f'name="city" value="{kyiv.pk}"' in html and 'name="format" value="online"' in html
    rng = "from=2099-03-01&to=2099-04-01"
    got = client.get(f"/api/v1/events?{rng}&city={kyiv.pk}&type=standup").json()["events"]
    assert [e["title"] for e in got] == ["Стендап у Києві"]
    assert [e["title"] for e in client.get(f"/api/v1/events?{rng}&format=online").json()["events"]] == ["Онлайн-лекція"]
    # «Київ + Стендап» link reproduces the choice
    page = client.get(f"/?city={kyiv.pk}&type=standup").content.decode()
    assert f'value="{kyiv.pk}" checked' in page and 'value="standup" checked' in page


def test_sitemap_and_robots(client, evs, admin_user):
    services.unpublish(evs[2], Site.objects.get(code="ua"), admin_user, reason="t")
    xml = client.get("/sitemap.xml").content.decode()
    assert f"/events/{evs[0].pk}-" in xml and f"/en/events/{evs[0].pk}-" in xml and 'hreflang="pl"' in xml
    assert f"/events/{evs[2].pk}-" not in xml                    # unpublished never in the sitemap
    robots = client.get("/robots.txt").content.decode()
    assert "Sitemap: http://testserver/sitemap.xml" in robots and "Disallow: /admin/" in robots


def test_multiday_event_in_every_day_of_its_range(client, evs, admin_user):
    e = publish(admin_user, eid=9, name="Фестиваль три дні", date="2099-04-29", end_date="2099-05-01", typ="festival")
    april = client.get("/api/v1/events?from=2099-04-01&to=2099-05-01").json()["events"]
    may = client.get("/api/v1/events?from=2099-05-01&to=2099-06-01").json()["events"]
    assert [x["title"] for x in april] == ["Фестиваль три дні"] == [x["title"] for x in may]
    assert april[0]["end"] == "2099-05-02"            # FullCalendar's end is exclusive
    assert "29 квітня 2099 — 1 травня 2099" in client.get(f"/events/{e.pk}-{e.slug}/").content.decode()


def test_daylight_saving_switch(client, evs):
    """Kyiv moves clocks forward on 28.03.2027 at 03:00: 10:00 local is 07:00 UTC, the day before 08:00 UTC."""
    kyiv = ZoneInfo("Europe/Kyiv")
    e = evs[0]
    o = e.occurrences.get()
    o.start_date = o.end_date = datetime(2027, 3, 28).date()
    o.precision = "datetime"
    o.starts_at = datetime(2027, 3, 28, 10, 0, tzinfo=kyiv)
    o.ends_at = datetime(2027, 3, 28, 12, 0, tzinfo=kyiv)
    o.save()
    Occurrence.objects.create(event=e, start_date="2027-03-27", end_date="2027-03-27", precision="datetime",
                              starts_at=datetime(2027, 3, 27, 10, 0, tzinfo=kyiv), city=o.city)
    got = client.get("/api/v1/events?from=2027-03-01&to=2027-04-01").json()["events"]
    starts = sorted(datetime.fromisoformat(x["start"]).astimezone(ZoneInfo("UTC")).hour for x in got)
    assert starts == [7, 8]
    html = client.get(f"/events/{e.pk}-{e.slug}/").content.decode()
    assert "10:00–12:00" in html and "10:00" in html
