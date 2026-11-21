from apps.catalog import services
from apps.catalog.models import Event, EventType
from apps.portals.models import Site
from tests.conftest import harvey_item


def publish_all(user):
    for ev in Event.objects.all():
        ev.format, ev.event_type = "offline", EventType.objects.get(code="standup")
        ev.save()
        services.approve(ev, Site.objects.get(code="ua"), user)


def test_calendar_page_renders(client, ref):
    r = client.get("/", HTTP_HOST="eventcalendar.com.ua")
    assert r.status_code == 200 and "fullcalendar" in r.content.decode().lower()


def test_api_returns_only_published_in_range(client, push, admin_user):
    push([harvey_item(1, date="2027-03-14"), harvey_item(2, date="2027-05-01")])
    push([harvey_item(3, date="2027-03-20")])
    publish_all(admin_user)
    Event.objects.filter(intake_items__external_id="3").update(state="pending")
    from apps.catalog.models import SitePublication
    SitePublication.objects.filter(event__intake_items__external_id="3").update(status="pending")
    r = client.get("/api/v1/events?from=2027-03-01&to=2027-04-01").json()["events"]
    assert [e["title"] for e in r] == ["Форум підприємців 1"]
    e = r[0]
    assert e["allDay"] and e["start"] == "2027-03-14" and e["end"] == "2027-03-15"
    assert e["city"] == "Київ" and e["time_unknown"] and e["type"] == "Стендап"


def test_multiday_event_found_by_overlap(client, push, admin_user):
    push([harvey_item(1, date="2027-02-27", end_date="2027-03-02")])
    publish_all(admin_user)
    r = client.get("/api/v1/events?from=2027-03-01&to=2027-04-01").json()["events"]
    assert len(r) == 1 and r[0]["end"] == "2027-03-03"


def test_api_validates_range(client, ref):
    assert client.get("/api/v1/events").status_code == 400
    assert client.get("/api/v1/events?from=2027-01-01&to=2027-06-01").status_code == 400
    assert client.get("/api/v1/events?from=2027-03-01&to=2027-04-01").json() == {"events": []}


def test_event_page(client, push, admin_user):
    from apps.catalog.models import TicketLink
    push([harvey_item(1, date="2027-03-14")])
    publish_all(admin_user)
    ev = Event.objects.get()
    api = client.get("/api/v1/events?from=2027-03-01&to=2027-04-01").json()["events"][0]
    assert api["url"] == f"/events/{ev.pk}-{ev.slug}/"
    r = client.get(api["url"])
    html = r.content.decode()
    assert r.status_code == 200 and "Форум підприємців 1" in html and "14 березня 2027" in html
    assert "Час уточнюється" in html and "Київ" in html and '"@type": "Event"' in html
    assert "Реєстрація та квитки" in html and "https://tickets.example/ev" in html
    # several ticket services: all shown, the first is the main button; «primary» mode shows one
    TicketLink.objects.create(event=ev, label="Concert.ua", url="https://concert.ua/x", position=1)
    TicketLink.objects.create(event=ev, label="Karabas", url="https://karabas.com/x", position=2)
    html = client.get(api["url"]).content.decode()
    assert "Квитки · Concert.ua" in html and "Квитки · Karabas" in html and "tickets.example" not in html
    ev.tickets_mode = "primary"
    ev.save()
    html = client.get(api["url"]).content.decode()
    assert "Concert.ua" in html and "Karabas" not in html
    # wrong slug → permanent redirect to the right one; unpublished → 404
    assert client.get(f"/events/{ev.pk}-old-name/").status_code == 301
    services.unpublish(ev, Site.objects.get(code="ua"), admin_user, reason="test")
    assert client.get(api["url"]).status_code == 404
