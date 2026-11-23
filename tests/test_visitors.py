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
    page = client.get("/").content.decode()
    html = page[page.index('data-key="type"'):page.index('id="calendar"')]      # the filter, not the subscribe form
    box = 'type="checkbox" name="type" value="{}"'
    assert box.format("standup") in html and box.format("concert") in html and box.format("forum") not in html
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


def test_claim_flow_register_then_moderator_approves(client, three, admin_user, mailoutbox):
    import re
    ev = three[1]
    r = client.get(f"/events/{ev.pk}/claim/")
    assert r.status_code == 302 and r["Location"] == f"/cabinet/login/?next=/events/{ev.pk}/claim/"
    r = client.post("/cabinet/register/", {"name": "Олена", "email": "Olena@Jazz.ua", "password": "dzhaz-u-parku-2099",
                                           "next": f"/events/{ev.pk}/claim/"})
    assert r.status_code == 302 and r["Location"] == f"/events/{ev.pk}/claim/"
    assert User.objects.get(username="olena@jazz.ua").first_name == "Олена"
    # email must be confirmed first
    assert client.get(f"/events/{ev.pk}/claim/")["Location"] == "/cabinet/"
    link = re.search(r"https?://\S+/cabinet/verify/\S+/", mailoutbox[0].body).group(0)
    client.get(link.split("testserver", 1)[1])
    r = client.post(f"/events/{ev.pk}/claim/", {"org_name": "Jazz Park", "role": "організатор", "phone": "+380671234567",
                                                "evidence": "https://jazz.ua/team", "method": "manual"})
    claim = Claim.objects.get()
    assert r["Location"] == f"/cabinet/claims/{claim.pk}/"
    assert claim.status == "open" and claim.method == "manual"
    user = claim.user
    assert not user_events(user).exists()                       # no rights before the moderator decides
    assert "на перевірці" in client.get("/cabinet/").content.decode()
    assert client.get(f"/events/{ev.pk}/claim/")["Location"] == f"/cabinet/claims/{claim.pk}/"   # no duplicate
    approve_claim(claim, admin_user)
    assert list(user_events(user)) == [ev]
    ev.refresh_from_db()
    assert ev.organization.name == "Jazz Park" and EventGrant.objects.count() == 1
    html = client.get("/cabinet/").content.decode()
    assert "Джаз у парку" in html and "Редагувати" in html
    assert client.get(f"/events/{ev.pk}/claim/").status_code == 302     # already theirs
    assert "Подію додано у ваш кабінет" in mailoutbox[-1].subject


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


@pytest.fixture(autouse=True)
def _offline_fetch(monkeypatch):
    """Suggested links are not fetched from the internet in tests: the page «does not answer»."""
    from apps.intake import fetcher, tasks
    monkeypatch.setattr(tasks, "safe_fetch", lambda url, **kw: fetcher.FetchResult(False, url, error="offline",
                                                                                   temporary=True))


def test_suggest_event_goes_to_moderation(client, three, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        r = client.post("/suggest/", {"url": "fest.com.ua/winter?utm_source=fb", "date": "2099-12-20", "city": "Одеса",
                                      "type": "festival", "email": "fan@ex.ua"})
    assert r.status_code == 302
    from apps.intake.models import IntakeItem
    item = IntakeItem.objects.get(source__code="form")
    ev = item.event
    assert ev.state == "pending" and ev.title == "fest.com.ua" and ev.source_url == "https://fest.com.ua/winter?utm_source=fb"
    assert ev.event_type.code == "festival" and "from_visitor" in ev.review_flags and "no_type" not in ev.review_flags
    assert "fetch_failed" in ev.review_flags
    o = ev.occurrences.get()
    assert str(o.start_date) == "2099-12-20" and o.city.name == "Одеса"
    assert item.payload["email"] == "fan@ex.ua"
    assert ev.publications.get().status == "pending"            # not visible before moderation
    # the same link again (other tracking params) → no second card
    with django_capture_on_commit_callbacks(execute=True):
        client.post("/suggest/", {"url": "https://www.fest.com.ua/winter/"})
    assert Event.objects.filter(source_url__contains="fest.com.ua").count() == 1


def test_suggest_only_link_is_required(client, three, django_capture_on_commit_callbacks):
    assert client.post("/suggest/", {"url": ""}).status_code == 302
    from apps.intake.models import IntakeItem
    assert not IntakeItem.objects.filter(source__code="form").exists()
    with django_capture_on_commit_callbacks(execute=True):
        client.post("/suggest/", {"url": "https://only-link.ua/e"})
    ev = IntakeItem.objects.get(source__code="form").event
    assert {"no_date", "no_type"} <= set(ev.review_flags) and not ev.occurrences.exists()


def test_suggest_known_published_event_points_to_it(client, three):
    ev = three[0]
    r = client.post("/suggest/", {"url": ev.source_url})
    from urllib.parse import unquote
    assert unquote(r["Location"]) == f"/events/{ev.pk}-{ev.slug}/"


def test_suggest_spam_protection(client, three):
    client.post("/suggest/", {"url": "https://spam.example/", "website": "x"})
    for i in range(12):
        client.post("/suggest/", {"url": f"https://e{i}.ua/"})
    from apps.intake.models import IntakeItem
    assert IntakeItem.objects.filter(source__code="form").count() == 10


def test_home_has_suggest_form(client, three):
    html = client.get("/").content.decode()
    assert "Запропонувати подію" in html and 'name="url"' in html and 'value="festival"' in html
