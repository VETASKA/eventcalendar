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


def test_fill_format_and_type_in_the_list_then_bulk_approve(admin_client, push):
    from apps.catalog.models import Event, EventType, SitePublication
    push([harvey_item(1), harvey_item(2)])
    e1, e2 = Event.objects.order_by("id")
    forum = EventType.objects.get(code="forum")
    page = admin_client.get("/admin/catalog/event/?state__exact=pending").content.decode()
    assert f'name="form-0-format"' in page and f'name="form-0-event_type"' in page
    # one «Сохранить» for the page: only the first row gets values
    data = {"form-TOTAL_FORMS": "2", "form-INITIAL_FORMS": "2", "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000",
            "_save": "Сохранить"}
    rows = [(e1, "offline", forum.pk), (e2, "", "")]
    import re
    ids = dict((int(i), int(pk)) for i, pk in re.findall(r'name="form-(\d+)-id" value="(\d+)"', page))
    for i, pk in ids.items():
        ev, fmt, typ = next(r for r in rows if r[0].pk == pk)
        data.update({f"form-{i}-id": str(pk), f"form-{i}-format": fmt, f"form-{i}-event_type": str(typ)})
    r = admin_client.post("/admin/catalog/event/?state__exact=pending", data)
    assert r.status_code == 302, r.content.decode()[:2000]
    e1.refresh_from_db(); e2.refresh_from_db()
    assert e1.format == "offline" and e1.event_type == forum
    assert "no_format" not in e1.review_flags and "no_type" not in e1.review_flags
    assert {"format", "event_type"} <= set(e1.manual_fields)
    assert e2.format == "" and "no_type" in e2.review_flags
    admin_client.post("/admin/catalog/event/", {"action": "bulk_approve", "_selected_action": [e1.pk, e2.pk],
                                                 "confirm": "yes"})
    assert SitePublication.objects.get(event=e1).status == "published"
    assert SitePublication.objects.get(event=e2).status == "pending"
