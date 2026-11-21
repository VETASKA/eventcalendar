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
