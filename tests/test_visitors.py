"""Search / category filter, «Знайшли помилку?», «Це моя подія» and the cabinet."""
import pytest
from django.contrib.auth.models import User
from django.core.cache import cache

from apps.catalog import services
from apps.catalog.models import Event, EventType
from apps.feedback.models import ErrorReport
from apps.organizers.models import Claim, EventGrant
from apps.organizers.services import approve_claim, user_events
from apps.portals.models import Site
from tests.conftest import harvey_item


@pytest.fixture(autouse=True)
def _clear_limits():
    cache.clear()


def publish(user, items):
    """items: [(harvey_item kwargs, type code)]"""
    from apps.intake.models import EventSource
    from apps.intake.services import receive
    src = EventSource.objects.get(code="harvey")
    for kw, typ in items:
        receive(src, harvey_item(**kw))
        ev = Event.objects.get(intake_items__external_id=str(kw["eid"]))
        ev.format, ev.event_type = "offline", EventType.objects.get(code=typ)
        ev.save()
        services.approve(ev, Site.objects.get(code="ua"), user)


@pytest.fixture
def three(harvey_token, admin_user):
    publish(admin_user, [({"eid": 1, "name": "Стендап Петрова", "date": "2099-03-14"}, "standup"),
                         ({"eid": 2, "name": "Джаз у парку", "date": "2099-03-20"}, "concert"),
                         ({"eid": 3, "name": "Стендап у Львові", "date": "2099-05-02", "city": "Львов"}, "standup")])
    return Event.objects.order_by("id")


def test_category_filter_shows_only_types_with_events(client, three):
    html = client.get("/").content.decode()
    assert 'value="standup"' in html and 'value="concert"' in html and 'value="forum"' not in html
    assert ">2</small>" in html                                   # two stand-ups


def test_api_filters_by_type_and_query(client, three):
    rng = "from=2099-03-01&to=2099-04-01"
    assert len(client.get(f"/api/v1/events?{rng}").json()["events"]) == 2
    assert [e["title"] for e in client.get(f"/api/v1/events?{rng}&type=concert").json()["events"]] == ["Джаз у парку"]
    assert [e["title"] for e in client.get(f"/api/v1/events?{rng}&type=concert&type=standup").json()["events"]] == \
        ["Стендап Петрова", "Джаз у парку"]
    assert [e["title"] for e in client.get(f"/api/v1/events?{rng}&q=стендап").json()["events"]] == ["Стендап Петрова"]


def test_search_finds_events_in_other_months(client, three):
    r = client.get("/api/v1/search?q=Стендап").json()
    assert r["total"] == 2 and [x["title"] for x in r["results"]] == ["Стендап Петрова", "Стендап у Львові"]
    assert r["results"][1]["city"] == "Львів" and r["results"][0]["date"] == "14 березня 2099"
    assert client.get("/api/v1/search").json() == {"results": [], "total": 0}


def test_filters_survive_in_url(client, three):
    html = client.get("/?q=джаз&type=concert").content.decode()
    assert 'value="джаз"' in html and 'value="concert" checked' in html


def test_error_report(client, three):
    ev = three[0]
    r = client.post(f"/events/{ev.pk}/report/", {"kind": "date", "message": "Перенесли на 15 березня", "email": ""})
    assert r.status_code == 302
    rep = ErrorReport.objects.get()
    assert rep.event == ev and rep.kind == "date" and rep.status == "new"
    # bots fill the hidden field: nothing is stored, the answer looks the same
    client.post(f"/events/{ev.pk}/report/", {"kind": "other", "message": "spam", "website": "http://spam"})
    assert ErrorReport.objects.count() == 1
    # empty message is refused
    client.post(f"/events/{ev.pk}/report/", {"kind": "other", "message": ""})
    assert ErrorReport.objects.count() == 1


def test_error_report_rate_limited(client, three):
    ev = three[0]
    for i in range(12):
        client.post(f"/events/{ev.pk}/report/", {"kind": "other", "message": f"m{i}"})
    assert ErrorReport.objects.count() == 10


def test_claim_flow_register_then_moderator_approves(client, three, admin_user):
    ev = three[1]
    r = client.get(f"/events/{ev.pk}/claim/")
    assert r.status_code == 302 and r["Location"] == f"/cabinet/login/?next=/events/{ev.pk}/claim/"
    r = client.post("/cabinet/register/", {"name": "Олена", "email": "Olena@Jazz.ua", "password": "dzhaz-u-parku-2099",
                                           "next": f"/events/{ev.pk}/claim/"})
    assert r.status_code == 302 and r["Location"] == f"/events/{ev.pk}/claim/"
    assert User.objects.get(username="olena@jazz.ua").first_name == "Олена"
    r = client.post(f"/events/{ev.pk}/claim/", {"org_name": "Jazz Park", "role": "організатор", "phone": "+380671234567",
                                                "evidence": "https://jazz.ua/team"})
    assert r.status_code == 302 and r["Location"] == "/cabinet/"
    claim = Claim.objects.get()
    assert claim.status == "open" and claim.method == "manual"
    user = claim.user
    # no rights before the moderator decides
    assert not user_events(user).exists()
    assert "на перевірці" in client.get("/cabinet/").content.decode()
    # second visit shows «already sent», no duplicate
    assert "Заявку вже надіслано" in client.get(f"/events/{ev.pk}/claim/").content.decode()
    approve_claim(claim, admin_user)
    assert list(user_events(user)) == [ev]
    ev.refresh_from_db()
    assert ev.organization.name == "Jazz Park" and EventGrant.objects.count() == 1
    html = client.get("/cabinet/").content.decode()
    assert "Джаз у парку" in html and "підтверджено" in html
    assert client.get(f"/events/{ev.pk}/claim/").status_code == 302     # already theirs


def test_login_and_wrong_password(client, three):
    User.objects.create_user(username="a@b.ua", email="a@b.ua", password="long-enough-pass-1")
    r = client.post("/cabinet/login/", {"email": "a@b.ua", "password": "wrong"})
    assert "Невірний email або пароль" in r.content.decode()
    r = client.post("/cabinet/login/", {"email": "A@b.ua", "password": "long-enough-pass-1"})
    assert r.status_code == 302 and r["Location"] == "/cabinet/"
    r = client.post("/cabinet/login/", {"email": "a@b.ua", "password": "x", "next": "https://evil.example/"})
    assert r["Location"] == "/cabinet/"                                # no open redirect


def test_register_validation(client, three):
    r = client.post("/cabinet/register/", {"name": "X", "email": "x@x.ua", "password": "12345"})
    assert r.status_code == 200 and not User.objects.filter(username="x@x.ua").exists()
    User.objects.create_user(username="dup@x.ua", email="dup@x.ua", password="long-enough-pass-1")
    r = client.post("/cabinet/register/", {"name": "X", "email": "DUP@x.ua", "password": "another-long-pass-2"})
    assert "уже зареєстровано" in r.content.decode()


def test_claim_on_unpublished_event_is_404(client, three, admin_user):
    ev = three[0]
    services.unpublish(ev, Site.objects.get(code="ua"), admin_user, reason="t")
    assert client.get(f"/events/{ev.pk}/claim/").status_code == 404
    assert client.post(f"/events/{ev.pk}/report/", {"kind": "other", "message": "x"}).status_code == 404


def test_admin_pages_for_new_sections(admin_client, three):
    for p in ("/admin/", "/admin/feedback/errorreport/", "/admin/organizers/claim/", "/admin/organizers/organization/"):
        assert admin_client.get(p).status_code == 200, p
