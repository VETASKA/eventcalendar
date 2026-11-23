"""Stage 6: a second storefront (another country) on the same database shows only its own records."""
import pytest
from django.core.cache import cache

from apps.catalog import services
from apps.catalog.models import Event, EventType
from apps.geo.models import City, Country
from apps.intake.models import EventSource
from apps.intake.services import receive
from apps.portals.models import Site, SiteDomain
from apps.subscriptions.models import Subscription
from tests.conftest import harvey_item

PL_HOST = "pl.test.eventcalendar.local"


@pytest.fixture
def two_sites(harvey_token, admin_user):
    cache.clear()
    ua = Site.objects.get(code="ua")
    pl = Site.objects.create(code="pl-test", name="EventCalendar Polska", default_locale="pl",
                             locales=["pl", "en", "uk"], timezone="Europe/Warsaw")
    pl.countries.add(Country.objects.get(code="PL"))
    SiteDomain.objects.create(site=pl, host=PL_HOST, is_primary=True)
    warsaw = City.objects.create(country_id="PL", name="Warszawa", names={"uk": "Варшава", "en": "Warsaw"})
    src = EventSource.objects.get(code="harvey")
    receive(src, harvey_item(1, name="Київський форум", date="2099-03-10"))
    receive(src, harvey_item(2, name="Warszawski meetup", country="PL", city="Warszawa", date="2099-03-12"))
    evs = {}
    for eid in ("1", "2"):
        ev = Event.objects.get(intake_items__external_id=eid)
        ev.format, ev.event_type = "offline", EventType.objects.get(code="forum")
        ev.save()
        if eid == "2":
            ev.occurrences.update(city=warsaw)
        evs[eid] = ev
    services.approve(evs["1"], ua, admin_user)
    services.approve(evs["2"], pl, admin_user)
    return ua, pl, evs


def test_each_site_lists_only_its_events(client, two_sites):
    ua, pl, evs = two_sites
    ua_api = client.get("/api/v1/events?from=2099-03-01&to=2099-03-31").json()
    pl_api = client.get("/api/v1/events?from=2099-03-01&to=2099-03-31", HTTP_HOST=PL_HOST).json()
    flat = lambda d: str(d)
    assert "Київський форум" in flat(ua_api) and "Warszawski" not in flat(ua_api)
    assert "Warszawski meetup" in flat(pl_api) and "Київський" not in flat(pl_api)


def test_foreign_event_page_is_404_and_sitemap_is_per_site(client, two_sites):
    ua, pl, evs = two_sites
    assert client.get(f"/events/{evs['1'].pk}/", HTTP_HOST=PL_HOST).status_code == 404
    assert client.get(f"/events/{evs['2'].pk}/").status_code == 404
    page = client.get(f"/events/{evs['2'].pk}/", HTTP_HOST=PL_HOST, follow=True).content.decode()
    assert f'<link rel="canonical" href="http://{PL_HOST}/events/{evs["2"].pk}-' in page
    sm = client.get("/sitemap.xml", HTTP_HOST=PL_HOST).content.decode()
    assert f"/events/{evs['2'].pk}-" in sm and f"/events/{evs['1'].pk}-" not in sm
    assert PL_HOST in client.get("/robots.txt", HTTP_HOST=PL_HOST).content.decode()


def test_site_geography_is_enforced(two_sites, admin_user):
    ua, pl, evs = two_sites
    with pytest.raises(services.PublishError):
        services.approve(evs["1"], pl, admin_user)          # a Kyiv event can't go on the Polish storefront


def test_unknown_host_is_not_served(client, two_sites):
    Site.objects.filter(is_default=True).update(is_default=False)
    assert client.get("/", HTTP_HOST="evil.example").status_code == 404
    assert client.get("/healthz", HTTP_HOST="evil.example").status_code == 200


def test_subscriptions_belong_to_the_site_they_were_made_on(client, two_sites):
    client.post("/subscribe/", {"channel": "email", "email": "pl@ex.pl"}, HTTP_HOST=PL_HOST)
    client.post("/subscribe/", {"channel": "email", "email": "ua@ex.ua"})
    assert Subscription.objects.get(address="pl@ex.pl").site.code == "pl-test"
    assert Subscription.objects.get(address="ua@ex.ua").site.code == "ua"
