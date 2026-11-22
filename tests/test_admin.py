from apps.catalog.models import Event, EventType, SitePublication
from tests.conftest import harvey_item


def test_queue_and_bulk_approve(admin_client, push):
    push([harvey_item(1), harvey_item(2)])
    good = Event.objects.order_by("id").first()
    good.format, good.event_type = "offline", EventType.objects.get(code="forum")
    good.save()
    r = admin_client.get("/admin/catalog/event/?flag=no_type")
    assert r.status_code == 200
    for path in ("/admin/catalog/event/", f"/admin/catalog/event/{good.pk}/change/", "/admin/intake/intakeitem/",
                 "/admin/geo/city/", "/admin/audit/auditlog/", "/admin/", "/admin/auth/user/"):
        assert admin_client.get(path).status_code == 200, path
    ids = list(Event.objects.values_list("pk", flat=True))
    r = admin_client.post("/admin/catalog/event/", {"action": "bulk_approve", "_selected_action": ids})
    assert r.status_code == 200 and "одобрить 2" in r.content.decode()
    assert not SitePublication.objects.filter(status="published").exists()   # confirmation first
    r = admin_client.post("/admin/catalog/event/", {"action": "bulk_approve", "_selected_action": ids,
                                                     "confirm": "yes"}, follow=True)
    text = r.content.decode()
    assert "Опубликовано: 1" in text and "не вказано тип" in text
    assert SitePublication.objects.get(event=good).status == "published"


def test_healthz_and_unknown_host(client, ref):
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/", HTTP_HOST="eventcalendar.com.ua").status_code == 200


def test_event_list_sorts_by_date_city_country(admin_client, push):
    push([harvey_item(1, name="Б", date="2027-05-01", city="Львов"),
          harvey_item(2, name="А", date="2027-03-01", city="Киев"),
          harvey_item(3, name="В", date=None, city="", country="PL"),
          harvey_item(4, name="Г", date="2027-04-01", city="Одесса", country="")])

    def titles(order):
        html = admin_client.get(f"/admin/catalog/event/?o={order}").content.decode()
        found = [(html.find(f">{t}</a>"), t) for t in "АБВГ"]
        return "".join(t for pos, t in sorted(found) if pos >= 0)

    assert titles("2") == "АГБВ"        # by date, no date last
    assert titles("-2") == "БГАВ"       # newest first, no date still last
    assert titles("3") == "АБГВ"        # by city: Київ, Львів, Одеса, then none
    assert titles("-3") == "ГБАВ"
    assert titles("4")[0] == "В" and titles("4")[-1] == "Г"     # Польща, Україна ×2, no country last
    assert titles("-4")[0] in "АБ" and titles("-4")[-1] == "Г"
