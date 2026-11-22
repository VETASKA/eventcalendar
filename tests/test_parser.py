"""Stage 3: a suggested link is fetched, read and queued; protection when accepting URLs."""
from datetime import date

import httpx
import pytest

from apps.catalog.models import Event, SitePublication
from apps.intake import fetcher, tasks
from apps.intake.fetcher import Blocked, FetchResult, check_url, safe_fetch
from apps.intake.models import IntakeItem
from apps.intake.parser import parse

EVENT_PAGE = """<html lang="uk"><head><title>Jazz Fest — квитки</title>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Organization","name":"X"},
{"@type":"MusicEvent","name":"Odesa Jazz Fest 2099","startDate":"2099-09-12T19:00:00+03:00",
 "endDate":"2099-09-12T23:00:00+03:00","eventAttendanceMode":"https://schema.org/OfflineEventAttendanceMode",
 "location":{"@type":"Place","name":"Зелений театр","address":{"@type":"PostalAddress","addressLocality":"Одеса",
 "streetAddress":"вул. Маразліївська, 1","addressCountry":"UA"}},
 "offers":{"@type":"Offer","price":"800","priceCurrency":"UAH","url":"https://tickets.example/jazz"},
 "organizer":{"@type":"Organization","name":"Jazz Agency","url":"https://jazz.agency"},
 "description":"Три сцени, двадцять гуртів."}]}</script></head><body>…</body></html>"""
TEXT_PAGE = "<html><head><title>Майстер-клас з кераміки</title></head><body>Чекаємо 14 березня 2099 о 18:00</body></html>"
NEXT_YEAR = date.today().year + 1
TEXT_PAGE_SOON = TEXT_PAGE.replace("2099", str(NEXT_YEAR))
NOT_EVENT = "<html><head><title>Про компанію</title></head><body>Ми робимо сайти з 2010 року.</body></html>"


def test_parse_schema_org_event():
    p = parse(EVENT_PAGE)
    assert p["kind"] == "event" and p["via"] == "schema.org" and p["title"] == "Odesa Jazz Fest 2099"
    assert p["start_date"] == "2099-09-12" and p["starts_at"].startswith("2099-09-12T19:00")
    assert p["city"] == "Одеса" and p["venue"] == "Зелений театр" and p["format"] == "offline"
    assert p["price"] == "800 UAH" and p["ticket_url"] == "https://tickets.example/jazz"
    assert p["organizer"] == "Jazz Agency" and p["lang"] == "uk"


def test_parse_text_date_is_maybe_and_plain_page_is_not_event():
    p = parse(TEXT_PAGE, today=date(2098, 1, 1))
    assert p["kind"] == "maybe" and p["start_date"] == "2099-03-14" and p["title"] == "Майстер-клас з кераміки"
    assert parse(NOT_EVENT)["kind"] == "no"
    assert parse("<html>broken <script type='application/ld+json'>{oops</script>")["kind"] == "no"


@pytest.mark.parametrize("url", ["http://localhost/x", "http://127.0.0.1/", "http://10.0.0.5/", "http://192.168.1.1/",
                                 "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "ftp://example.com/",
                                 "http://example.com:8080/", "http://user:pass@example.com/", "file:///etc/passwd",
                                 "http://db.internal/"])
def test_blocked_urls(url):
    with pytest.raises(Blocked):
        check_url(url, resolver=lambda h: ["93.184.216.34"])


def test_host_resolving_to_private_address_is_blocked():
    with pytest.raises(Blocked):
        check_url("https://evil.example/", resolver=lambda h: ["93.184.216.34", "10.1.2.3"])


def test_redirect_to_internal_address_is_blocked():
    def handler(req):
        if req.url.host == "public.example":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
        return httpx.Response(200, text="secret", headers={"content-type": "text/html"})
    c = httpx.Client(transport=httpx.MockTransport(handler))
    r = safe_fetch("https://public.example/e", client=c,
                   resolver=lambda h: ["127.0.0.1"] if h == "127.0.0.1" else ["93.184.216.34"])
    assert not r.ok and "blocked" in r.error and "secret" not in r.html


def test_size_and_type_limits():
    big = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=b"x" * (fetcher.MAX_BYTES + 5000), headers={"content-type": "text/html"})))
    r = safe_fetch("https://a.example/", client=big, resolver=lambda h: ["93.184.216.34"])
    assert r.ok and len(r.html) == fetcher.MAX_BYTES
    pdf = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})))
    assert not safe_fetch("https://a.example/f.pdf", client=pdf, resolver=lambda h: ["93.184.216.34"]).ok


# ── the whole funnel ────────────────────────────────────────────────────────

def fake_fetch(pages: dict, calls: list):
    def f(url, **kw):
        calls.append(url)
        v = pages[url]
        return v if isinstance(v, FetchResult) else FetchResult(True, url, html=v, status=200)
    return f


@pytest.fixture
def suggest(client, harvey_token, django_capture_on_commit_callbacks):
    def go(url, **extra):
        with django_capture_on_commit_callbacks(execute=True):
            return client.post("/suggest/", {"url": url, **extra})
    return go


def test_event_link_becomes_a_card_in_the_queue(suggest, monkeypatch):
    calls = []
    monkeypatch.setattr(tasks, "safe_fetch", fake_fetch({"https://jazz.example/fest": EVENT_PAGE}, calls))
    suggest("https://jazz.example/fest", type="festival")
    item = IntakeItem.objects.get(source__code="form")
    assert item.status == "event_detected" and calls == ["https://jazz.example/fest"]
    e = item.event
    assert e.title == "Odesa Jazz Fest 2099" and e.format == "offline" and e.event_type.code == "festival"
    assert e.registration_url == "https://tickets.example/jazz" and e.price_text == "800 UAH"
    assert e.summary == ""                                   # the source's text is a hint, not our summary
    assert item.normalized["hint_description"] == "Три сцени, двадцять гуртів."
    o = e.occurrences.get()
    assert o.city.name == "Одеса" and o.venue == "Зелений театр" and o.precision == "datetime"
    assert o.starts_at.isoformat().startswith("2099-09-12T16:00")          # stored in UTC
    assert e.state == "pending" and SitePublication.objects.get(event=e).status == "pending"
    # not visible anywhere public before moderation
    assert "Odesa Jazz" not in str(__import__("json").dumps(
        __import__("django.test", fromlist=["Client"]).Client().get(
            "/api/v1/events?from=2099-09-01&to=2099-10-01").json()))


def test_not_event_link_is_kept_without_a_card(suggest, monkeypatch):
    monkeypatch.setattr(tasks, "safe_fetch", fake_fetch({"https://studio.example/about": NOT_EVENT}, []))
    suggest("https://studio.example/about")
    item = IntakeItem.objects.get(source__code="form")
    assert item.status == "not_event" and item.event is None


def test_temporary_error_is_retried_then_succeeds(suggest, monkeypatch):
    attempts = []

    def flaky(url, **kw):
        attempts.append(url)
        if len(attempts) < 3:
            return FetchResult(False, url, status=503, error="HTTP 503", temporary=True)
        return FetchResult(True, url, html=TEXT_PAGE_SOON, status=200)
    monkeypatch.setattr(tasks, "safe_fetch", flaky)
    suggest("https://craft.example/class")
    item = IntakeItem.objects.get(source__code="form")
    assert len(attempts) == 3 and item.status == "needs_review" and item.event.title == "Майстер-клас з кераміки"
    assert str(item.event.occurrences.get().start_date) == f"{NEXT_YEAR}-03-14"
    assert parse(TEXT_PAGE)["kind"] == "no"          # a date 70 years ahead is not believed


def test_site_down_after_all_retries_still_reaches_the_moderator(suggest, monkeypatch):
    monkeypatch.setattr(tasks, "safe_fetch",
                        lambda url, **kw: FetchResult(False, url, error="ConnectTimeout", temporary=True))
    suggest("https://down.example/e", date="2099-05-01", city="Київ")
    item = IntakeItem.objects.get(source__code="form")
    assert item.status == "needs_review" and "fetch_failed" in item.event.review_flags
    assert item.event.occurrences.get().city.name == "Київ"


def test_dead_link_is_not_event(suggest, monkeypatch):
    monkeypatch.setattr(tasks, "safe_fetch",
                        lambda url, **kw: FetchResult(False, url, status=404, error="HTTP 404"))
    suggest("https://gone.example/e")
    assert IntakeItem.objects.get(source__code="form").status == "not_event"
