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
                 "/admin/geo/city/", "/admin/audit/auditlog/"):
        assert admin_client.get(path).status_code == 200, path
    ids = list(Event.objects.values_list("pk", flat=True))
    r = admin_client.post("/admin/catalog/event/", {"action": "bulk_approve", "_selected_action": ids})
    assert r.status_code == 200 and "Схвалити 2" in r.content.decode()
    assert not SitePublication.objects.filter(status="published").exists()   # confirmation first
    r = admin_client.post("/admin/catalog/event/", {"action": "bulk_approve", "_selected_action": ids,
                                                     "confirm": "yes"}, follow=True)
    text = r.content.decode()
    assert "Опубліковано: 1" in text and "не вказано тип" in text
    assert SitePublication.objects.get(event=good).status == "published"


def test_healthz_and_unknown_host(client, ref):
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/", HTTP_HOST="eventcalendar.com.ua").status_code == 200
